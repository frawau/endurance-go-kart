# Stop and Go Station

## Configuration

The stop and go station supports configuration via TOML files. Command line arguments will override configuration file values.

The repository tracks `stopandgo-station.toml.example` as the template;
the runtime file `stopandgo-station.toml` is gitignored so local
changes never block `git pull`. `race-manager configure-stations`
bootstraps the runtime file from the template on first run, then
patches it from `.env`. To configure manually:

```bash
cp stopandgo-station.toml.example stopandgo-station.toml
# edit stopandgo-station.toml as needed
```

## Reliability

The station has three independent watchdogs (configured in the
`[watchdog]` section of `stopandgo-station.toml`):

1. **WebSocket heartbeat** — aiohttp pings the server every
   `ws_heartbeat_seconds`; missing pongs close the WS and trigger
   reconnect.
2. **Disconnect-reboot timer** — if the WS stays down for
   `disconnect_reboot_seconds` (default 5 min), the station calls
   `/sbin/reboot`. Recovers from a wedged network stack.
3. **Hardware watchdog** — opens `/dev/watchdog` and pets it every
   `hw_watchdog_pet_seconds`; if the asyncio loop deadlocks, the
   kernel reboots the Pi after `hw_watchdog_timeout` seconds.

Enable the hardware watchdog on a Raspberry Pi by adding
`dtparam=watchdog=on` to `/boot/firmware/config.txt` (or
`/boot/config.txt` on older OS releases) and rebooting. The station
must run as root for `/dev/watchdog` write access (which it usually
already does for GPIO).

When the station is disconnected from the server and reconnects, the
server replays the current top-of-queue Stop & Go penalty so the
station immediately knows what it should display — no Race Control
intervention needed.

### Usage

```bash
# Use config file
python stopandgo-station.py -c stopandgo-station.toml

# Override specific values from command line
python stopandgo-station.py -c stopandgo-station.toml -s different-server.com -p 9000

# Use without config file (all defaults/command line)
python stopandgo-station.py -s your-server.com -p 8000
```

### Configuration File Format

Create a TOML file with the following structure:

```toml
# Server connection settings
server = "your-server.com"
port = 8000
secure = false

# GPIO pin configuration
button = 18  # Physical pin 18 (GPIO24)
fence = 24   # Physical pin 24 (GPIO8)

# HMAC secret for message authentication
hmac_secret = "your-hmac-secret"

[logging]
level = "INFO"  # DEBUG, INFO, WARNING, ERROR
```

### Command Line Arguments

- `-c, --config`: Path to TOML configuration file
- `-s, --server`: Server hostname
- `-p, --port`: Server port
- `-S, --secure`: Use secure WebSocket (wss://)
- `-b, --button`: Physical button pin number
- `-f, --fence`: Physical fence sensor pin number
- `-d, --debug`: Set log level to DEBUG
- `-i, --info`: Set log level to INFO
- `-H, --hmac-secret`: HMAC secret key

### Priority Order

1. Command line arguments (highest priority)
2. Configuration file values
3. Built-in defaults (lowest priority)

This allows you to set common values in a config file and override specific ones as needed from the command line.