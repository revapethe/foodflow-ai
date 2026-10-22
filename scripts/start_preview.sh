#!/usr/bin/env bash
# Run in a persistent cloud terminal. Only Next.js is exposed to the preview proxy.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export NEXT_TELEMETRY_DISABLED=1
mkdir -p logs
if [[ ! -x .venv-api/bin/python || ! -f frontend/.next/BUILD_ID ]]; then
  echo 'Missing Phase 1 dependencies/build. Follow PHASE1.md cloud setup instructions.' >&2
  exit 1
fi
# Fail on existing listeners; never stop unrelated services or reuse a stale build.
.venv-api/bin/python - <<'PY'
import socket
for port in (3000, 8000):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError:
            raise SystemExit(f'Port {port} is occupied. Stop the previous FoodFlow service before restarting preview.')
PY
api_pid=''
web_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$web_pid" ]] || kill "$web_pid" 2>/dev/null || true
  [[ -z "$api_pid" ]] || kill "$api_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv-api/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 > logs/preview-api.log 2>&1 &
api_pid=$!
# Direct invocation keeps the managed PID equal to the actual Next.js process.
node frontend/node_modules/next/dist/bin/next start frontend --hostname 0.0.0.0 --port 3000 > logs/preview-web.log 2>&1 &
web_pid=$!
.venv-api/bin/python - <<'PY'
import time
from urllib.request import urlopen
for attempt in range(60):
    try:
        with urlopen('http://127.0.0.1:3000/api/health', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        pass
    time.sleep(0.5)
else:
    raise SystemExit('Preview failed readiness check. Inspect logs/preview-api.log and logs/preview-web.log.')
print('FoodFlow preview ready: frontend 0.0.0.0:3000; private FastAPI 127.0.0.1:8000.')
print('In Codex Web preview select port 3000. Logs: logs/preview-web.log and logs/preview-api.log.')
PY
# If either service exits, stop the companion instead of leaving a broken preview.
wait -n "$api_pid" "$web_pid"
