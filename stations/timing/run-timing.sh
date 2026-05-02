#!/bin/sh
# Generate timing-station.toml from TIMING_* environment variables
# then exec the timing station daemon.

set -e

CONF="/app/timing-station.toml"

PLUGIN_TYPE="${TIMING_PLUGIN_TYPE:-simulator}"
TIMING_MODE="${TIMING_MODE:-duration}"
ROLLOVER="${TIMING_ROLLOVER_SECONDS:-360000.0}"
WS_URL="${TIMING_WS_URL:-ws://127.0.0.1:80/ws/timing/}"
HMAC_SECRET="${TIMING_HMAC_SECRET:-changeme}"
RECONNECT="${TIMING_RECONNECT_INTERVAL:-5.0}"
LOG_LEVEL="${TIMING_LOG_LEVEL:-INFO}"

cat > "$CONF" <<EOF
[daemon]
websocket_url = "${WS_URL}"
hmac_secret = "${HMAC_SECRET}"
reconnect_interval = ${RECONNECT}
timing_mode = "${TIMING_MODE}"
rollover_seconds = ${ROLLOVER}
buffer_db = "/app/data/crossing_buffer.db"

[plugin]
type = "${PLUGIN_TYPE}"

[plugin.simulator]
num_transponders = ${TIMING_SIM_TRANSPONDERS:-10}
lap_time_min = ${TIMING_SIM_LAP_MIN:-45.0}
lap_time_max = ${TIMING_SIM_LAP_MAX:-75.0}

[plugin.tag]
device = "${TIMING_TAG_DEVICE:-/dev/ttyUSB0}"
baud = ${TIMING_TAG_BAUD:-9600}
endian = "${TIMING_TAG_ENDIAN:-normal}"

[plugin.nettag]
host = "${TIMING_NETTAG_HOST:-192.168.0.11}"
port = ${TIMING_NETTAG_PORT:-2009}
protocol = "${TIMING_NETTAG_PROTOCOL:-udp}"

[logging]
level = "${LOG_LEVEL}"
file = "/app/data/timing-station.log"
EOF

echo "Generated ${CONF} (plugin=${PLUGIN_TYPE}, mode=${TIMING_MODE})"

exec python timing-station.py -c "$CONF"
