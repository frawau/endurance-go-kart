# Stop and Go Station

## Configuration

The stop and go station supports configuration via TOML files. Command line arguments will override configuration file values.

### Usage

```bash
# Use config file
python stopandgo-station.py -c stopandgo-station.toml

# Override specific values from command line
python stopandgo-station.py -c stopandgo-station.toml -s different-server.com -p 9000

# Use without config file (all defaults/command line)
python stopandgo-station.py -s gokart.wautier.eu -p 8000
```

### Configuration File Format

Create a TOML file with the following structure:

```toml
# Server connection settings
server = "gokart.wautier.eu"
port = 8000
secure = false

# GPIO pin configuration
button = 18  # Physical pin 18 (GPIO24)
fence = 24   # Physical pin 24 (GPIO8)

# Logging level
debug = false
info = true

# HMAC secret for message authentication
hmac_secret = "race_control_hmac_key_2024"
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