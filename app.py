"""
WAS-110 Monitor - Main Application
Enhanced monitoring webapp for WAS-110 SFP+ ONT modules
"""
import os
import re
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Optional, Any

import paramiko
import pytz
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from notifications import notification_manager

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if Config.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__, static_folder='static')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Data storage
MAX_HISTORY_POINTS = Config.get_history_max_points()

history = {
    'timestamps': deque(maxlen=MAX_HISTORY_POINTS),
    'temp1': deque(maxlen=MAX_HISTORY_POINTS),
    'temp2': deque(maxlen=MAX_HISTORY_POINTS),
    'optical_temp': deque(maxlen=MAX_HISTORY_POINTS),
    'voltage': deque(maxlen=MAX_HISTORY_POINTS),
    'bias_current': deque(maxlen=MAX_HISTORY_POINTS),
    'tx_power': deque(maxlen=MAX_HISTORY_POINTS),
    'rx_power': deque(maxlen=MAX_HISTORY_POINTS),
}

current_data: Dict[str, Any] = {
    'connected': False,
    'last_update': None,
    'uptime': None,
    'firmware': None,
    'temp1': None,
    'temp2': None,
    'optical_temp': None,
    'voltage': None,
    'bias_current': None,
    'tx_power': None,
    'rx_power': None,
    'pon_mode': None,
    'onu_state': None,
    'loid_status': None,
}

connection_stats = {
    'successful_fetches': 0,
    'failed_fetches': 0,
    'last_error': None,
    'uptime_start': datetime.now().isoformat()
}

# SSH client management
ssh_client: Optional[paramiko.SSHClient] = None
ssh_lock = threading.Lock()


def get_ssh_client() -> Optional[paramiko.SSHClient]:
    """Get or create SSH client connection"""
    global ssh_client

    with ssh_lock:
        if ssh_client is not None:
            try:
                # Test if connection is still alive
                transport = ssh_client.get_transport()
                if transport and transport.is_active():
                    return ssh_client
            except Exception:
                pass
            # Connection lost, reset
            try:
                ssh_client.close()
            except Exception:
                pass
            ssh_client = None

        # Create new connection
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                Config.SFP_HOST,
                username=Config.SFP_USER,
                password=Config.SFP_ROOT_PASSWORD,
                timeout=10,
                banner_timeout=10
            )
            ssh_client = client
            logger.info(f"SSH connection established to {Config.SFP_HOST}")
            return ssh_client
        except Exception as e:
            logger.error(f"SSH connection failed: {e}")
            connection_stats['last_error'] = str(e)
            return None


def execute_command(command: str) -> Optional[str]:
    """Execute command via SSH and return output"""
    client = get_ssh_client()
    if not client:
        return None

    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        if error:
            logger.warning(f"Command stderr: {error}")
        return output
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        # Reset connection on failure
        global ssh_client
        with ssh_lock:
            try:
                ssh_client.close()
            except Exception:
                pass
            ssh_client = None
        return None


def parse_temperatures() -> Dict[str, Optional[float]]:
    """Parse temperature readings from thermal zones and SFP EEPROM"""
    temps = {'temp1': None, 'temp2': None, 'optical_temp': None}

    # Read thermal zones
    output = execute_command('cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null')
    if output:
        lines = output.strip().split('\n')
        for i, line in enumerate(lines[:2]):
            try:
                temp_milli = int(line.strip())
                temps[f'temp{i+1}'] = temp_milli / 1000.0
            except (ValueError, IndexError):
                pass

    # Read optical temperature from SFP EEPROM (A2 page, offset 96-97)
    output = execute_command('cat /sys/bus/i2c/devices/0-0051/eeprom 2>/dev/null | xxd -p -l 2 -s 96')
    if output:
        try:
            hex_val = output.strip()
            if len(hex_val) >= 4:
                temp_raw = int(hex_val[:4], 16)
                # Convert from signed 16-bit with 1/256 degree resolution
                if temp_raw > 32767:
                    temp_raw -= 65536
                temps['optical_temp'] = temp_raw / 256.0
        except (ValueError, Exception) as e:
            logger.debug(f"Failed to parse optical temp: {e}")

    return temps


def parse_optical_stats() -> Dict[str, Optional[float]]:
    """Parse optical interface statistics using pontop command"""
    stats = {
        'voltage': None,
        'bias_current': None,
        'tx_power': None,
        'rx_power': None
    }

    output = execute_command("pontop -b -g 'Optical Interface Status' 2>/dev/null")
    if not output:
        return stats

    # Parse voltage (typically in mV, convert to V)
    voltage_match = re.search(r'Voltage\s*:\s*([\d.]+)\s*(?:mV|V)', output, re.IGNORECASE)
    if voltage_match:
        voltage = float(voltage_match.group(1))
        stats['voltage'] = voltage / 1000.0 if voltage > 10 else voltage

    # Parse bias current (mA)
    bias_match = re.search(r'Bias\s*Current\s*:\s*([\d.]+)\s*mA', output, re.IGNORECASE)
    if bias_match:
        stats['bias_current'] = float(bias_match.group(1))

    # Parse TX power (dBm)
    tx_match = re.search(r'TX\s*Power\s*:\s*([-\d.]+)\s*dBm', output, re.IGNORECASE)
    if tx_match:
        stats['tx_power'] = float(tx_match.group(1))

    # Parse RX power (dBm)
    rx_match = re.search(r'RX\s*Power\s*:\s*([-\d.]+)\s*dBm', output, re.IGNORECASE)
    if rx_match:
        stats['rx_power'] = float(rx_match.group(1))

    return stats


