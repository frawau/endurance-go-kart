# Stations

This directory contains the various physical stations that can be deployed around the go-kart track. Each station has its own subdirectory with its implementation, configuration, and documentation.

## Available Stations

### [Stop and Go](stopandgo/)
Handles stop-and-go penalties during races. Monitors a physical button and fence sensor to detect when a driver has completed their penalty.

### [Timing](timing/)
Transponder timing station that connects to timing hardware (TAG Heuer/Chronelec decoders) and relays crossing events to the Django application. Supports multiple decoder types via a plugin system.

## Station Structure

Each station follows a consistent structure:
```
<station-name>/
├── README.md                  # Station-specific documentation
├── <station-name>-station.py  # Main station script
├── <station-name>-station.toml # Configuration file
└── test-*.py                  # Test utilities (optional)
```

## Adding a New Station

1. Create a new directory under `stations/` with your station name
2. Add a `<station-name>-station.py` as the main entry point
3. Add a `<station-name>-station.toml` for configuration
4. Add a `README.md` documenting usage and configuration
5. Update this README to list the new station
