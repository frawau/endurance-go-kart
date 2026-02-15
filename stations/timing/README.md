# Timing Station

Transponder timing station that connects to timing hardware (TAG Heuer/Chronelec decoders) and relays crossing events to the Django race management application via WebSocket.

## Supported Hardware

- **NetTag** - Chronelec decoder over network (UDP/TCP)
- **TAG** - TAG Heuer decoder via serial port
- **Simulator** - Virtual transponders for testing

## Configuration

The timing station supports configuration via TOML files.

### Usage

```bash
# Use config file
python timing-station.py -c timing-station.toml

# Use default config file (timing-station.toml in current directory)
python timing-station.py
```

### Configuration File Format

```toml
[daemon]
# WebSocket connection to Django app
websocket_url = "ws://your-server.com:8000/ws/timing/"
hmac_secret = "your-hmac-secret"
reconnect_interval = 5.0  # seconds

[plugin]
# Plugin type: "nettag", "tag", "simulator"
type = "nettag"

# NetTag plugin configuration (Chronelec decoder over UDP/TCP)
[plugin.nettag]
host = "192.168.0.11"    # Decoder IP address
port = 2009              # Decoder port
protocol = "udp"         # "udp" or "tcp"

# TAG Heuer serial plugin configuration
[plugin.tag]
device = "/dev/ttyUSB0"
baud = 9600
parity = "N"
stopbits = 1
endian = "normal"  # or "bitrev" for bit-reversed serial

# Simulator plugin configuration (for testing)
[plugin.simulator]
num_transponders = 10
lap_time_min = 45.0
lap_time_max = 75.0
lap_time_variance = 5.0

[logging]
level = "INFO"  # DEBUG, INFO, WARNING, ERROR
file = "timing-station.log"
```

## Plugin Details

### NetTag Plugin

For Chronelec decoders that output TAG Heuer format frames over the network:
- Frame format: `<STA 023066 80:27'53"016 01 01 01 3 1569>`
- Supports both UDP and TCP protocols
- Sends ACK bytes back to decoder

### TAG Plugin

For TAG Heuer decoders connected via serial port:
- Same frame format as NetTag
- Supports bit-reversal for certain decoder configurations
- Requires `pyserial-asyncio` package

### Simulator Plugin

For testing without hardware:
- Generates realistic crossing events
- Configurable number of transponders and lap times
- 10x time acceleration for faster testing

## WebSocket Protocol

The station communicates with Django using HMAC-signed JSON messages. The station is intentionally "dumb" - it only sends raw transponder data. Django handles all race/team/kart lookups using `RaceTransponderAssignment`.

### Outgoing Messages (Station -> Django)

**Connection established:**
```json
{
  "type": "connected",
  "plugin_type": "nettag",
  "timestamp": "2024-01-15T14:30:00.000000"
}
```

**Lap crossing (raw transponder data):**
```json
{
  "type": "lap_crossing",
  "transponder_id": "023066",
  "timestamp": "2024-01-15T14:30:45.123456",
  "raw_time": 2745.123,
  "signal_strength": 0
}
```

### Incoming Commands (Django -> Station)

**Get status:**
```json
{
  "type": "command",
  "command": "get_status"
}
```

### Response Messages (Station -> Django)

**Status response:**
```json
{
  "type": "response",
  "response": "status",
  "status": {
    "plugin_type": "NetTag",
    "connected": true,
    "reading": true,
    "host": "192.168.0.11",
    "port": 2009,
    "protocol": "udp"
  }
}
```

## Requirements

```
websockets
toml  # Only needed for Python < 3.11
pyserial-asyncio  # Only for TAG serial plugin
```

## Deployment

### Docker (co-located with Django app)

The timing station can run as an optional Docker service alongside the main application. This is useful when timing hardware is connected to the same server, or for testing with the simulator plugin.

```bash
# Enable the timing station (uncomments defaults in .env)
./race-manager enable-timing

# Configure plugin and settings in .env, then start
./race-manager restart

# View logs
docker compose --profile timing logs -f timing-station

# Disable
./race-manager disable-timing
./race-manager restart
```

The Docker entrypoint (`run-timing.sh`) generates `timing-station.toml` from `TIMING_*` environment variables at container startup. The WebSocket URL defaults to `ws://appseed_app:5005/ws/timing/` (Docker internal network). Crossing buffer data is persisted in the `timing_buffer` Docker volume.

For development, `docker-compose.dev.yml` mounts the local `stations/timing/` directory into the container for live code changes.

### Systemd (standalone deployment)

For running on a separate machine (e.g., trackside Raspberry Pi):

```bash
# Install dependencies
pip install websockets toml
pip install pyserial-asyncio  # Only for TAG serial plugin

# Edit timing-station.toml with your settings
python timing-station.py -c timing-station.toml
```

A systemd service template is provided at `timing-station.service.template`. To install:

```bash
sudo cp timing-station.service.template /etc/systemd/system/timing-station.service
# Edit the file: replace __USER__, __GROUP__, __WORKDIR__ with actual values
sudo systemctl enable --now timing-station
```
