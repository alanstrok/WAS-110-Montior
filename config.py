"""
WAS-110 Monitor - Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # WAS-110 Connection
    SFP_HOST = os.getenv('SFP_HOST', '192.168.11.1')
    SFP_USER = os.getenv('SFP_USER', 'root')
    SFP_ROOT_PASSWORD = os.getenv('SFP_ROOT_PASSWORD', '')

    # Data Collection
    FETCH_INTERVAL_SECONDS = int(os.getenv('FETCH_INTERVAL_SECONDS', '60'))
    HISTORY_HOURS = int(os.getenv('HISTORY_HOURS', '72'))  # 3 days by default
    DATA_DIR = os.getenv('DATA_DIR', '/data')

    # Alert Thresholds
    TEMP_WARNING = float(os.getenv('TEMP_WARNING', '65'))
    TEMP_CRITICAL = float(os.getenv('TEMP_CRITICAL', '75'))
    OPTICAL_TEMP_WARNING = float(os.getenv('OPTICAL_TEMP_WARNING', '55'))
    OPTICAL_TEMP_CRITICAL = float(os.getenv('OPTICAL_TEMP_CRITICAL', '65'))
    RX_POWER_WARNING = float(os.getenv('RX_POWER_WARNING', '-25'))
    RX_POWER_CRITICAL = float(os.getenv('RX_POWER_CRITICAL', '-28'))
    TX_POWER_WARNING = float(os.getenv('TX_POWER_WARNING', '-1'))
    TX_POWER_CRITICAL = float(os.getenv('TX_POWER_CRITICAL', '-3'))

    # Notifications
    NOTIFICATIONS_ENABLED = os.getenv('NOTIFICATIONS_ENABLED', 'false').lower() == 'true'

    # Email
    SMTP_HOST = os.getenv('SMTP_HOST', '')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_FROM = os.getenv('SMTP_FROM', '')
    SMTP_TO = os.getenv('SMTP_TO', '')
    SMTP_TLS = os.getenv('SMTP_TLS', 'true').lower() == 'true'

    # Webhook
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'false').lower() == 'true'

    # Discord
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

    # Ntfy
    NTFY_URL = os.getenv('NTFY_URL', '')
    NTFY_TOPIC = os.getenv('NTFY_TOPIC', '')

    # Web Server
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    PORT = int(os.getenv('PORT', '5050'))

    @classmethod
    def get_history_max_points(cls):
        """Calculate max data points based on history hours and fetch interval"""
        return (cls.HISTORY_HOURS * 3600) // cls.FETCH_INTERVAL_SECONDS
