"""
WAS-110 Monitor - Main Application
Enhanced monitoring webapp for WAS-110 SFP+ ONT modules
"""
import os
import re
import json
import logging
import threading
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

# Store raw command outputs for debugging
debug_outputs = {}

# SSH client management
ssh_client: Optional[paramiko.SSHClient] = None
ssh_lock = threading.Lock()


def get_ssh_client() -> Optional[paramiko.SSHClient]:
    """Get or create SSH client connection"""
    global ssh_client

    with ssh_lock:
        if ssh_client is not None:
            try:
                transport = ssh_client.get_transport()
                if transport and transport.is_active():
                    return ssh_client
            except Exception:
                pass
            try:
                ssh_client.close()
            except Exception:
                pass
            ssh_client = None

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                Config.SFP_HOST,
                port=Config.SFP_PORT,
                username=Config.SFP_USER,
                password=Config.SFP_ROOT_PASSWORD,
                timeout=10,
                banner_timeout=10
            )
            ssh_client = client
            logger.info(f"SSH connection established to {Config.SFP_HOST}:{Config.SFP_PORT}")
            return ssh_client
        except Exception as e:
            logger.error(f"SSH connection failed: {e}")
            connection_stats['last_error'] = str(e)
            return None


def execute_command(command: str, store_key: str = None) -> Optional[str]:
    """Execute command via SSH and return output"""
    client = get_ssh_client()
    if not client:
        return None

    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')

        # Store for debugging
        if store_key:
            debug_outputs[store_key] = {
                'command': command,
                'stdout': output,
                'stderr': error,
                'timestamp': datetime.now().isoformat()
            }

        if error and 'not found' not in error.lower():
            logger.debug(f"Command stderr for {command}: {error}")

        return output
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
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
    output = execute_command('cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null', 'thermal')
    if output:
        lines = output.strip().split('\n')
        for i, line in enumerate(lines[:2]):
            try:
                temp_milli = int(line.strip())
                temps[f'temp{i+1}'] = temp_milli / 1000.0
            except (ValueError, IndexError):
                pass

    # Try multiple methods to get optical temperature
    # Method 1: Direct EEPROM read (SFP DDM A2 page)
    output = execute_command('hexdump -C /sys/bus/i2c/devices/0-0051/eeprom 2>/dev/null | head -20', 'eeprom_hex')

    # Method 2: Try ethtool if available
    output = execute_command('ethtool -m eth0 2>/dev/null | grep -i temp', 'ethtool')
    if output:
        match = re.search(r'Module temperature\s*:\s*([\d.]+)', output)
        if match:
            temps['optical_temp'] = float(match.group(1))

    # Method 3: Try sfp-bus
    if temps['optical_temp'] is None:
        output = execute_command('cat /sys/class/hwmon/hwmon*/temp1_input 2>/dev/null', 'hwmon')
        if output:
            try:
                temps['optical_temp'] = int(output.strip()) / 1000.0
            except (ValueError, Exception):
                pass

    # Method 4: Read from pontop.txt (parsed later in optical stats)
    if temps['optical_temp'] is None:
        output = execute_command('cat /tmp/pontop.txt 2>/dev/null')
        if output:
            # Match "Optical transceiver temperature : 48 deg C"
            match = re.search(r'Optical transceiver temperature\s*:\s*(\d+)\s*deg', output)
            if match:
                temps['optical_temp'] = float(match.group(1))

    return temps


