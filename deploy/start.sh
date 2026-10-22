#!/usr/bin/env bash
# Single Render service: public Next.js, private FastAPI, bundled read-only SQLite.
set -euo pipefail
cd "${FOODFLOW_APP_ROOT:-/app}"
port="${PORT:-10000}"
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 || port == 8000 )); then
  echo 'PORT must be an integer between 1024 and 65535, other than private API port 8000.' >&2
  exit 1
fi
api_pid=''
web_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$web_pid" ]] || kill "$web_pid" 2>/dev/null || true
  [[ -z "$api_pid" ]] || kill "$api_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
python - <<'PY'
import time
from urllib.request import urlopen
for attempt in range(60):
    try:
        with urlopen('http://127.0.0.1:8000/health', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        pass
    time.sleep(0.5)
else:
    raise SystemExit('FastAPI failed readiness; inspect the service logs.')
PY
node frontend/node_modules/next/dist/bin/next start frontend --hostname 0.0.0.0 --port "$port" &
web_pid=$!
set +e
wait -n "$api_pid" "$web_pid"
status=$?
set -e
# An unexpected clean child exit also requires the service to restart.
if (( status == 0 )); then status=1; fi
exit "$status"