def parse_system_info() -> Dict[str, Optional[str]]:
    """Parse additional system information"""
    info = {
        'uptime': None,
        'firmware': None,
        'pon_mode': None,
        'onu_state': None,
        'loid_status': None
    }

    # Get uptime
    output = execute_command('cat /proc/uptime 2>/dev/null')
    if output:
        try:
            uptime_seconds = float(output.split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            info['uptime'] = f"{days}d {hours}h {minutes}m"
        except (ValueError, IndexError):
            pass

    # Get firmware version
    output = execute_command('cat /etc/openwrt_release 2>/dev/null | grep DISTRIB_DESCRIPTION')
    if output:
        match = re.search(r"DISTRIB_DESCRIPTION='([^']+)'", output)
        if match:
            info['firmware'] = match.group(1)

    # Get PON status
    output = execute_command("pontop -b -g 'PON Status' 2>/dev/null")
    if output:
        pon_match = re.search(r'PON\s*Mode\s*:\s*(\w+)', output, re.IGNORECASE)
        if pon_match:
            info['pon_mode'] = pon_match.group(1)

        state_match = re.search(r'ONU\s*State\s*:\s*(\w+)', output, re.IGNORECASE)
        if state_match:
            info['onu_state'] = state_match.group(1)

    # Get LOID status
    output = execute_command("pontop -b -g 'LOID Status' 2>/dev/null")
    if output:
        loid_match = re.search(r'Status\s*:\s*(\w+)', output, re.IGNORECASE)
        if loid_match:
            info['loid_status'] = loid_match.group(1)

    return info


def fetch_data():
    """Fetch all data from WAS-110"""
    global current_data

    logger.debug("Fetching data from WAS-110...")

    try:
        temps = parse_temperatures()
        optical = parse_optical_stats()
        system = parse_system_info()

        now = datetime.now(pytz.timezone('America/Toronto'))

        # Update current data
        current_data.update({
            'connected': True,
            'last_update': now.isoformat(),
            **temps,
            **optical,
            **system
        })

        # Add to history
        history['timestamps'].append(now.isoformat())
        for key in ['temp1', 'temp2', 'optical_temp', 'voltage', 'bias_current', 'tx_power', 'rx_power']:
            value = current_data.get(key)
            history[key].append(value)

        connection_stats['successful_fetches'] += 1

        # Check thresholds and send notifications
        alerts = notification_manager.check_thresholds(current_data)
        if alerts:
            notification_manager.send_notifications(alerts)

        # Emit via WebSocket
        socketio.emit('data_update', {
            'current': current_data,
            'alerts': notification_manager.get_current_status()
        })

        # Save history periodically
        save_history()

        logger.debug(f"Data fetch successful: temp1={temps.get('temp1')}, optical_temp={temps.get('optical_temp')}")

    except Exception as e:
        logger.error(f"Data fetch failed: {e}")
        current_data['connected'] = False
        connection_stats['failed_fetches'] += 1
        connection_stats['last_error'] = str(e)


def save_history():
    """Save history to JSON file"""
    try:
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        filepath = os.path.join(Config.DATA_DIR, 'sfp_history.json')

        data = {
            'timestamps': list(history['timestamps']),
            'temp1': list(history['temp1']),
            'temp2': list(history['temp2']),
            'optical_temp': list(history['optical_temp']),
            'voltage': list(history['voltage']),
            'bias_current': list(history['bias_current']),
            'tx_power': list(history['tx_power']),
            'rx_power': list(history['rx_power']),
        }

        with open(filepath, 'w') as f:
            json.dump(data, f)

    except Exception as e:
        logger.error(f"Failed to save history: {e}")


def load_history():
    """Load history from JSON file"""
    try:
        filepath = os.path.join(Config.DATA_DIR, 'sfp_history.json')
        if not os.path.exists(filepath):
            return

        with open(filepath, 'r') as f:
            data = json.load(f)

        for key in history.keys():
            if key in data:
                for value in data[key]:
                    history[key].append(value)

        logger.info(f"Loaded {len(history['timestamps'])} history points")

    except Exception as e:
        logger.error(f"Failed to load history: {e}")


# Flask Routes
@app.route('/')
def index():
    """Serve main dashboard"""
    return send_from_directory('static', 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory('static', path)


@app.route('/api/data')
def get_data():
    """Get current data and history"""
    # Calculate time until next refresh
    next_refresh = Config.FETCH_INTERVAL_SECONDS

    return jsonify({
        'current': current_data,
        'history': {
            'timestamps': list(history['timestamps']),
            'temp1': list(history['temp1']),
            'temp2': list(history['temp2']),
            'optical_temp': list(history['optical_temp']),
            'voltage': list(history['voltage']),
            'bias_current': list(history['bias_current']),
            'tx_power': list(history['tx_power']),
            'rx_power': list(history['rx_power']),
        },
        'config': {
            'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
            'history_hours': Config.HISTORY_HOURS,
            'thresholds': {
                'temp_warning': Config.TEMP_WARNING,
                'temp_critical': Config.TEMP_CRITICAL,
                'optical_temp_warning': Config.OPTICAL_TEMP_WARNING,
                'optical_temp_critical': Config.OPTICAL_TEMP_CRITICAL,
                'rx_power_warning': Config.RX_POWER_WARNING,
                'rx_power_critical': Config.RX_POWER_CRITICAL,
                'tx_power_warning': Config.TX_POWER_WARNING,
                'tx_power_critical': Config.TX_POWER_CRITICAL,
            }
        },
        'next_refresh': next_refresh,
        'alerts': notification_manager.get_current_status()
    })


@app.route('/api/status')
def get_status():
    """Get connection status and stats"""
    return jsonify({
        'connected': current_data.get('connected', False),
        'last_update': current_data.get('last_update'),
        'stats': connection_stats,
        'config': {
            'sfp_host': Config.SFP_HOST,
            'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
            'notifications_enabled': Config.NOTIFICATIONS_ENABLED
        }
    })


@app.route('/api/alerts')
def get_alerts():
    """Get alert history"""
    return jsonify({
        'current': notification_manager.get_current_status(),
        'history': notification_manager.get_alert_history()
    })


@app.route('/api/config')
def get_config():
    """Get current configuration (safe values only)"""
    return jsonify({
        'sfp_host': Config.SFP_HOST,
        'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
        'history_hours': Config.HISTORY_HOURS,
        'thresholds': {
            'temp_warning': Config.TEMP_WARNING,
            'temp_critical': Config.TEMP_CRITICAL,
            'optical_temp_warning': Config.OPTICAL_TEMP_WARNING,
            'optical_temp_critical': Config.OPTICAL_TEMP_CRITICAL,
            'rx_power_warning': Config.RX_POWER_WARNING,
            'rx_power_critical': Config.RX_POWER_CRITICAL,
            'tx_power_warning': Config.TX_POWER_WARNING,
            'tx_power_critical': Config.TX_POWER_CRITICAL,
        },
        'notifications': {
            'enabled': Config.NOTIFICATIONS_ENABLED,
            'email_configured': bool(Config.SMTP_HOST),
            'webhook_configured': Config.WEBHOOK_ENABLED,
            'discord_configured': bool(Config.DISCORD_WEBHOOK_URL),
            'ntfy_configured': bool(Config.NTFY_URL and Config.NTFY_TOPIC)
        }
    })


@app.route('/api/export')
def export_data():
    """Export history data as JSON or CSV"""
    format_type = request.args.get('format', 'json')
    hours = int(request.args.get('hours', Config.HISTORY_HOURS))

    # Calculate cutoff time
    cutoff = datetime.now(pytz.timezone('America/Toronto')) - timedelta(hours=hours)

    # Filter data
    filtered_data = []
    for i, ts in enumerate(history['timestamps']):
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt >= cutoff:
                row = {
                    'timestamp': ts,
                    'temp1': history['temp1'][i],
                    'temp2': history['temp2'][i],
                    'optical_temp': history['optical_temp'][i],
                    'voltage': history['voltage'][i],
                    'bias_current': history['bias_current'][i],
                    'tx_power': history['tx_power'][i],
                    'rx_power': history['rx_power'][i],
                }
                filtered_data.append(row)
        except (ValueError, IndexError):
            pass

    if format_type == 'csv':
        import io
        import csv

        output = io.StringIO()
        if filtered_data:
            writer = csv.DictWriter(output, fieldnames=filtered_data[0].keys())
            writer.writeheader()
            writer.writerows(filtered_data)

        response = app.response_class(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=was110_export.csv'}
        )
        return response

    return jsonify(filtered_data)


@app.route('/api/refresh', methods=['POST'])
def trigger_refresh():
    """Manually trigger a data refresh"""
    fetch_data()
    return jsonify({'success': True, 'data': current_data})


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    logger.info("WebSocket client connected")
    socketio.emit('data_update', {
        'current': current_data,
        'alerts': notification_manager.get_current_status()
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info("WebSocket client disconnected")


# Initialize scheduler
scheduler = BackgroundScheduler()


def init_app():
    """Initialize the application"""
    # Load existing history
    load_history()

    # Initial data fetch
    fetch_data()

    # Schedule periodic fetches
    scheduler.add_job(
        fetch_data,
        'interval',
        seconds=Config.FETCH_INTERVAL_SECONDS,
        id='fetch_data'
    )
    scheduler.start()

    logger.info(f"WAS-110 Monitor started. Fetching every {Config.FETCH_INTERVAL_SECONDS}s")


if __name__ == '__main__':
    init_app()
    socketio.run(app, host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
