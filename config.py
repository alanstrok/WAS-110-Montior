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
    HISTORY_HOURS = int(os.getenv('HISTORY_HOURS', '168'))  # 7 days
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
        """Get alert thresholds - defaults based on WAS-110/PRX126 specs with 5% margin"""
        return {
            # Temperature thresholds (HIGH - alert when above)
            'temp1_warning': cls._settings.get('temp1_warning', float(os.getenv('TEMP_WARNING', '66.5'))),
            'temp1_critical': cls._settings.get('temp1_critical', float(os.getenv('TEMP_CRITICAL', '76'))),
            'temp2_warning': cls._settings.get('temp2_warning', float(os.getenv('TEMP_WARNING', '66.5'))),
            'temp2_critical': cls._settings.get('temp2_critical', float(os.getenv('TEMP_CRITICAL', '76'))),
            'optical_temp_warning': cls._settings.get('optical_temp_warning', float(os.getenv('OPTICAL_TEMP_WARNING', '52'))),
            'optical_temp_critical': cls._settings.get('optical_temp_critical', float(os.getenv('OPTICAL_TEMP_CRITICAL', '62'))),
            # Power thresholds (LOW - alert when below)
            'rx_power_warning': cls._settings.get('rx_power_warning', float(os.getenv('RX_POWER_WARNING', '-24.7'))),
            'rx_power_critical': cls._settings.get('rx_power_critical', float(os.getenv('RX_POWER_CRITICAL', '-26.6'))),
            'tx_power_warning': cls._settings.get('tx_power_warning', float(os.getenv('TX_POWER_WARNING', '4.3'))),
            'tx_power_critical': cls._settings.get('tx_power_critical', float(os.getenv('TX_POWER_CRITICAL', '3.8'))),
            # Voltage LOW thresholds (alert when below)
            'voltage_low_warning': cls._settings.get('voltage_low_warning', 2.95),
            'voltage_low_critical': cls._settings.get('voltage_low_critical', 2.85),
            # Voltage HIGH thresholds (alert when above)
            'voltage_high_warning': cls._settings.get('voltage_high_warning', 3.45),
            'voltage_high_critical': cls._settings.get('voltage_high_critical', 3.6),
            # Bias current thresholds (HIGH - alert when above)
            'bias_current_warning': cls._settings.get('bias_current_warning', 57),
            'bias_current_critical': cls._settings.get('bias_current_critical', 76),
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
            'discord': {
                'enabled': cls._settings.get('discord_enabled', False),
                'webhook_url': cls._settings.get('discord_webhook_url', os.getenv('DISCORD_WEBHOOK_URL', '')),
                'username': cls._settings.get('discord_username', 'WAS-110 Monitor'),
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
