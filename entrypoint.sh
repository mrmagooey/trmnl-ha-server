#!/bin/sh
set -e

if [ -f /data/options.json ]; then
    # Running as HA app — map supervisor environment to server env vars
    export HASS_URL="http://supervisor/core"
    export HASS_TOKEN="${SUPERVISOR_TOKEN}"
    export CONFIG_PATH="/config/config.yaml"

    # Read user-configured options from /data/options.json
    eval "$(python3 -c "
import json
d = json.load(open('/data/options.json'))
sn = d.get('server_name', '').replace(\"'\", \"'\\\\''\")
print(f\"export SERVER_NAME='{sn}'\")
print(f\"export PORT={d.get('port', 8000)}\")
if d.get('debug'):
    print('export DEBUG=1')
")"
    exec python3 server.py --port "${PORT:-8000}"
else
    # Standalone Docker — use environment variables as-is
    exec python3 server.py "$@"
fi
