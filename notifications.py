"""
WAS-110 Monitor - Notification System
"""
import logging
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional
import requests

from config import Config

logger = logging.getLogger(__name__)


class AlertLevel:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    RECOVERY = "recovery"


class NotificationManager:
    def __init__(self):
        self.last_alerts: Dict[str, str] = {}  # metric -> last alert level
        self.alert_history: List[Dict] = []
        self.cooldown_minutes = 15
        self.last_notification_time: Dict[str, datetime] = {}

    def check_thresholds(self, data: Dict) -> List[Dict]:
        """Check all metrics against thresholds and return alerts"""
        alerts = []

        # CPU Temperatures
        for key in ['temp1', 'temp2']:
            if key in data and data[key] is not None:
                temp = data[key]
                alert = self._check_metric(
                    key, temp,
                    Config.TEMP_WARNING,
                    Config.TEMP_CRITICAL,
                    f"CPU Temperature ({key})"
                )
                if alert:
                    alerts.append(alert)

        # Optical Temperature
        if 'optical_temp' in data and data['optical_temp'] is not None:
            alert = self._check_metric(
                'optical_temp', data['optical_temp'],
                Config.OPTICAL_TEMP_WARNING,
                Config.OPTICAL_TEMP_CRITICAL,
                "Optical Temperature"
            )
            if alert:
                alerts.append(alert)

        # RX Power
        if 'rx_power' in data and data['rx_power'] is not None:
            rx = data['rx_power']
            if rx < Config.RX_POWER_CRITICAL:
                alert = self._create_alert('rx_power', rx, AlertLevel.CRITICAL,
                    "RX Power", f"{rx:.2f} dBm (critical < {Config.RX_POWER_CRITICAL})")
                if alert:
                    alerts.append(alert)
            elif rx < Config.RX_POWER_WARNING:
                alert = self._create_alert('rx_power', rx, AlertLevel.WARNING,
                    "RX Power", f"{rx:.2f} dBm (warning < {Config.RX_POWER_WARNING})")
                if alert:
                    alerts.append(alert)
            elif self.last_alerts.get('rx_power') in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
                alerts.append(self._create_recovery('rx_power', rx, "RX Power"))

        # TX Power
        if 'tx_power' in data and data['tx_power'] is not None:
            tx = data['tx_power']
            if tx < Config.TX_POWER_CRITICAL:
                alert = self._create_alert('tx_power', tx, AlertLevel.CRITICAL,
                    "TX Power", f"{tx:.2f} dBm (critical < {Config.TX_POWER_CRITICAL})")
                if alert:
                    alerts.append(alert)
            elif tx < Config.TX_POWER_WARNING:
                alert = self._create_alert('tx_power', tx, AlertLevel.WARNING,
                    "TX Power", f"{tx:.2f} dBm (warning < {Config.TX_POWER_WARNING})")
                if alert:
                    alerts.append(alert)
            elif self.last_alerts.get('tx_power') in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
                alerts.append(self._create_recovery('tx_power', tx, "TX Power"))

        return alerts

    def _check_metric(self, key: str, value: float, warning: float,
                      critical: float, name: str) -> Optional[Dict]:
        """Check a metric against warning/critical thresholds"""
        if value >= critical:
            return self._create_alert(key, value, AlertLevel.CRITICAL, name,
                f"{value:.1f}°C (critical >= {critical}°C)")
        elif value >= warning:
            return self._create_alert(key, value, AlertLevel.WARNING, name,
                f"{value:.1f}°C (warning >= {warning}°C)")
        elif self.last_alerts.get(key) in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
            return self._create_recovery(key, value, name)
        return None

    def _create_alert(self, key: str, value: float, level: str,
                      name: str, message: str) -> Optional[Dict]:
        """Create an alert if conditions are met"""
        # Check if alert level changed or cooldown passed
        if self.last_alerts.get(key) == level:
            last_time = self.last_notification_time.get(key)
            if last_time:
                elapsed = (datetime.now() - last_time).total_seconds() / 60
                if elapsed < self.cooldown_minutes:
                    return None

        self.last_alerts[key] = level
        self.last_notification_time[key] = datetime.now()

        alert = {
            'key': key,
            'name': name,
            'value': value,
            'level': level,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        self.alert_history.append(alert)

        # Keep only last 100 alerts
        if len(self.alert_history) > 100:
            self.alert_history = self.alert_history[-100:]

        return alert

    def _create_recovery(self, key: str, value: float, name: str) -> Dict:
        """Create a recovery notification"""
        self.last_alerts[key] = AlertLevel.RECOVERY
        self.last_notification_time[key] = datetime.now()

        alert = {
            'key': key,
            'name': name,
            'value': value,
            'level': AlertLevel.RECOVERY,
            'message': f"{name} returned to normal: {value:.2f}",
            'timestamp': datetime.now().isoformat()
        }
        self.alert_history.append(alert)
        return alert

    def send_notifications(self, alerts: List[Dict]):
        """Send notifications through all configured channels"""
        if not Config.NOTIFICATIONS_ENABLED or not alerts:
            return

        for alert in alerts:
            self._send_email(alert)
            self._send_webhook(alert)
            self._send_discord(alert)
            self._send_ntfy(alert)

    def _send_email(self, alert: Dict):
        """Send email notification"""
        if not Config.SMTP_HOST or not Config.SMTP_TO:
            return

        try:
            msg = MIMEMultipart()
            level_emoji = {"critical": "🔴", "warning": "🟠", "recovery": "🟢", "info": "🔵"}
            emoji = level_emoji.get(alert['level'], "ℹ️")

            msg['Subject'] = f"{emoji} WAS-110 Alert: {alert['name']} - {alert['level'].upper()}"
            msg['From'] = Config.SMTP_FROM
            msg['To'] = Config.SMTP_TO

            body = f"""
WAS-110 Monitoring Alert

Metric: {alert['name']}
Level: {alert['level'].upper()}
Value: {alert['value']}
Message: {alert['message']}
Time: {alert['timestamp']}
            """
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                if Config.SMTP_TLS:
                    server.starttls()
                if Config.SMTP_USER and Config.SMTP_PASSWORD:
                    server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info(f"Email sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    def _send_webhook(self, alert: Dict):
        """Send generic webhook notification"""
        if not Config.WEBHOOK_ENABLED or not Config.WEBHOOK_URL:
            return

        try:
            payload = {
                'source': 'WAS-110 Monitor',
                'alert': alert
            }
            response = requests.post(Config.WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Webhook sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")

    def _send_discord(self, alert: Dict):
        """Send Discord webhook notification"""
        if not Config.DISCORD_WEBHOOK_URL:
            return

        try:
            colors = {"critical": 15158332, "warning": 15105570, "recovery": 3066993, "info": 3447003}

            embed = {
                "title": f"WAS-110 Alert: {alert['name']}",
                "description": alert['message'],
                "color": colors.get(alert['level'], 3447003),
                "fields": [
                    {"name": "Level", "value": alert['level'].upper(), "inline": True},
                    {"name": "Value", "value": str(alert['value']), "inline": True},
                ],
                "timestamp": alert['timestamp']
            }

            payload = {"embeds": [embed]}
            response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Discord notification sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")

    def _send_ntfy(self, alert: Dict):
        """Send ntfy.sh notification"""
        if not Config.NTFY_URL or not Config.NTFY_TOPIC:
            return

        try:
            priority_map = {"critical": "urgent", "warning": "high", "recovery": "default", "info": "low"}

            headers = {
                "Title": f"WAS-110: {alert['name']}",
                "Priority": priority_map.get(alert['level'], "default"),
                "Tags": f"was110,{alert['level']}"
            }

            url = f"{Config.NTFY_URL.rstrip('/')}/{Config.NTFY_TOPIC}"
            response = requests.post(url, data=alert['message'], headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"Ntfy notification sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send ntfy notification: {e}")

    def get_alert_history(self) -> List[Dict]:
        """Return alert history"""
        return self.alert_history.copy()

    def get_current_status(self) -> Dict:
        """Return current alert status for all metrics"""
        return self.last_alerts.copy()


# Global instance
notification_manager = NotificationManager()
