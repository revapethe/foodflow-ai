#!/usr/bin/env bash
# Build and validate one isolated frontend/API pair; stop only our child processes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export NEXT_TELEMETRY_DISABLED=1
export FOODFLOW_API_PORT="${FOODFLOW_API_PORT:-8005}"
export FOODFLOW_WEB_PORT="${FOODFLOW_WEB_PORT:-3005}"
export FOODFLOW_NEXT_DIST_DIR="${FOODFLOW_NEXT_DIST_DIR:-.next-release}"
export FOODFLOW_API_URL="http://127.0.0.1:${FOODFLOW_API_PORT}"
release_python="${FOODFLOW_PYTHON:-python}"
release_report_dir="${FOODFLOW_REPORT_DIR:-logs/release}"
mkdir -p "$release_report_dir"
"$release_python" - <<'PY'
import os,socket
ports=[int(os.environ[key]) for key in ('FOODFLOW_API_PORT','FOODFLOW_WEB_PORT')]
if len(set(ports))!=2 or any(not 1024<=port<=65535 for port in ports):
    raise SystemExit('Use distinct nonprivileged ports')
for port in ports:
    with socket.socket() as sock:
        try: sock.bind(('0.0.0.0',port))
        except OSError: raise SystemExit(f'Port {port} occupied; no existing services were stopped')
PY
if [[ ! -f artifacts/intelligence.json ]]; then
  echo 'Missing evaluated artifact. Run python -m src.intelligence.train first.' >&2
  exit 1
fi
npm run build --prefix frontend
npm run typecheck --prefix frontend
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
"$release_python" -m uvicorn api.main:app --host 127.0.0.1 --port "$FOODFLOW_API_PORT" > "$release_report_dir/api.log" 2>&1 &
api_pid=$!
node frontend/node_modules/next/dist/bin/next start frontend --hostname 0.0.0.0 --port "$FOODFLOW_WEB_PORT" > "$release_report_dir/web.log" 2>&1 &
web_pid=$!
"$release_python" - <<'PY'
import os,time
from urllib.request import urlopen
for attempt in range(60):
    try:
        with urlopen('http://127.0.0.1:'+os.environ['FOODFLOW_WEB_PORT']+'/api/health',timeout=2) as r:
            if r.status==200: break
    except OSError: pass
    time.sleep(.5)
else: raise SystemExit('Readiness failed; inspect release logs')
PY
FOODFLOW_WEB_URL="http://127.0.0.1:${FOODFLOW_WEB_PORT}" npm run test:e2e --prefix frontend
"$release_python" scripts/check_release.py --web-url "http://127.0.0.1:${FOODFLOW_WEB_PORT}" --report "$release_report_dir/web-check.json"