def parse_optical_stats() -> Dict[str, Optional[float]]:
    """Parse optical interface statistics"""
    stats = {
        'voltage': None,
        'bias_current': None,
        'tx_power': None,
        'rx_power': None
    }

    # Try pontop command (common on WAS-110)
    # pontop -b saves to /tmp/pontop.txt, so we run it then read the file
    execute_command("pontop -b 2>/dev/null", 'pontop_full')
    output = execute_command("cat /tmp/pontop.txt 2>/dev/null", 'pontop_content')

    if output:
        debug_outputs['pontop_parsed'] = output

        # Parse voltage - multiple patterns
        voltage_patterns = [
            r'[Vv]oltage\s*[:\s]\s*([\d.]+)\s*(?:mV|V)',
            r'VCC\s*[:\s]\s*([\d.]+)\s*(?:mV|V)',
            r'Supply\s*[Vv]oltage\s*[:\s]\s*([\d.]+)',
        ]
        for pattern in voltage_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                voltage = float(match.group(1))
                stats['voltage'] = voltage / 1000.0 if voltage > 10 else voltage
                break

        # Parse bias current - multiple patterns
        bias_patterns = [
            r'[Bb]ias\s*[Cc]urrent\s*[:\s]\s*([\d.]+)\s*mA',
            r'TX\s*[Bb]ias\s*[:\s]\s*([\d.]+)',
            r'Laser\s*[Bb]ias\s*[:\s]\s*([\d.]+)',
        ]
        for pattern in bias_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                stats['bias_current'] = float(match.group(1))
                break

        # Parse TX power - multiple patterns
        tx_patterns = [
            r'TX\s*[Pp]ower\s*[:\s]\s*([-\d.]+)\s*dBm',
            r'[Tt]ransmit\s*[Pp]ower\s*[:\s]\s*([-\d.]+)',
            r'Tx_Power\s*[:\s]\s*([-\d.]+)',
        ]
        for pattern in tx_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                stats['tx_power'] = float(match.group(1))
                break

        # Parse RX power - multiple patterns
        rx_patterns = [
            r'RX\s*[Pp]ower\s*[:\s]\s*([-\d.]+)\s*dBm',
            r'[Rr]eceive\s*[Pp]ower\s*[:\s]\s*([-\d.]+)',
            r'Rx_Power\s*[:\s]\s*([-\d.]+)',
        ]
        for pattern in rx_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                stats['rx_power'] = float(match.group(1))
                break

    # Try ethtool as fallback
    if stats['tx_power'] is None or stats['rx_power'] is None:
        output = execute_command('ethtool -m eth0 2>/dev/null', 'ethtool_full')
        if output:
            if stats['tx_power'] is None:
                match = re.search(r'Laser output power\s*:\s*([-\d.]+)\s*dBm', output)
                if match:
                    stats['tx_power'] = float(match.group(1))

            if stats['rx_power'] is None:
                match = re.search(r'Receiver signal.*power\s*:\s*([-\d.]+)\s*dBm', output)
                if match:
                    stats['rx_power'] = float(match.group(1))

            if stats['voltage'] is None:
                match = re.search(r'Module voltage\s*:\s*([\d.]+)', output)
                if match:
                    stats['voltage'] = float(match.group(1))

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

    # Get firmware version - try multiple methods
    output = execute_command('cat /etc/openwrt_release 2>/dev/null', 'firmware')
    if output:
        match = re.search(r"DISTRIB_DESCRIPTION='([^']+)'", output)
        if match:
            info['firmware'] = match.group(1)

    if not info['firmware']:
        output = execute_command('cat /etc/version 2>/dev/null')
        if output:
            info['firmware'] = output.strip()

    # Get PON status - read from pontop.txt (already generated by parse_optical_stats)
    output = execute_command("cat /tmp/pontop.txt 2>/dev/null", 'pon_status')
    if output:
        # PON Mode - detect from capability or PLOAM status
        # Look for "G.987|G.989|G.9807" or specific mode indicators
        if 'G.9807' in output or 'XGS-PON' in output.upper():
            info['pon_mode'] = 'XGS-PON'
        elif 'G.989' in output or 'XGPON' in output.upper():
            info['pon_mode'] = 'XG-PON'
        elif 'G.987' in output or 'GPON' in output.upper():
            info['pon_mode'] = 'GPON'
        elif 'EPON' in output.upper():
            info['pon_mode'] = 'EPON'

        # ONU State - from PON PLOAM Status
        ploam_match = re.search(r'PON PLOAM Status\s*:\s*(O\d+(?:\.\d+)?)[,\s]*([^\n]*)', output)
        if ploam_match:
            state = ploam_match.group(1)
            desc = ploam_match.group(2).strip() if ploam_match.group(2) else ''
            info['onu_state'] = f"{state} ({desc})" if desc else state

    # Alternative: Try onu command
    if not info['onu_state']:
        output = execute_command('onu ploam_state_get 2>/dev/null', 'ploam')
        if output:
            match = re.search(r'curr_state\s*=\s*(\d+)', output)
            if match:
                state_map = {'5': 'O5 (Operation)', '1': 'O1 (Initial)', '2': 'O2', '3': 'O3', '4': 'O4'}
                info['onu_state'] = state_map.get(match.group(1), f"O{match.group(1)}")

    return info


