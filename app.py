"""
WAS-110 Monitor - Main Application
Enhanced monitoring webapp for WAS-110 SFP+ ONT modules
Uses HTTP API for data collection
"""
import os
import json
import logging
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Any

import requests
import urllib3
import pytz
from flask import Flask, jsonify, request, send_from_directory

# Suppress SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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
    'temp1': None,
    'temp2': None,
    'optical_temp': None,
    'voltage': None,
    'bias_current': None,
    'tx_power': None,
    'rx_power': None,
    'pon_mode': None,
    'onu_state': None,
}

connection_stats = {
    'successful_fetches': 0,
    'failed_fetches': 0,
    'last_error': None,
    'uptime_start': datetime.now().isoformat()
}

# Store raw API response for debugging
debug_outputs = {}


def ploam_state_to_string(state: int) -> str:
    """Convert PLOAM state number to readable format"""
    state_map = {
        1: 'O1 (Initial)',
        2: 'O2 (Standby)',
        3: 'O3 (Serial Number)',
        4: 'O4 (Ranging)',
        5: 'O5 (Operation)',
        51: 'O5.1 (Associated)',
        52: 'O5.2 (Associated)',
        6: 'O6 (POPUP)',
        7: 'O7 (Emergency Stop)',
    }
    if state in state_map:
        return state_map[state]
    # Handle O5.x states (51 = O5.1, 52 = O5.2, etc.)
    if 50 < state < 60:
        return f'O5.{state - 50} (Associated)'
    return f'O{state}'


def fetch_metrics() -> Dict[str, Any]:
    """Fetch metrics from WAS-110 HTTP API"""
    try:
        url = f"http://{Config.SFP_HOST}/cgi-bin/luci/8311/metrics"
        logger.debug(f"Fetching metrics from {url}")

        # Disable SSL verification in case of redirect to HTTPS with self-signed cert
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()

        data = response.json()
        debug_outputs['metrics'] = {
            'url': url,
            'response': data,
            'timestamp': datetime.now().isoformat()
        }

        logger.debug(f"Metrics received: {data}")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch metrics: {e}")
        connection_stats['last_error'] = str(e)
        raise


def fetch_data():
    """Fetch all data from WAS-110"""
    global current_data

    logger.debug("Fetching data from WAS-110...")

    try:
        metrics = fetch_metrics()

        try:
            tz = pytz.timezone(Config.TIMEZONE)
        except Exception:
            tz = pytz.UTC

        now = datetime.now(tz)

        # Map API response to our data structure
        current_data.update({
            'connected': True,
            'last_update': now.isoformat(),
            'temp1': metrics.get('cpu1_tempC'),
            'temp2': metrics.get('cpu2_tempC'),
            'optical_temp': metrics.get('optic_tempC'),
            'voltage': metrics.get('module_voltage'),
            'bias_current': metrics.get('tx_bias_mA'),
            'tx_power': metrics.get('tx_power_dBm'),
            'rx_power': metrics.get('rx_power_dBm'),
            'pon_mode': 'XGS-PON',  # WAS-110 is XGS-PON
            'onu_state': ploam_state_to_string(metrics.get('ploam_state', 0)),
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

        logger.debug(f"Data fetch successful: temp1={current_data.get('temp1')}, rx_power={current_data.get('rx_power')}")

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
        points = len(data.get('timestamps', []))

        with open(filepath, 'w') as f:
            json.dump(data, f)

        logger.debug(f"Saved {points} history points to {filepath}")

    except Exception as e:
        logger.error(f"Failed to save history to {Config.DATA_DIR}: {e}")


def load_history():
    """Load history from JSON file"""
    try:
        filepath = os.path.join(Config.DATA_DIR, 'sfp_history.json')
        logger.info(f"Looking for history file at: {filepath}")

        if not os.path.exists(filepath):
            logger.info(f"No history file found at {filepath}, starting fresh")
            return

        with open(filepath, 'r') as f:
            data = json.load(f)

        file_points = len(data.get('timestamps', []))
        logger.info(f"Found {file_points} points in history file")

        for key in history.keys():
            if key in data:
                for value in data[key]:
                    history[key].append(value)

        logger.info(f"Loaded {len(history['timestamps'])} history points into memory")

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
        }
    })


@app.route('/api/status')
def get_status():
    """Get connection status"""
    return jsonify({
        'connected': current_data['connected'],
        'stats': connection_stats
    })


@app.route('/api/alerts')
def get_alerts():
    """Get alert history"""
    return jsonify({
        'current': notification_manager.get_current_status(),
        'history': notification_manager.get_alert_history()
    })


