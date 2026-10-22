"""Verify real gateway retention offline, with isolated SQLite and no model calls."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def serve(stop_file):
    import uvicorn
    from mcp_servers.probe_gateway import app, BASELINE_CLEANUP_INTERVAL_SECONDS
    assert BASELINE_CLEANUP_INTERVAL_SECONDS == 60
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1',
        port=int(os.environ['RETENTION_TEST_PORT']), log_level='info'))

    async def stop_when_requested():
        while not stop_file.exists():
            await asyncio.sleep(0.1)
        server.should_exit = True

    watcher = asyncio.create_task(stop_when_requested())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def verify():
    from scripts.windows_probe import _set_acl
    from scripts.verify_windows_local_faults import free_port, wait_listener, stop, listening_rows
    out = ROOT / 'runtime' / ('probe-retention-' + uuid4().hex)
    out.mkdir(parents=True)
    _set_acl(out)
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(out / 'retention.sqlite')
    os.environ['PROBE_EVIDENCE_DIR'] = str(out / 'evidence')
    os.environ['PROBE_TARGET_ID'] = 'retention-offline-target'
    os.environ['PROBE_TOKEN'] = secrets.token_urlsafe(32)
    from src.agent.aiops import run_store
    from src.database.models import ProbeSnapshot
    from src.database.sql_session import SessionLocal, engine
    import httpx

    def seed(digest, expired):
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            db.add(ProbeSnapshot(target_id='retention-offline-target', kind='baseline',
                collected_at=now - timedelta(hours=25) if expired else now,
                expires_at=now - timedelta(hours=1) if expired else now + timedelta(hours=24),
                raw_hash=digest, payload={'test': digest}))
            db.commit()

    def hashes():
        with SessionLocal() as db:
            return sorted(row.raw_hash for row in db.query(ProbeSnapshot).all())

    def unwrap(value):
        if isinstance(value, str):
            return unwrap(json.loads(value))
        if isinstance(value, list):
            return unwrap(value[0])
        if value.get('type') == 'text':
            return unwrap(value['text'])
        return value

    def offline_status(port):
        headers = {'Authorization': 'Bearer ' + os.environ['PROBE_TOKEN'],
                   'Accept': 'application/json, text/event-stream'}
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
            def rpc(body):
                response = client.post('/mcp', headers=headers, json=body)
                response.raise_for_status()
                return response
            response = rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-03-26', 'capabilities': {},
                'clientInfo': {'name': 'retention-test', 'version': '1'}}})
            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
            rpc({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            response = rpc({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                'params': {'name': 'probe_list_evidence', 'arguments': {'limit': 1}}})
            data = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))
            assert 'error' not in data and not data['result'].get('isError')
            result = unwrap(data['result']['content'])
            assert result['status']['status'] == 'offline'
            assert result['status']['hello'] is None

    report = {'ok': False, 'model_calls': 0, 'interval_seconds': 60, 'checks': [], 'errors': []}
    process = None
    port = free_port()
    stop_file = out / 'stop'
    try:
        seed('sha256:startup-expired', True)
        seed('sha256:retained', False)
        evidence_id = run_store.add_evidence('retention-run', None, 'retention-offline-target',
            'resources', {'collected_at': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                          'payload': {'cpu_percent': 12}})
        evidence = run_store.get_evidence('retention-run', evidence_id, include_raw=True)
        raw_path = Path(evidence['raw_ref'])
        original_bytes = raw_path.read_bytes()
        env = dict(os.environ, RETENTION_TEST_PORT=str(port))
        with (out / 'gateway.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                '--gateway', str(stop_file)], cwd=ROOT, env=env, stdout=log, stderr=log)
        wait_listener(port, process)
        assert hashes() == ['sha256:retained']
        offline_status(port)
        report['checks'].append('startup_cleanup_without_probe')
        seed('sha256:timer-expired', True)
        assert hashes() == ['sha256:retained', 'sha256:timer-expired']
        started = time.monotonic()
        print(json.dumps({'directory': str(out), 'stage': 'waiting_for_default_60_second_timer'}), flush=True)
        while 'sha256:timer-expired' in hashes():
            assert process.poll() is None, 'temporary gateway exited early'
            assert time.monotonic() - started < 75, 'default retention timer did not delete expired row'
            time.sleep(0.25)
        report['timer_wait_seconds'] = round(time.monotonic() - started, 3)
        assert hashes() == ['sha256:retained']
        offline_status(port)
        assert run_store.get_evidence('retention-run', evidence_id, include_raw=True) == evidence
        assert raw_path.read_bytes() == original_bytes
        report['checks'] += ['timer_cleanup_without_probe', 'unexpired_baseline_retained',
                             'diagnostic_evidence_and_raw_unchanged']
        stop_file.touch()
        process.wait(timeout=15)
        assert process.returncode == 0
        assert 'Application shutdown complete' in (out / 'gateway.log').read_text(encoding='utf-8')
        report['checks'].append('graceful_gateway_shutdown')
        report['ok'] = True
    except Exception as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
    finally:
        if process is not None:
            stop_file.touch(exist_ok=True)
            if process.poll() is None:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    stop(process)
            report['owned_process_stopped'] = process.poll() is not None
        report['remaining_listeners'] = listening_rows([port])
        report['port_released'] = not report['remaining_listeners']
        report['ok'] = report['ok'] and report.get('owned_process_stopped', False) and report['port_released']
        engine.dispose()
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(out), **report}, ensure_ascii=False), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--gateway':
        asyncio.run(serve(Path(sys.argv[2])))
    else:
        raise SystemExit(verify())