def fetch_data():
    """Fetch all data from WAS-110"""
    global current_data

    logger.debug("Fetching data from WAS-110...")

    try:
        temps = parse_temperatures()
        optical = parse_optical_stats()
        system = parse_system_info()

        try:
            tz = pytz.timezone(Config.TIMEZONE)
        except Exception:
            tz = pytz.UTC

        now = datetime.now(tz)

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

        data = {key: list(values) for key, values in history.items()}

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


@app.route('/settings')
def settings_page():
    """Serve settings page"""
    return send_from_directory('static', 'settings.html')


@app.route('/manifest.json')
def manifest():
    """Serve PWA manifest"""
    return send_from_directory('static', 'manifest.json')


@app.route('/sw.js')
def service_worker():
    """Serve service worker"""
    return send_from_directory('static', 'sw.js')


@app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory('static', path)


@app.route('/api/data')
def get_data():
    """Get current data and history"""
    return jsonify({
        'current': current_data,
        'history': {key: list(values) for key, values in history.items()},
        'config': {
            'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
            'history_hours': Config.HISTORY_HOURS,
            'thresholds': Config.get_thresholds()
        },
        'next_refresh': Config.FETCH_INTERVAL_SECONDS,
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
            'notifications': Config.get_notifications()
        }
    })


@app.route('/api/alerts')
def get_alerts():
    """Get alert history"""
    return jsonify({
        'current': notification_manager.get_current_status(),
        'history': notification_manager.get_alert_history()
    })


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings"""
    return jsonify({
        'thresholds': Config.get_thresholds(),
        'notifications': Config.get_notifications(),
        'connection': {
            'sfp_host': Config.SFP_HOST,
            'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
            'history_hours': Config.HISTORY_HOURS
        }
    })


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update settings"""
    try:
        data = request.get_json()
        Config.update_settings(data)
        return jsonify({'success': True, 'settings': Config.get_all_settings()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/settings/thresholds', methods=['POST'])
def update_thresholds():
    """Update threshold settings"""
    try:
        data = request.get_json()
        for key, value in data.items():
            Config.set(key, float(value))
        return jsonify({'success': True, 'thresholds': Config.get_thresholds()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/settings/notifications', methods=['POST'])
def update_notifications():
    """Update notification settings"""
    try:
        data = request.get_json()
        Config.update_settings(data)
        return jsonify({'success': True, 'notifications': Config.get_notifications()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/notifications/test', methods=['POST'])
def test_notifications():
    """Send test notification"""
    try:
        results = notification_manager.send_test_notification()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/debug')
def get_debug():
    """Get debug information including raw command outputs"""
    return jsonify({
        'current_data': current_data,
        'connection_stats': connection_stats,
        'raw_outputs': debug_outputs,
        'settings': Config.get_all_settings()
    })


@app.route('/api/export')
def export_data():
    """Export history data as JSON or CSV"""
    format_type = request.args.get('format', 'json')
    hours = int(request.args.get('hours', Config.HISTORY_HOURS))

    try:
        tz = pytz.timezone(Config.TIMEZONE)
    except Exception:
        tz = pytz.UTC

    cutoff = datetime.now(tz) - timedelta(hours=hours)

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
    load_history()
    fetch_data()

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
