"""
WAS-110 Monitor - Notification System
Supports Gotify, Ntfy, Webhook, and Email
"""
import logging
import smtplib
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
        self.last_alerts: Dict[str, str] = {}
        self.alert_history: List[Dict] = []
        self.cooldown_minutes = 15
        self.last_notification_time: Dict[str, datetime] = {}

    def check_thresholds(self, data: Dict) -> List[Dict]:
        """Check all metrics against thresholds and return alerts"""
        alerts = []
        thresholds = Config.get_thresholds()

        # CPU Temperature 1
        if data.get('temp1') is not None:
            alert = self._check_metric(
                'temp1', data['temp1'],
                thresholds['temp1_warning'],
                thresholds['temp1_critical'],
                "CPU 0 Temperature"
            )
            if alert:
                alerts.append(alert)

        # CPU Temperature 2
        if data.get('temp2') is not None:
            alert = self._check_metric(
                'temp2', data['temp2'],
                thresholds['temp2_warning'],
                thresholds['temp2_critical'],
                "CPU 1 Temperature"
            )
            if alert:
                alerts.append(alert)

        # Optical Temperature
        if data.get('optical_temp') is not None:
            alert = self._check_metric(
                'optical_temp', data['optical_temp'],
                thresholds['optical_temp_warning'],
                thresholds['optical_temp_critical'],
                "Optical Temperature"
            )
            if alert:
                alerts.append(alert)

        # Voltage (low is bad)
        if data.get('voltage') is not None:
            voltage = data['voltage']
            if voltage < thresholds['voltage_critical']:
                alert = self._create_alert('voltage', voltage, AlertLevel.CRITICAL,
                    "Supply Voltage", f"{voltage:.2f}V (critical < {thresholds['voltage_critical']}V)")
                if alert:
                    alerts.append(alert)
            elif voltage < thresholds['voltage_warning']:
                alert = self._create_alert('voltage', voltage, AlertLevel.WARNING,
                    "Supply Voltage", f"{voltage:.2f}V (warning < {thresholds['voltage_warning']}V)")
                if alert:
                    alerts.append(alert)
            elif self.last_alerts.get('voltage') in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
                alerts.append(self._create_recovery('voltage', voltage, "Supply Voltage"))

        # RX Power (low is bad)
        if data.get('rx_power') is not None:
            rx = data['rx_power']
            if rx < thresholds['rx_power_critical']:
                alert = self._create_alert('rx_power', rx, AlertLevel.CRITICAL,
                    "RX Power", f"{rx:.2f} dBm (critical < {thresholds['rx_power_critical']})")
                if alert:
                    alerts.append(alert)
            elif rx < thresholds['rx_power_warning']:
                alert = self._create_alert('rx_power', rx, AlertLevel.WARNING,
                    "RX Power", f"{rx:.2f} dBm (warning < {thresholds['rx_power_warning']})")
                if alert:
                    alerts.append(alert)
            elif self.last_alerts.get('rx_power') in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
                alerts.append(self._create_recovery('rx_power', rx, "RX Power"))

        # TX Power (low is bad)
        if data.get('tx_power') is not None:
            tx = data['tx_power']
            if tx < thresholds['tx_power_critical']:
                alert = self._create_alert('tx_power', tx, AlertLevel.CRITICAL,
                    "TX Power", f"{tx:.2f} dBm (critical < {thresholds['tx_power_critical']})")
                if alert:
                    alerts.append(alert)
            elif tx < thresholds['tx_power_warning']:
                alert = self._create_alert('tx_power', tx, AlertLevel.WARNING,
                    "TX Power", f"{tx:.2f} dBm (warning < {thresholds['tx_power_warning']})")
                if alert:
                    alerts.append(alert)
            elif self.last_alerts.get('tx_power') in [AlertLevel.WARNING, AlertLevel.CRITICAL]:
                alerts.append(self._create_recovery('tx_power', tx, "TX Power"))

        return alerts

    def _check_metric(self, key: str, value: float, warning: float,
                      critical: float, name: str) -> Optional[Dict]:
        """Check a metric against warning/critical thresholds (high is bad)"""
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
        notif_config = Config.get_notifications()

        if not notif_config['enabled'] or not alerts:
            return

        for alert in alerts:
            if notif_config['gotify']['enabled']:
                self._send_gotify(alert, notif_config['gotify'])
            if notif_config['ntfy']['enabled']:
                self._send_ntfy(alert, notif_config['ntfy'])
            if notif_config['webhook']['enabled']:
                self._send_webhook(alert, notif_config['webhook'])
            if notif_config['email']['enabled']:
                self._send_email(alert, notif_config['email'])

    def _send_gotify(self, alert: Dict, config: Dict):
        """Send Gotify notification"""
        if not config.get('url') or not config.get('token'):
            return

        try:
            priority_map = {"critical": 10, "warning": 8, "recovery": 5, "info": 4}
            priority = priority_map.get(alert['level'], config.get('priority', 8))

            url = f"{config['url'].rstrip('/')}/message?token={config['token']}"

            payload = {
                "title": f"WAS-110: {alert['name']} [{alert['level'].upper()}]",
                "message": alert['message'],
                "priority": priority,
                "extras": {
                    "client::display": {
                        "contentType": "text/plain"
                    }
                }
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Gotify notification sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send Gotify notification: {e}")

    def _send_ntfy(self, alert: Dict, config: Dict):
        """Send ntfy.sh notification"""
        if not config.get('url') or not config.get('topic'):
            return

        try:
            priority_map = {"critical": "urgent", "warning": "high", "recovery": "default", "info": "low"}

            headers = {
                "Title": f"WAS-110: {alert['name']}",
                "Priority": priority_map.get(alert['level'], "default"),
                "Tags": f"was110,{alert['level']}"
            }

            url = f"{config['url'].rstrip('/')}/{config['topic']}"
            response = requests.post(url, data=alert['message'], headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"Ntfy notification sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send ntfy notification: {e}")

    def _send_webhook(self, alert: Dict, config: Dict):
        """Send generic webhook notification"""
        if not config.get('url'):
            return

        try:
            payload = {
                'source': 'WAS-110 Monitor',
                'alert': alert
            }
            response = requests.post(config['url'], json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Webhook sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")

    def _send_email(self, alert: Dict, config: Dict):
        """Send email notification"""
        if not config.get('smtp_host') or not config.get('smtp_to'):
            return

        try:
            msg = MIMEMultipart()
            level_emoji = {"critical": "🔴", "warning": "🟠", "recovery": "🟢", "info": "🔵"}
            emoji = level_emoji.get(alert['level'], "ℹ️")

            msg['Subject'] = f"{emoji} WAS-110 Alert: {alert['name']} - {alert['level'].upper()}"
            msg['From'] = config.get('smtp_from', config['smtp_user'])
            msg['To'] = config['smtp_to']

            body = f"""
WAS-110 Monitoring Alert

Metric: {alert['name']}
Level: {alert['level'].upper()}
Value: {alert['value']}
Message: {alert['message']}
Time: {alert['timestamp']}
            """
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(config['smtp_host'], config.get('smtp_port', 587)) as server:
                if config.get('smtp_tls', True):
                    server.starttls()
                if config.get('smtp_user') and config.get('smtp_password'):
                    server.login(config['smtp_user'], config['smtp_password'])
                server.send_message(msg)

            logger.info(f"Email sent for {alert['name']} alert")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    def send_test_notification(self) -> Dict:
        """Send a test notification to all configured channels"""
        test_alert = {
            'key': 'test',
            'name': 'Test Notification',
            'value': 0,
            'level': AlertLevel.INFO,
            'message': 'This is a test notification from WAS-110 Monitor',
            'timestamp': datetime.now().isoformat()
        }

        results = {'success': [], 'failed': []}
        notif_config = Config.get_notifications()

        if notif_config['gotify']['enabled']:
            try:
                self._send_gotify(test_alert, notif_config['gotify'])
                results['success'].append('gotify')
            except Exception as e:
                results['failed'].append({'channel': 'gotify', 'error': str(e)})

        if notif_config['ntfy']['enabled']:
            try:
                self._send_ntfy(test_alert, notif_config['ntfy'])
                results['success'].append('ntfy')
            except Exception as e:
                results['failed'].append({'channel': 'ntfy', 'error': str(e)})

        if notif_config['webhook']['enabled']:
            try:
                self._send_webhook(test_alert, notif_config['webhook'])
                results['success'].append('webhook')
            except Exception as e:
                results['failed'].append({'channel': 'webhook', 'error': str(e)})

        if notif_config['email']['enabled']:
            try:
                self._send_email(test_alert, notif_config['email'])
                results['success'].append('email')
            except Exception as e:
                results['failed'].append({'channel': 'email', 'error': str(e)})

        return results

    def get_alert_history(self) -> List[Dict]:
        """Return alert history"""
        return self.alert_history.copy()

    def get_current_status(self) -> Dict:
        """Return current alert status for all metrics"""
        return self.last_alerts.copy()


# Global instance
notification_manager = NotificationManager()
