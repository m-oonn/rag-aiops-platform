"""Free live boundary check using only disposable loopback processes."""
import argparse
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation_record import utc_now
from scripts.evaluate_windows_probe import trace_evaluation_tools
from scripts.verify_windows_local_faults import free_port, get_local, wait_listener, stop, cleanup_owned
from src.probe.evidence import validate_tool_evidence, validate_observation_window, EvidenceValidationError


async def verify_boundary_rounds(tools, target, output, log, reset, scenarios=None):
    """Reuse the caller's live tools and owned business reset; preserve failures."""
    output.mkdir(parents=True, exist_ok=False)
    report = {'case': 'probe_observation_boundary', 'status': 'started', 'model_calls': 0,
        'autonomous_model_investigation': False, 'rounds': [], 'observations': []}
    def save():
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    row = None
    try:
        for index, case in enumerate(scenarios if scenarios is not None else ('normal', 'normal')):
            row = None
            phase = output / f'round-{index}'
            phase.mkdir()
            old = validate_tool_evidence(await tools['probe_dependency_probe'].ainvoke({'dependency': 'localapp'}),
                tool_name='probe_dependency_probe', target_id=target)
            report['observations'].append({'phase': f'old-{index}', 'raw': old})
            boundary = utc_now()
            row = {'case': case, 'boundary': boundary, 'status': 'started', 'verified_at': None}
            report['rounds'].append(row)
            save()
            try:
                validate_observation_window(old, boundary)
            except EvidenceValidationError as exc:
                if 'predates' not in str(exc):
                    raise
                row['old_observation_rejected'] = True
            else:
                raise AssertionError('pre-reset observation accepted')
            trace = []
            wrapped = {t.name: t for t in trace_evaluation_tools(list(tools.values()), target, phase, trace, boundary)}
            try:
                await wrapped['probe_text_log'].ainvoke({'service': 'localapp', 'path': str(log), 'lines': 100})
            except EvidenceValidationError as exc:
                if 'predates' not in str(exc):
                    raise
                row['old_log_rejected'] = True
            else:
                raise AssertionError('pre-reset log accepted')
            (phase / 'pre-reset.log').write_bytes(log.read_bytes())
            snapshot = await reset(case)
            row['controller_state'] = snapshot
            row['verified_at'] = utc_now()
            checks = [('probe_dependency_probe', {'dependency': 'localapp'})]
            if scenarios is not None:
                if not snapshot or snapshot.get('case') != case or snapshot.get('passed') is not True:
                    raise AssertionError('reset did not return verified controller state')
                checks.append(('probe_dependency_probe', {'dependency': 'downstream'}))
            checks.append(('probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 100}))
            for name, args in checks:
                result = await wrapped[name].ainvoke(args)
                item = validate_tool_evidence(result, tool_name=name, target_id=target)
                if name == 'probe_text_log' and not (item.get('payload') or {}).get('lines'):
                    raise AssertionError('reset log is empty')
                report['observations'].append({'phase': f'current-{index}', 'raw': item})
                if scenarios is not None:
                    payload = item['payload']
                    if name == 'probe_dependency_probe':
                        key = 'app' if args['dependency'] == 'localapp' else 'downstream'
                        expected = snapshot[key]['http_status']
                        if payload.get('dependency') != args['dependency'] or (payload.get('http') or {}).get('status') != expected or payload.get('tcp') != ('failed' if expected is None else 'ok'):
                            raise AssertionError('Probe disagrees with controller state')
                        if expected is not None and payload['http'].get('body_prefix') != snapshot[key]['body']:
                            raise AssertionError('Probe response body disagrees with controller')
                    else:
                        entries = [json.loads(line) for line in payload['lines']]
                        owners = set(snapshot['app_pids']) | set(snapshot['downstream_pids'])
                        if any(entry.get('pid') not in owners for entry in entries):
                            raise AssertionError('log contains another reset process')
                        expected_detail = {'normal': 'healthy', 'downstream_unreachable': 'upstream connection failed',
                            'application_error': 'request failed',
                            'application_config_error': 'invalid max_attempts configuration'}[case]
                        if not any(entry.get('pid') in snapshot['app_pids'] and entry.get('status') == snapshot['app']['http_status']
                                and entry.get('detail') == expected_detail for entry in entries):
                            raise AssertionError('log does not support current application state')
            row.update(status='passed', current_observations_accepted=all(r['validated_live_evidence'] for r in trace[1:]))
            if not row['current_observations_accepted']:
                raise AssertionError('current observations not validated')
            save()
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        report['failed_round'] = {'index': index, 'case': case}
        if row is not None:
            row.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        report['ended_at'] = utc_now()
        save()
    return {'case': report['case'], 'status': report['status'], 'model_calls': 0,
        'autonomous_model_investigation': False, 'rounds': len(report['rounds']),
        'evidence_count': len(report['observations']), 'result_dir': output.name}


async def verify(output):
    from langchain_mcp_adapters.client import MultiServerMCPClient
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    from scripts.windows_probe import _set_acl
    if os.name == 'nt':
        _set_acl(output)
    ports = []
    while len(ports) < 2:
        port = free_port()
        if port not in ports:
            ports.append(port)
    app_port, gateway_port = ports
    target, token = 'boundary-check', uuid.uuid4().hex + uuid.uuid4().hex
    log, mode = output / 'app.log', output / 'app.mode'
    log.touch()
    mode.write_text('normal', encoding='utf-8')
    (output / 'token').write_text(token, encoding='utf-8')
    config = output / 'config.toml'
    config.write_text('\n'.join([f"target_id = '{target}'",
        f"gateway_url = 'ws://127.0.0.1:{gateway_port}/probe/ws'",
        f"token_file = '{(output / 'token').as_posix()}'", 'baseline_interval_seconds = 60',
        '[services.localapp]', "kind = 'process'", "process_names = ['python.exe']",
        f"text_logs = ['{log.as_posix()}']", '[dependencies.localapp]',
        "host = '127.0.0.1'", f'port = {app_port}', "health_scheme = 'http'"]), encoding='utf-8')
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + (output / 'ledger.sqlite').as_posix(),
        'PROBE_EVIDENCE_DIR': str(output / 'evidence'), 'PROBE_TOKEN': token,
        'PROBE_TARGET_ID': target, 'RAG_AIOPS_PROBE_CONFIG': str(config)}
    owned, observations, rounds = [], [], []
    report = {'ok': False, 'model_calls': 0, 'ports': ports, 'rounds': rounds,
        'scope': 'normal disposable application; real Probe worker and MCP; no autonomous decisions'}
    with ExitStack() as stack:
        def launch(args, name):
            handle = stack.enter_context((output / (name + '.stderr')).open('wb'))
            process = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                stdout=handle, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            owned.append(process)
            return process
        def application(name):
            process = launch([str(ROOT / 'scripts/verify_windows_local_faults.py'),
                '--serve', str(app_port), '--log', str(log), '--mode-file', str(mode)], name)
            wait_listener(app_port, process)
            return process
        try:
            app = application('app-initial')
            gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host',
                '127.0.0.1', '--port', str(gateway_port)], 'gateway')
            wait_listener(gateway_port, gateway)
            launch(['-c', 'import asyncio; from scripts.windows_probe import run_probe; asyncio.run(run_probe())'], 'probe')
            client = MultiServerMCPClient({'probe': {'transport': 'streamable_http',
                'url': f'http://127.0.0.1:{gateway_port}/mcp', 'headers': {'Authorization': 'Bearer ' + token}}})
            tools = {tool.name: tool for tool in await client.get_tools()}
            async def collect(name, args, phase):
                result = await tools[name].ainvoke(args)
                item = validate_tool_evidence(result, tool_name=name, target_id=target)
                observations.append({'phase': phase, 'tool': name, 'raw': item})
                return result
            for attempt in range(30):
                try:
                    await collect('probe_inventory', {}, 'ready')
                    break
                except ValueError:
                    if attempt == 29:
                        raise
                    await asyncio.sleep(0.25)
            async def reset(case):
                nonlocal app
                stop(app)
                log.write_text('', encoding='utf-8')
                app = application('app-reset-' + uuid.uuid4().hex)
                assert get_local(app_port)[0] == 200
            result = await verify_boundary_rounds(tools, target, output / 'boundary', log, reset)
            details = json.loads((output / 'boundary/report.json').read_text(encoding='utf-8'))
            rounds.extend(details['rounds'])
            observations.extend(details['observations'])
            report['ok'] = result['status'] == 'passed'
        except BaseException as exc:
            report['error_type'] = type(exc).__name__
            raise
        finally:
            report.update(cleanup_owned(owned, ports))
            report.update(observation_count=len(observations), ended_at=utc_now())
            report['ok'] = report['ok'] and not report['cleanup_errors'] and report['owned_processes_stopped'] and report['ports_released']
            (output / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert report['ok'] and report['owned_processes_stopped'] and not report['remaining_listeners']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.output))
    print(json.dumps({k: result[k] for k in ('ok', 'model_calls', 'observation_count', 'owned_processes_stopped', 'remaining_listeners')}))
