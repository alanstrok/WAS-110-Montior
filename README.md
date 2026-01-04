# WAS-110 SFP+ ONT Monitor

A modern, real-time monitoring webapp for WAS-110 SFP+ ONT modules with alerting and notifications.

![Dashboard Preview](docs/dashboard.png)

## Features

- **Real-time Monitoring**: Live dashboard with WebSocket updates
- **Temperature Tracking**: CPU and optical module temperatures
- **Optical Metrics**: TX/RX power, bias current, supply voltage
- **System Info**: Uptime, firmware version, PON status, ONU state
- **Historical Data**: Up to 72 hours of history with interactive charts
- **Alerting System**: Configurable thresholds with warning/critical levels
- **Multiple Notification Channels**:
  - Email (SMTP)
  - Discord webhooks
  - Generic webhooks
  - Ntfy push notifications
- **Dark/Light Theme**: User preference with auto-save
- **Data Export**: Export history as JSON or CSV
- **Docker Ready**: Easy deployment with Docker Compose

## Quick Start

### Using Docker Compose (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/yourusername/WAS-110-Monitor.git
cd WAS-110-Monitor
```

2. Create environment file:
```bash
cp .env.example .env
```

3. Edit `.env` with your WAS-110 credentials:
```env
SFP_HOST=192.168.11.1
SFP_USER=root
SFP_ROOT_PASSWORD=your_password
```

4. Start the container:
```bash
docker-compose up -d
```

5. Access the dashboard at `http://localhost:5050`

### Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export SFP_ROOT_PASSWORD="your_password"
```

3. Run the application:
```bash
python app.py
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SFP_HOST` | `192.168.11.1` | WAS-110 IP address |
| `SFP_USER` | `root` | SSH username |
| `SFP_ROOT_PASSWORD` | - | SSH password (required) |
| `FETCH_INTERVAL_SECONDS` | `60` | Data collection interval |
| `HISTORY_HOURS` | `72` | Hours of history to keep |
| `TEMP_WARNING` | `65` | CPU temp warning threshold (°C) |
| `TEMP_CRITICAL` | `75` | CPU temp critical threshold (°C) |
| `OPTICAL_TEMP_WARNING` | `55` | Optical temp warning (°C) |
| `OPTICAL_TEMP_CRITICAL` | `65` | Optical temp critical (°C) |
| `RX_POWER_WARNING` | `-25` | RX power warning (dBm) |
| `RX_POWER_CRITICAL` | `-28` | RX power critical (dBm) |
| `NOTIFICATIONS_ENABLED` | `false` | Enable notifications |

### Notifications

#### Email (SMTP)
```env
NOTIFICATIONS_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com
SMTP_TO=alerts@example.com
```

#### Discord
```env
NOTIFICATIONS_ENABLED=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

#### Ntfy
```env
NOTIFICATIONS_ENABLED=true
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=was110-alerts
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Current data and history |
| `/api/status` | GET | Connection status |
| `/api/alerts` | GET | Alert history |
| `/api/config` | GET | Current configuration |
| `/api/export` | GET | Export data (JSON/CSV) |
| `/api/refresh` | POST | Force data refresh |

### Export Examples

```bash
# Export last 24h as JSON
curl "http://localhost:5050/api/export?format=json&hours=24"

# Export last 6h as CSV
curl "http://localhost:5050/api/export?format=csv&hours=6" > data.csv
```

## Architecture

```
┌─────────────────┐     SSH      ┌─────────────┐
│   WAS-110 ONT   │◄────────────►│   Monitor   │
│  192.168.11.1   │              │   Backend   │
└─────────────────┘              └──────┬──────┘
                                        │
                                        │ WebSocket/REST
                                        │
                                 ┌──────▼──────┐
                                 │  Dashboard  │
                                 │  (Browser)  │
                                 └─────────────┘
```

## Metrics Collected

| Metric | Source | Unit |
|--------|--------|------|
| CPU 0 Temperature | `/sys/class/thermal/thermal_zone0/temp` | °C |
| CPU 1 Temperature | `/sys/class/thermal/thermal_zone1/temp` | °C |
| Optical Temperature | SFP EEPROM (A2, offset 96) | °C |
| Supply Voltage | `pontop -b -g 'Optical Interface Status'` | V |
| Bias Current | `pontop -b -g 'Optical Interface Status'` | mA |
| TX Power | `pontop -b -g 'Optical Interface Status'` | dBm |
| RX Power | `pontop -b -g 'Optical Interface Status'` | dBm |
| PON Mode | `pontop -b -g 'PON Status'` | - |
| ONU State | `pontop -b -g 'PON Status'` | - |

## Troubleshooting

### Connection Issues

1. Verify the WAS-110 is accessible:
```bash
ping 192.168.11.1
```

2. Test SSH connection:
```bash
ssh root@192.168.11.1
```

3. Check container logs:
```bash
docker-compose logs -f
```

### High Temperatures

WAS-110 modules are known to run hot. If temperatures consistently exceed 70°C:
- Ensure adequate ventilation
- Consider adding a heatsink
- Check ambient temperature

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

MIT License - see LICENSE file for details.

## Credits

Inspired by [mahmoudhamadeh/was-110-monitoring](https://github.com/mahmoudhamadeh/was-110-monitoring)
