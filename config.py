"""
WAS-110 Monitor - Configuration
Supports both environment variables and persistent settings file
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

SETTINGS_FILE = os.path.join(os.getenv('DATA_DIR', '/data'), 'settings.json')


def load_settings():
    """Load settings from JSON file"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(settings):
    """Save settings to JSON file"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False


class Config:
    _settings = load_settings()

    # WAS-110 Connection (HTTP API)
    SFP_HOST = os.getenv('SFP_HOST', '192.168.11.1')

    # Data Collection
    FETCH_INTERVAL_SECONDS = int(os.getenv('FETCH_INTERVAL_SECONDS', '60'))
    HISTORY_HOURS = int(os.getenv('HISTORY_HOURS', '72'))
    DATA_DIR = os.getenv('DATA_DIR', '/data')

    # Web Server
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    PORT = int(os.getenv('PORT', '5050'))
    TIMEZONE = os.getenv('TZ', os.getenv('TIMEZONE', 'UTC'))

    @classmethod
    def get(cls, key, default=None):
        """Get setting from persistent storage or default"""
        return cls._settings.get(key, default)

    @classmethod
    def set(cls, key, value):
        """Set setting in persistent storage"""
        cls._settings[key] = value
        save_settings(cls._settings)

    @classmethod
    def get_all_settings(cls):
        """Get all settings"""
        return cls._settings.copy()

    @classmethod
    def update_settings(cls, new_settings):
        """Update multiple settings"""
        cls._settings.update(new_settings)
        save_settings(cls._settings)

    @classmethod
    def get_thresholds(cls):
        """Get alert thresholds"""
        return {
            'temp1_warning': cls._settings.get('temp1_warning', float(os.getenv('TEMP_WARNING', '65'))),
            'temp1_critical': cls._settings.get('temp1_critical', float(os.getenv('TEMP_CRITICAL', '75'))),
            'temp2_warning': cls._settings.get('temp2_warning', float(os.getenv('TEMP_WARNING', '65'))),
            'temp2_critical': cls._settings.get('temp2_critical', float(os.getenv('TEMP_CRITICAL', '75'))),
            'optical_temp_warning': cls._settings.get('optical_temp_warning', float(os.getenv('OPTICAL_TEMP_WARNING', '55'))),
            'optical_temp_critical': cls._settings.get('optical_temp_critical', float(os.getenv('OPTICAL_TEMP_CRITICAL', '65'))),
            'rx_power_warning': cls._settings.get('rx_power_warning', float(os.getenv('RX_POWER_WARNING', '-25'))),
            'rx_power_critical': cls._settings.get('rx_power_critical', float(os.getenv('RX_POWER_CRITICAL', '-28'))),
            'tx_power_warning': cls._settings.get('tx_power_warning', float(os.getenv('TX_POWER_WARNING', '-1'))),
            'tx_power_critical': cls._settings.get('tx_power_critical', float(os.getenv('TX_POWER_CRITICAL', '-3'))),
            'voltage_warning': cls._settings.get('voltage_warning', 3.1),
            'voltage_critical': cls._settings.get('voltage_critical', 3.0),
            'bias_current_warning': cls._settings.get('bias_current_warning', 50),
            'bias_current_critical': cls._settings.get('bias_current_critical', 70),
        }

    @classmethod
    def get_notifications(cls):
        """Get notification settings"""
        return {
            'enabled': cls._settings.get('notifications_enabled', os.getenv('NOTIFICATIONS_ENABLED', 'false').lower() == 'true'),
            'gotify': {
                'enabled': cls._settings.get('gotify_enabled', False),
                'url': cls._settings.get('gotify_url', os.getenv('GOTIFY_URL', '')),
                'token': cls._settings.get('gotify_token', os.getenv('GOTIFY_TOKEN', '')),
                'priority': cls._settings.get('gotify_priority', 8),
            },
            'ntfy': {
                'enabled': cls._settings.get('ntfy_enabled', False),
                'url': cls._settings.get('ntfy_url', os.getenv('NTFY_URL', '')),
                'topic': cls._settings.get('ntfy_topic', os.getenv('NTFY_TOPIC', '')),
            },
            'webhook': {
                'enabled': cls._settings.get('webhook_enabled', False),
                'url': cls._settings.get('webhook_url', os.getenv('WEBHOOK_URL', '')),
            },
            'email': {
                'enabled': cls._settings.get('email_enabled', False),
                'smtp_host': cls._settings.get('smtp_host', os.getenv('SMTP_HOST', '')),
                'smtp_port': cls._settings.get('smtp_port', int(os.getenv('SMTP_PORT', '587'))),
                'smtp_user': cls._settings.get('smtp_user', os.getenv('SMTP_USER', '')),
                'smtp_password': cls._settings.get('smtp_password', os.getenv('SMTP_PASSWORD', '')),
                'smtp_from': cls._settings.get('smtp_from', os.getenv('SMTP_FROM', '')),
                'smtp_to': cls._settings.get('smtp_to', os.getenv('SMTP_TO', '')),
                'smtp_tls': cls._settings.get('smtp_tls', True),
            }
        }

    @classmethod
    def get_history_max_points(cls):
        """Calculate max data points based on history hours and fetch interval"""
        return (cls.HISTORY_HOURS * 3600) // cls.FETCH_INTERVAL_SECONDS
