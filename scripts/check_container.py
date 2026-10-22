"""Exercise an existing image under free-demo limits; always remove only own containers."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, check=True, timeout=60):
    return subprocess.run(['docker', *args], check=check, capture_output=True, text=True, timeout=timeout)


def ready(port):
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
                if json.load(response) == {'status': 'ok'}:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('Container readiness timed out')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--port', type=int, default=10005)
    parser.add_argument('--expected-revision')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use a nonprivileged port')
    name = 'foodflow-check-' + uuid.uuid4().hex[:12]
    invalid = name + '-invalid'
    try:
        docker('run', '--name', name, '-d', '--memory=512m', '--cpus=1', '-p', f'127.0.0.1:{args.port}:10000', args.image)
        ready(args.port)
        command = [sys.executable, str(ROOT/'scripts/check_release.py'), '--web-url', f'http://127.0.0.1:{args.port}']
        if args.expected_revision:
            command += ['--expected-revision', args.expected_revision]
        if args.report:
            command += ['--report', str(args.report)]
        subprocess.run(command, cwd=ROOT, check=True, timeout=180)
        if args.report:
            report = json.loads(args.report.read_text())
            report['status'] = 'in_progress'
            args.report.write_text(json.dumps(report, indent=2)+'\n')
        docker('exec', name, 'python', '-c', '''import os,pathlib
assert os.getuid()==10001
assert pathlib.Path('/app/warehouse/foodflow.db').stat().st_mode&0o222==0
assert not pathlib.Path('/app/.git').exists()
assert not pathlib.Path('/run/secrets/build_ca').exists()
assert not pathlib.Path('/app/.env').exists()
''')
        # Kill only the API in this newly created test container. Supervision must
        # shut down the companion process and exit, then recover on restart.
        docker('exec', name, 'python', '-c', '''import os,pathlib,signal
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    try: args=path.read_bytes().split(b'\\0')
    except OSError: continue
    if b'uvicorn' in args and b'api.main:app' in args:
        os.kill(int(path.parent.name),signal.SIGTERM); break
else: raise SystemExit('Private API process not found')
''')
        exited = docker('wait', name, timeout=30)
        if int(exited.stdout.strip()) == 0:
            raise RuntimeError('Unexpected clean supervision exit')
        state = json.loads(docker('inspect', '--format', '{{json .State}}', name).stdout)
        if state['OOMKilled']:
            raise RuntimeError('Container was OOM killed')
        docker('start', name); ready(args.port)
        rejected = docker('run', '--name', invalid, '-e', 'PORT=8000', args.image, check=False, timeout=30)
        if rejected.returncode == 0 or 'PORT must be' not in rejected.stderr + rejected.stdout:
            raise RuntimeError('Conflicting private API port was not rejected')
        if args.report:
            report['status'] = 'passed'
            report['container'] = {'memory_limit_mb':512, 'cpu_limit':1, 'nonroot':True,
                'database_file_readonly':True, 'api_supervision':True, 'restart_recovery':True,
                'invalid_port_rejected':True, 'oom_killed':False}
            args.report.write_text(json.dumps(report, indent=2)+'\n')
        print('Container passed: 512 MB/one CPU, nonroot, read-only data, API supervision, restart, invalid PORT rejection.')
    except Exception as exc:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({'status':'failed', 'error_type':type(exc).__name__}, indent=2)+'\n')
        logs = docker('logs', '--tail', '40', name, check=False)
        print(logs.stdout+logs.stderr, file=sys.stderr)
        raise
    finally:
        docker('rm', '-f', name, check=False)
        docker('rm', '-f', invalid, check=False)


if __name__ == '__main__':
    main()