@app.route('/api/alerts/reset', methods=['POST'])
def reset_alerts():
    """Clear all alert history"""
    try:
        notification_manager.clear_alert_history()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/config')
def get_config():
    """Get current configuration"""
    return jsonify({
        'thresholds': Config.get_thresholds(),
        'notifications': Config.get_notifications(),
        'fetch_interval': Config.FETCH_INTERVAL_SECONDS,
        'history_hours': Config.HISTORY_HOURS
    })


@app.route('/api/refresh', methods=['POST'])
def refresh_data():
    """Force a data refresh"""
    fetch_data()
    return jsonify({'success': True, 'data': current_data})


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    """Get or update settings"""
    if request.method == 'GET':
        return jsonify({
            'thresholds': Config.get_thresholds(),
            'notifications': Config.get_notifications()
        })

    try:
        data = request.get_json()
        Config.update_settings(data)
        return jsonify({'success': True, 'settings': Config.get_all_settings()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/thresholds', methods=['POST'])
def update_thresholds():
    """Update alert thresholds"""
    try:
        data = request.get_json()
        # Save flat keys directly, not nested under 'thresholds'
        Config.update_settings(data)
        return jsonify({'success': True, 'thresholds': Config.get_thresholds()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/notifications', methods=['POST'])
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


@app.route('/api/notifications/debug')
def debug_notifications():
    """Get notification configuration for debugging (masks sensitive tokens)"""
    notif_config = Config.get_notifications()

    debug_config = {
        'enabled': notif_config['enabled'],
        'gotify': {
            'enabled': notif_config['gotify']['enabled'],
            'url': notif_config['gotify']['url'],
            'token_set': bool(notif_config['gotify']['token']),
            'token_preview': notif_config['gotify']['token'][:8] + '...' if notif_config['gotify']['token'] and len(notif_config['gotify']['token']) > 8 else '(not set)',
            'priority': notif_config['gotify']['priority'],
        },
        'ntfy': {
            'enabled': notif_config['ntfy']['enabled'],
            'url': notif_config['ntfy']['url'],
            'topic': notif_config['ntfy']['topic'],
        },
        'webhook': {
            'enabled': notif_config['webhook']['enabled'],
            'url_set': bool(notif_config['webhook']['url']),
        },
        'email': {
            'enabled': notif_config['email']['enabled'],
            'smtp_host': notif_config['email']['smtp_host'],
            'smtp_port': notif_config['email']['smtp_port'],
        }
    }
    return jsonify(debug_config)


@app.route('/api/debug')
def get_debug():
    """Get debug information including raw API response"""
    filepath = os.path.join(Config.DATA_DIR, 'sfp_history.json')
    history_file_exists = os.path.exists(filepath)
    history_file_size = os.path.getsize(filepath) if history_file_exists else 0

    return jsonify({
        'current_data': current_data,
        'connection_stats': connection_stats,
        'raw_outputs': debug_outputs,
        'settings': Config.get_all_settings(),
        'retention_config': {
            'history_hours': Config.HISTORY_HOURS,
            'fetch_interval_seconds': Config.FETCH_INTERVAL_SECONDS,
            'max_history_points': MAX_HISTORY_POINTS,
        },
        'history_status': {
            'data_dir': Config.DATA_DIR,
            'file_path': filepath,
            'file_exists': history_file_exists,
            'file_size_bytes': history_file_size,
            'points_in_memory': len(history['timestamps']),
            'oldest_point': history['timestamps'][0] if history['timestamps'] else None,
            'newest_point': history['timestamps'][-1] if history['timestamps'] else None,
        }
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
            continue

    if format_type == 'csv':
        if not filtered_data:
            return "timestamp,temp1,temp2,optical_temp,voltage,bias_current,tx_power,rx_power\n"

        lines = ['timestamp,temp1,temp2,optical_temp,voltage,bias_current,tx_power,rx_power']
        for row in filtered_data:
            lines.append(','.join([
                str(row.get(k, '')) for k in
                ['timestamp', 'temp1', 'temp2', 'optical_temp', 'voltage', 'bias_current', 'tx_power', 'rx_power']
            ]))
        return '\n'.join(lines)

    return jsonify(filtered_data)


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    logger.info("WebSocket client connected")


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info("WebSocket client disconnected")


# Initialize scheduler
scheduler = BackgroundScheduler()


def init_app():
    """Initialize the application"""
    logger.info("Initializing WAS-110 Monitor...")
    logger.info(f"Target device: http://{Config.SFP_HOST}/cgi-bin/luci/8311/metrics")
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


# Initialize on module load (works with gunicorn)
init_app()


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
