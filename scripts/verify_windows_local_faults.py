"""Disposable local faults; models disabled unless separately authorized and enabled.

Only owned loopback application processes are stopped. Installed Probe and
business configuration are untouched. Foreground Probe uses current identity.
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import time
import uuid
import psutil
import shutil
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def get_local(port):
    try:
        response = build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/health', timeout=2)
    except HTTPError as exc:
        response = exc
    with response:
        return response.code, response.read(2048).decode('utf-8')


def serve(port, log, downstream, mode_file):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            mode = mode_file.read_text(encoding='utf-8').strip()
            status, body = 200, 'healthy'
            if mode == 'http_error':
                status, body = 503, 'temporarily unavailable'
            elif mode == 'application_error':
                status, body = 500, 'request failed'
            elif downstream is not None:
                try:
                    status, body = get_local(downstream)
                except (URLError, OSError):
                    status, body = 503, 'upstream connection failed'
            with log.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                    'pid': os.getpid(), 'status': status, 'detail': body}) + '\n')
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body.encode())

    server = HTTPServer(('127.0.0.1', port), Handler, bind_and_activate=False)
    server.allow_reuse_address = False
    try:
        if os.name == 'nt':
            server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        server.server_bind()
        server.server_activate()
    except OSError as exc:
        server.server_close()
        with log.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'pid': os.getpid(), 'error': 'bind_failed',
                'errno': exc.errno, 'port': port}) + '\n')
        raise
    with server:
        server.serve_forever(poll_interval=0.1)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_listener(port, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('owned process exited before listening')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError('owned process did not listen')


def stop(process):
    children = []
    if process.poll() is None:
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            pass
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    _, alive = psutil.wait_procs(children, timeout=5)
    for child in alive:
        child.kill()
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError('owned child process did not stop')


def listening_rows(ports):
    return [{'port': conn.laddr.port, 'pid': conn.pid} for conn in psutil.net_connections(kind='tcp')
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port in ports]


async def evaluate_model_case(out, case, launch, previous_cost=None, knowledge_url=None, knowledge_disabled=False):
    """Only the caller's explicit paid mode may invoke this serial runner."""
    from scripts.evaluate_windows_probe import read_cost_ledger
    sample_id = uuid.uuid4().hex
    result_dir = out / ('model-' + sample_id)
    symptom_file = out / ('symptom-' + sample_id + '.txt')
    symptom_file.write_text('请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。', encoding='utf-8')
    args = [str(ROOT / 'scripts/evaluate_windows_probe.py'), '--run-model',
        '--probe-config', str(out / 'config.toml'), '--symptom-file', str(symptom_file),
        '--output-dir', str(result_dir), '--local-runbooks', str(out / 'runbooks')]
    before = read_cost_ledger(previous_cost) if previous_cost else None
    if knowledge_url:
        args += ['--knowledge-mcp-url', knowledge_url]
    if knowledge_disabled:
        args += ['--knowledge-disabled']
    if case == 'missing_evidence':
        args += ['--limited-evidence']
    if before is not None:
        if before['reserved_cny'] >= 5 or any(not row.get('usage') or row.get('http_status') != 200
                for row in before['requests']):
            raise RuntimeError('prior scenario has exhausted or uncertain cost; stopping')
        args += ['--previous-cost', str(previous_cost)]
    process = launch(args, 'model-' + case)
    code = await asyncio.to_thread(process.wait)
    if code != 0:
        raise RuntimeError('model scenario process failed: ' + case)
    summary = json.loads((result_dir / 'summary.json').read_text(encoding='utf-8'))
    cost = read_cost_ledger(result_dir / 'cost.json')
    if before is not None and cost['requests'][:len(before['requests'])] != before['requests']:
        raise ValueError('model scenario did not preserve prior cost ledger')
    if (summary.get('budget_stopped') or summary.get('execution_error') or summary.get('error_events')
            or not summary.get('has_final_report') or summary.get('report_kind') not in {
                'unlocated', 'healthy_within_checked_scope', 'root_cause_reported',
                'confirmed_cause', 'localized_fault', 'healthy_within_scope'}):
        raise RuntimeError('model scenario incomplete or failed: ' + case)
    if not cost['requests'] or any(not row.get('usage') or row.get('http_status') != 200
            for row in cost['requests']):
        raise RuntimeError('model scenario has uncertain cost; stopping')
    checks = review_model_artifacts(result_dir, case, summary)
    (result_dir / 'mechanical-review.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'case': 'real_model_workflow_' + case, 'status': 'passed' if checks['passed'] else 'failed',
        'workflow_completed': True, 'diagnostic_correctness_verified': False,
        'requires_manual_review': True, 'report_kind': summary['report_kind'],
        'cumulative_requests': len(cost['requests']), 'reserved_cny': cost['reserved_cny'],
        'cost_file': str(result_dir / 'cost.json'), 'sample_id': sample_id,
        'knowledge_enabled': not knowledge_disabled, 'diagnosis': summary.get('diagnosis'),
        'manual_verdict': 'pending', 'mechanical_review': checks, 'result_dir': str(result_dir)}


def review_model_artifacts(directory, case, summary):
    """Mechanical gates only; a human must judge causal meaning independently."""
    from src.probe.protocol import redact
    directory = Path(directory)
    events = json.loads((directory / 'events.json').read_text(encoding='utf-8')) if (directory / 'events.json').exists() else []
    trace = json.loads((directory / 'tool_trace.json').read_text(encoding='utf-8')) if (directory / 'tool_trace.json').exists() else []
    ids = {row.get('evidence_id') for row in events if row.get('type') == 'evidence'}
    diagnosis = summary.get('diagnosis') or {}
    citations = diagnosis.get('evidence', [])
    expected = {'normal': ['healthy_within_scope'], 'downstream_unreachable': ['localized_fault'],
        'application_error': ['localized_fault'], 'application_exit': ['localized_fault'],
        'port_conflict': ['localized_fault', 'confirmed_cause'], 'missing_evidence': ['unlocated', 'localized_fault']}
    allowed = {'probe_inventory', 'probe_resource_snapshot', 'probe_service_status', 'probe_process_snapshot',
        'probe_port_snapshot', 'probe_event_log', 'probe_text_log', 'probe_dependency_probe',
        'probe_list_evidence', 'search_knowledge_base', 'read_run_evidence'}
    # Model citations are produced from the persisted, redacted evidence view.
    # The tool trace contains a serialized transport representation instead;
    # nested JSON (especially text-log lines) can therefore differ in escaping
    # even when the citation is valid.  Prefer the evidence ledger and keep a
    # trace fallback for older/offline fixtures that do not have a database.
    evidence_text = _load_review_evidence_text(directory, citations)
    trace_text = json.dumps(redact([row.get('result') for row in trace if row.get('validated_live_evidence')]),
        ensure_ascii=False)
    legacy_trace = not (directory / 'runs.sqlite').exists()
    if legacy_trace:
        evidence_text = {
            c.get('evidence_id'): json.dumps(redact(row.get('result')), ensure_ascii=False)
            for row in trace if row.get('validated_live_evidence')
            for c in citations if c.get('evidence_id') == row.get('evidence_id')
        }
    quotes_observed = all(
        c.get('quote') and (
            (c.get('evidence_id') in evidence_text
             and _citation_in_evidence(c['quote'], evidence_text[c['evidence_id']]))
            or (legacy_trace and not evidence_text and c['quote'] in trace_text)
        )
        for c in citations
    )
    gates = {'structured_result': diagnosis.get('version') == 1,
        'correct_target': diagnosis.get('target_id') == 'windows-local-01',
        'current_run_ids': all(c.get('evidence_id') in ids for c in citations),
        'quotes_observed': quotes_observed,
        'no_unapproved_tool': all(row.get('tool') in allowed for row in trace),
        'has_live_observation': any(row.get('validated_live_evidence') for row in trace),
        'evidence_for_assertion': diagnosis.get('kind') == 'unlocated' or bool(citations)}
    mechanical_passed = all(gates.values())
    level_matches = diagnosis.get('kind') in expected[case]
    return {'passed': mechanical_passed, 'gates': gates,
        'mechanical_status': 'passed' if mechanical_passed else 'failed',
        'workflow_status': 'incomplete' if summary.get('budget_stopped') or summary.get('execution_error') or summary.get('has_final_report') is False else 'completed',
        'result_level_status': 'passed' if level_matches else 'failed',
        'semantic_status': 'pending_manual_review', 'capability_passed': False,
        'expected_result_levels': expected[case], 'level_matches_scenario': level_matches,
        'manual_verdict': 'pending', 'allowed_manual_verdicts': ['correct_localization', 'honest_unlocated', 'wrong_cause_or_false_positive', 'incomplete'],
        'causal_correctness_proven': False}


def _load_review_evidence_text(directory, citations):
    """Return complete redacted evidence JSON keyed by evidence id.

    The reviewer is intentionally read-only.  It only follows raw_ref values
    already recorded in this run's SQLite ledger and ignores rows from other
    evidence ids.  A missing or unreadable row is left absent so the mechanical
    gate fails closed.
    """
    from src.probe.evidence import validate_evidence
    db = (Path(directory) / 'runs.sqlite').resolve()
    if not db.exists() or not citations:
        return {}
    wanted = {c.get('evidence_id') for c in citations if c.get('evidence_id')}
    if not wanted:
        return {}
    result = {}
    try:
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as connection:
            rows = connection.execute(
                'select evidence_id, raw_ref, raw_hash from aiops_evidence where evidence_id in ({})'.format(
                    ','.join('?' for _ in wanted)), tuple(wanted)).fetchall()
    except (OSError, sqlite3.Error):
        return {}
    root = (Path(directory) / 'evidence').resolve()
    for evidence_id, raw_ref, digest in rows:
        if not raw_ref:
            continue
        path = Path(raw_ref)
        try:
            if path.resolve(strict=True).parent != root or path.name != evidence_id + '.json':
                continue
            text = path.read_text(encoding='utf-8')
            raw = json.loads(text)
            when = datetime.fromisoformat(raw['collected_at'].replace('Z', '+00:00'))
            validate_evidence(raw, target_id='windows-local-01', now=when)
            if raw['raw_hash'] != digest:
                continue
            result[evidence_id] = text
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return result


def _citation_in_evidence(quote, evidence_text):
    """Match a model quote against raw JSON and its decoded JSON view."""
    if quote in evidence_text:
        return True
    try:
        decoded = json.loads(evidence_text)
    except (TypeError, ValueError):
        return False
    return quote in json.dumps(decoded, ensure_ascii=False, sort_keys=True)


async def evaluate_blind_cases(out, launch, set_case, knowledge_url=None, suite=None, previous_cost=None):
    """Controller keeps the scenario order outside the investigation context."""
    order = list(suite or ['normal', 'downstream_unreachable'])
    secrets.SystemRandom().shuffle(order)
    results, previous = [], previous_cost
    controller = {'results': results, 'injections': [], 'recovery': 'pending',
        'answer_visibility': 'not_in_model_context_or_probe_allowlist'}
    try:
        for case in order:
            await set_case(case)
            controller['injections'].append({'case': case, 'injected_at': datetime.now(timezone.utc).isoformat()})
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
            result = await evaluate_model_case(out, case, launch, previous, knowledge_url=knowledge_url)
            results.append(result)
            previous = Path(result['cost_file'])
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        controller['failure'] = {'case': case, 'status': 'incomplete', 'exception_type': type(exc).__name__,
            'failed_at': datetime.now(timezone.utc).isoformat()}
        raise
    finally:
        await set_case('normal')
        controller['recovery'] = 'normal_restored'
        (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


async def verify(out, evaluation_preflight=False, run_model=False, model_stage='smoke', previous_cost=None):
    from scripts.windows_probe import _set_acl
    from src.probe.evidence import validate_tool_evidence
    from langchain_mcp_adapters.client import MultiServerMCPClient

    target, token = 'windows-local-01', uuid.uuid4().hex + uuid.uuid4().hex
    ports = []
    while len(ports) < 4:
        candidate = free_port()
        if candidate not in ports:
            ports.append(candidate)
    gateway_port, app_port, dep_port, knowledge_port = ports
    out.mkdir(parents=True, exist_ok=False)
    if os.name == 'nt':
        _set_acl(out)
    shutil.copytree(ROOT / 'docs/fixtures/windows-local-runbooks', out / 'runbooks')
    env = os.environ.copy()
    env.update({'DATABASE_URL': 'sqlite:///' + (out / 'ledger.sqlite').as_posix(),
        'PROBE_EVIDENCE_DIR': str(out / 'evidence'), 'PROBE_TOKEN': token, 'PROBE_TARGET_ID': target,
        'RAG_AIOPS_PROBE_CONFIG': str(out / 'config.toml')})
    os.environ.update({key: env[key] for key in ('DATABASE_URL', 'PROBE_EVIDENCE_DIR')})
    from src.agent.aiops import run_store
    from src.database.sql_session import engine
    from src.settings import settings
    assert settings.DATABASE_URL == env['DATABASE_URL']
    settings.PROBE_TARGET_ID = target
    from src.agent.aiops.executor import _run_tool_calls, _record_probe_evidence
    (out / 'token').write_text(token, encoding='utf-8')
    log = out / 'app.log'
    log.touch()
    app_mode, dep_mode = out / 'app.mode', out / 'downstream.mode'
    app_mode.write_text('normal', encoding='utf-8')
    dep_mode.write_text('normal', encoding='utf-8')
    (out / 'config.toml').write_text('\n'.join([f"target_id = '{target}'",
        f"gateway_url = 'ws://127.0.0.1:{gateway_port}/probe/ws'",
        f"token_file = '{(out / 'token').as_posix()}'", 'baseline_interval_seconds = 60',
        '[services.localapp]', "kind = 'process'",
        "process_names = ['python.exe']", f"text_logs = ['{log.as_posix()}']",
        '[dependencies.localapp]', "host = '127.0.0.1'", f'port = {app_port}',
        "health_scheme = 'http'", "health_path = '/health'",
        '[dependencies.downstream]', "host = '127.0.0.1'", f'port = {dep_port}',
        "health_scheme = 'http'", "health_path = '/health'"]), encoding='utf-8')
    owned, records, cases = [], [], []
    report = {'ok': False, 'model_calls': None if run_model else 0, 'target_id': target, 'cases': cases,
        'probe_identity': 'temporary foreground current-account probe, not installed LocalService',
        'model_investigation': 'requested_not_started' if run_model else 'not_run', 'ports': ports, 'errors': []}
    with ExitStack() as stack:
        def launch(args, name):
            handle = stack.enter_context((out / (name + '.stderr')).open('wb'))
            proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                stdout=handle, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            owned.append(proc)
            return proc

        def application(port, mode, name, dependency=None):
            args = [str(Path(__file__).resolve()), '--serve', str(port), '--log', str(log), '--mode-file', str(mode)]
            if dependency is not None:
                args += ['--downstream', str(dependency)]
            proc = launch(args, name)
            wait_listener(port, proc)
            return proc

        probe = None
        try:
            dep = application(dep_port, dep_mode, 'downstream')
            app = application(app_port, app_mode, 'application', dep_port)
            gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host', '127.0.0.1',
                '--port', str(gateway_port)], 'gateway')
            wait_listener(gateway_port, gateway)
            probe = launch(['-c', 'import asyncio; from pathlib import Path; from scripts.windows_probe import run_probe; '
                f'asyncio.run(run_probe(lambda: Path({str(out / "stop-probe")!r}).exists()))'], 'probe')
            client = MultiServerMCPClient({'probe': {'transport': 'streamable_http',
                'url': f'http://127.0.0.1:{gateway_port}/mcp', 'headers': {'Authorization': 'Bearer ' + token}}})
            tools = {tool.name: tool for tool in await client.get_tools()}
            assert len(tools) == 9
            assert not any(name in tools for name in ('probe_exec', 'probe_restart_service', 'probe_write_file'))
            from src.agent.mcp_client import load_tools_for_config, close_client_for_config
            knowledge_server = launch([str(ROOT / 'scripts/verify_windows_probe_graph.py'),
                '--serve-knowledge', str(knowledge_port), '--runbooks', str(out / 'runbooks')], 'knowledge-mcp')
            wait_listener(knowledge_port, knowledge_server)
            knowledge_config = {'knowledge': {'transport': 'streamable_http',
                'url': f'http://127.0.0.1:{knowledge_port}/mcp'}}
            stack.callback(close_client_for_config, knowledge_config)
            knowledge_tools, knowledge_error = await load_tools_for_config(knowledge_config)
            assert knowledge_error is None and [tool.name for tool in knowledge_tools] == ['search_knowledge_base']
            knowledge_tool = knowledge_tools[0]
            from src.agent.aiops.evidence_sources import knowledge_context
            other_kb = await knowledge_tool.ainvoke({'query': 'localapp availability', 'kb_id': 999, 'top_k': 3})
            assert knowledge_context([('other library', other_kb)]) == []
            cases.append({'case': 'local_knowledge_mcp_isolation', 'status': 'passed',
                'transport': 'streamable_http_loopback', 'vector_rag_evaluated': False})

            async def query(name, args, case):
                messages = await _run_tool_calls([{'id': uuid.uuid4().hex, 'name': name, 'args': args}], tools)
                if messages[0].artifact['status'] != 'success':
                    raise ValueError('formal executor rejected ' + name + ': ' + messages[0].content)
                raw = validate_tool_evidence(messages[0].content, tool_name=name, target_id=target)
                events = _record_probe_evidence({'thread_id': case, 'user_id': 1}, messages[0].content, raw['operation'])
                assert len(events) == 1
                eid = events[0]['evidence_id']
                records.append({'case': case, 'evidence_id': eid, 'raw': raw})
                return raw

            for attempt in range(20):
                try:
                    await query('probe_inventory', {}, 'connection')
                    break
                except ValueError:
                    if attempt == 19:
                        raise
                    await asyncio.sleep(0.5)

            async def observe(case):
                health = (await query('probe_dependency_probe', {'dependency': 'localapp'}, case))['payload']
                dependency = (await query('probe_dependency_probe', {'dependency': 'downstream'}, case))['payload']
                logs = (await query('probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 100}, case))['payload']
                result = {'case': case, 'app_tcp': health['tcp'], 'app_http': health.get('http', {}).get('status'),
                    'dependency_tcp': dependency['tcp'], 'dependency_http': dependency.get('http', {}).get('status'),
                    'log_lines': len(logs.get('lines', [])), 'status': 'pending'}
                cases.append(result)
                return result, logs

            async def check_evaluation_entry(case):
                if not evaluation_preflight:
                    return
                result_dir = out / ('evaluation-' + case)
                symptom_file = out / ('symptom-' + case + '.txt')
                symptom_file.write_text('请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。', encoding='utf-8')
                process = launch([str(ROOT / 'scripts/evaluate_windows_probe.py'),
                    '--probe-config', str(out / 'config.toml'), '--symptom-file', str(symptom_file),
                    '--output-dir', str(result_dir), '--local-runbooks', str(out / 'runbooks'),
                    '--knowledge-mcp-url', knowledge_config['knowledge']['url']], 'evaluation-preflight-' + case)
                code = await asyncio.to_thread(process.wait, 45)
                assert code == 0, 'evaluation preflight failed: ' + case
                result = json.loads((result_dir / 'preflight.json').read_text(encoding='utf-8'))
                assert result['ok'] and result['model_calls'] == 0 and result['evidence_count'] == 4
                assert not (result_dir / 'cost.json').exists(), 'free preflight entered paid budget path'
                assert len(result['tool_names']) == 10
                assert result['knowledge_mcp']['transport'] == 'streamable_http_loopback'
                assert not result['knowledge_mcp']['autonomously_selected']
                tool_trace = json.loads((result_dir / 'tool_trace.json').read_text(encoding='utf-8'))
                assert len(tool_trace) == 5
                assert sum(row['validated_live_evidence'] for row in tool_trace) == 4
                knowledge_rows = [row for row in tool_trace if row['tool'] == 'search_knowledge_base']
                assert len(knowledge_rows) == 1 and knowledge_rows[0]['source'] == 'knowledge_base'
                assert not knowledge_rows[0]['validated_live_evidence']
                knowledge = json.loads((result_dir / 'knowledge_trace.json').read_text(encoding='utf-8'))
                assert knowledge['mode'] == 'local_runbooks' and not knowledge['vector_rag_evaluated']
                assert knowledge['queries'][0]['retrieved']
                assert '手册不是现场事实' in knowledge['queries'][0]['context']
                assert (result_dir / 'symptom.txt').read_text(encoding='utf-8') == symptom_file.read_text(encoding='utf-8')
                for item in result['checks']:
                    validate_tool_evidence(item['raw'], tool_name=item['tool'], target_id=target)
                dependencies = {row['arguments']['dependency']: row['raw']['payload']
                    for row in result['checks'] if row['tool'] == 'probe_dependency_probe'}
                assert dependencies['localapp']['http']['status'] == (200 if case == 'normal' else 503)
                assert dependencies['downstream']['tcp'] == ('ok' if case == 'normal' else 'failed')
                cases.append({'case': 'evaluation_preflight_' + case, 'status': 'passed',
                    'model_calls': 0, 'autonomous_model_investigation': False,
                    'evidence_count': result['evidence_count'], 'result_dir': result_dir.name})

            normal, _ = await observe('normal')
            assert normal['app_http'] == normal['dependency_http'] == 200
            normal['status'] = 'passed'
            await check_evaluation_entry('normal')
            blocker = None
            async def set_model_case(case):
                nonlocal dep, app, blocker
                if blocker and blocker.poll() is None:
                    stop(blocker)
                blocker = None
                if app.poll() is None:
                    stop(app)
                if dep.poll() is None:
                    stop(dep)
                app_mode.write_text('application_error' if case in {'application_error', 'missing_evidence'} else 'normal', encoding='utf-8')
                dep_mode.write_text('normal', encoding='utf-8')
                log.write_text('', encoding='utf-8')
                if case == 'downstream_unreachable':
                    pass
                else:
                    dep = application(dep_port, dep_mode, 'model-dependency-' + uuid.uuid4().hex)
                if case == 'port_conflict':
                    blocker = application(app_port, dep_mode, 'model-owner-' + uuid.uuid4().hex)
                    app = launch([str(Path(__file__).resolve()), '--serve', str(app_port), '--log', str(log),
                        '--mode-file', str(app_mode), '--downstream', str(dep_port)], 'model-bind-' + uuid.uuid4().hex)
                    assert await asyncio.to_thread(app.wait, 5) != 0
                elif case != 'application_exit':
                    app = application(app_port, app_mode, 'model-app-' + uuid.uuid4().hex, dep_port)
                if case == 'missing_evidence':
                    log.unlink(missing_ok=True)
            if evaluation_preflight:
                for case in ['normal', 'downstream_unreachable', 'application_error',
                             'application_exit', 'port_conflict', 'missing_evidence']:
                    await set_model_case(case)
                    health = (await query('probe_dependency_probe', {'dependency': 'localapp'}, 'controller-' + case))['payload']
                    downstream = (await query('probe_dependency_probe', {'dependency': 'downstream'}, 'controller-' + case))['payload']
                    if case == 'application_exit':
                        assert health['tcp'] == 'failed' and downstream['http']['status'] == 200
                    else:
                        expected = {'normal': 200, 'downstream_unreachable': 503,
                                    'application_error': 500, 'port_conflict': 200, 'missing_evidence': 500}[case]
                        assert health['http']['status'] == expected
                    assert downstream['tcp'] == ('failed' if case == 'downstream_unreachable' else 'ok')
                    if case == 'port_conflict':
                        rows = (await query('probe_port_snapshot', {'local_port': app_port, 'listening_only': True}, 'controller-' + case))['payload']['ports']
                        owner_pids = {blocker.pid} | {p.pid for p in psutil.Process(blocker.pid).children(recursive=True)}
                        assert any(row['pid'] in owner_pids for row in rows)
                        assert 'bind_failed' in log.read_text(encoding='utf-8')
                    cases.append({'case': 'controller_preflight_' + case, 'status': 'passed',
                                  'model_calls': 0, 'autonomous_model_investigation': False})
                await set_model_case('normal')
                assert get_local(app_port)[0] == get_local(dep_port)[0] == 200
            if run_model:
                report['model_investigation'] = 'started_requires_manual_review'
                if model_stage == 'knowledge-control':
                    previous = previous_cost
                    modes = [False, True]
                    secrets.SystemRandom().shuffle(modes)
                    for disabled in modes:
                        await set_model_case('downstream_unreachable')
                        result = await evaluate_model_case(out, 'downstream_unreachable', launch, previous,
                            knowledge_url=knowledge_config['knowledge']['url'], knowledge_disabled=disabled)
                        cases.append(result)
                        previous = Path(result['cost_file'])
                    await set_model_case('normal')
                else:
                    suite = ['application_error', 'application_exit', 'port_conflict', 'missing_evidence'] if model_stage == 'extended' else None
                    cases.extend(await evaluate_blind_cases(out, launch, set_model_case,
                        knowledge_url=knowledge_config['knowledge']['url'], suite=suite, previous_cost=previous_cost))
            from scripts.verify_windows_probe_graph import verify_graph
            cases.append(await verify_graph(tools, out, log, 'normal', knowledge_tool))
            process_snapshot = await query('probe_process_snapshot', {'service': 'localapp'}, 'normal')
            app_pids = {app.pid} | {p.pid for p in psutil.Process(app.pid).children(recursive=True)}
            assert app_pids & {row['pid'] for row in process_snapshot['payload']['processes']}
            stop(app)
            exited, _ = await observe('application_exit')
            assert exited['app_tcp'] == 'failed' and exited['dependency_http'] == 200
            assert app.poll() is not None
            after_exit = await query('probe_process_snapshot', {'service': 'localapp'}, 'application_exit')
            assert not app_pids & {row['pid'] for row in after_exit['payload']['processes']}
            exited['status'] = 'passed'
            app = application(app_port, app_mode, 'application-recovered', dep_port)
            recovered, _ = await observe('application_recovered')
            assert recovered['app_http'] == 200
            recovered['status'] = 'passed'
            stop(dep)
            down, logs = await observe('downstream_unreachable')
            assert app.poll() is None and down['app_tcp'] == 'ok' and down['app_http'] == 503
            assert down['dependency_tcp'] == 'failed' and 'upstream connection failed' in str(logs)
            down['status'] = 'passed'
            await check_evaluation_entry('downstream_unreachable')
            cases.append(await verify_graph(tools, out, log, 'downstream_unreachable', knowledge_tool))
            dep = application(dep_port, dep_mode, 'downstream-recovered')
            recovered, _ = await observe('downstream_recovered')
            assert recovered['app_http'] == 200
            recovered['status'] = 'passed'
            dep_mode.write_text('http_error', encoding='utf-8')
            http, _ = await observe('http_unhealthy')
            assert http['dependency_tcp'] == 'ok' and http['dependency_http'] == http['app_http'] == 503
            http['status'] = 'passed'
            dep_mode.write_text('normal', encoding='utf-8')
            app_mode.write_text('application_error', encoding='utf-8')
            error, logs = await observe('application_error')
            assert error['app_http'] == 500 and error['dependency_http'] == 200 and 'request failed' in str(logs)
            error['status'] = 'passed'
            app_mode.write_text('normal', encoding='utf-8')
            stop(app)
            blocker = application(app_port, dep_mode, 'port-owner')
            failed = launch([str(Path(__file__).resolve()), '--serve', str(app_port), '--log', str(log),
                '--mode-file', str(app_mode), '--downstream', str(dep_port)], 'bind-failure')
            assert await asyncio.to_thread(failed.wait, 5) != 0
            logs = (await query('probe_text_log', {'service': 'localapp', 'path': str(log)}, 'port_conflict'))['payload']
            snapshot = await query('probe_port_snapshot', {'local_port': app_port, 'listening_only': True}, 'port_conflict')
            owners = [row for row in snapshot['payload']['ports']
                if (row.get('local') or {}).get('port') == app_port and row.get('status') == 'LISTEN']
            owned_pids = {blocker.pid} | {p.pid for p in psutil.Process(blocker.pid).children(recursive=True)}
            found = any(row['pid'] in owned_pids for row in owners)
            cases.append({'case': 'port_conflict', 'status': 'passed' if found else 'inconclusive',
                'owner_found': found, 'owner_pids': [row['pid'] for row in owners],
                'ports_truncated': bool(snapshot.get('truncated'))})
            assert 'bind_failed' in str(logs)
            stop(blocker)
            app = application(app_port, app_mode, 'final-application', dep_port)
            final, _ = await observe('final_recovery')
            assert final['app_http'] == final['dependency_http'] == 200
            final['status'] = 'passed'
            import httpx
            from langchain_core.tools import ToolException
            from src.probe.evidence import EvidenceValidationError, validate_evidence
            from copy import deepcopy
            async with httpx.AsyncClient() as http:
                rejected = await http.post(f'http://127.0.0.1:{gateway_port}/mcp',
                    headers={'Authorization': 'Bearer deliberately-invalid'}, json={})
                assert rejected.status_code == 401
            for tool_name, args in [
                ('probe_dependency_probe', {'dependency': 'unconfigured'}),
                ('probe_text_log', {'service': 'localapp', 'path': str(out / 'token')}),
            ]:
                try:
                    await tools[tool_name].ainvoke(args)
                except ToolException as exc:
                    assert 'ProbeConfigError' in str(exc)
                else:
                    raise AssertionError('outside-allowlist request was not rejected')
            async with client.session('probe') as session:
                denied = await session.call_tool('probe_exec', {'command': 'not-executable-test-value'})
                assert denied.isError
            cases.append({'case': 'mcp_auth_and_allowlist_denials', 'status': 'passed'})
            for mutation in ('target', 'hash', 'expired'):
                invalid = deepcopy(records[-1]['raw'])
                if mutation == 'target':
                    invalid['target_id'] = 'other-target'
                elif mutation == 'hash':
                    invalid['payload']['unexpected'] = 'tampered'
                else:
                    invalid['collected_at'] = '2020-01-01T00:00:00Z'
                try:
                    validate_evidence(invalid, target_id=target)
                except EvidenceValidationError:
                    pass
                else:
                    raise AssertionError('invalid evidence accepted: ' + mutation)
            cases.append({'case': 'invalid_evidence_denials', 'status': 'passed'})
            def decode(value):
                if isinstance(value, str):
                    return decode(json.loads(value))
                if isinstance(value, list):
                    return decode(value[0])
                if value.get('type') == 'text':
                    return decode(value['text'])
                return value

            async def wait_probe(case):
                for attempt in range(20):
                    try:
                        return await query('probe_inventory', {}, case)
                    except ValueError:
                        if attempt == 19:
                            raise
                        await asyncio.sleep(0.5)

            before = decode(await tools['probe_list_evidence'].ainvoke({'limit': 10}))
            assert before['baseline_history'] and before['status']['status'] == 'online'
            previous_hashes = {row['raw_hash'] for row in before['baseline_history']}
            (out / 'stop-probe').touch()
            await asyncio.to_thread(probe.wait, 20)
            for attempt in range(20):
                offline = decode(await tools['probe_list_evidence'].ainvoke({'limit': 10}))
                if offline['status']['status'] == 'offline':
                    break
                await asyncio.sleep(0.2)
            assert offline['status']['status'] == 'offline'
            assert not offline['baseline_summary']['current']
            try:
                validate_tool_evidence(await tools['probe_inventory'].ainvoke({}),
                    tool_name='probe_inventory', target_id=target)
            except EvidenceValidationError:
                pass
            else:
                raise AssertionError('offline summary accepted as current evidence')
            (out / 'stop-probe').unlink()
            probe = launch(['-c', 'import asyncio; from pathlib import Path; from scripts.windows_probe import run_probe; '
                f'asyncio.run(run_probe(lambda: Path({str(out / "stop-probe")!r}).exists()))'], 'probe-reconnected')
            await wait_probe('probe_reconnected')
            cases.append({'case': 'probe_disconnect_reconnect', 'status': 'passed'})
            stop(gateway)
            gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host', '127.0.0.1',
                '--port', str(gateway_port)], 'gateway-restarted')
            wait_listener(gateway_port, gateway)
            await wait_probe('gateway_restarted')
            after = decode(await tools['probe_list_evidence'].ainvoke({'limit': 10}))
            assert after['status']['status'] == 'online'
            assert after['history_error'] is None
            assert previous_hashes & {row['raw_hash'] for row in after['baseline_history']}
            assert all(row['historical'] and not row['current'] for row in after['baseline_history'])
            cases.append({'case': 'gateway_restart_persisted_baseline', 'status': 'passed'})
            engine.dispose()
            for item in records:
                saved = run_store.get_evidence(item['case'], item['evidence_id'], 1, include_raw=True)
                assert saved and saved['raw'] == item['raw']
                assert run_store.get_evidence(item['case'], item['evidence_id'], 2) is None
            report['evidence_count'] = len(records)
            report['formal_executor_and_evidence_writer'] = True
            report['ledger_reopened'] = True
            report['ok'] = all(case['status'] == 'passed' for case in cases)
        except Exception as exc:
            report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:300]})
        finally:
            (out / 'stop-probe').touch()
            if probe and probe.poll() is None:
                try:
                    await asyncio.to_thread(probe.wait, 20)
                except subprocess.TimeoutExpired:
                    report['errors'].append({'type': 'cleanup', 'message': 'probe did not stop gracefully'})
            for process in reversed(owned):
                stop(process)
            report['owned_processes_stopped'] = all(proc.poll() is not None for proc in owned)
            report['remaining_listeners'] = listening_rows(ports)
            report['ports_released'] = not report['remaining_listeners']
            if run_model:
                report['cost_records'] = []
                for path in sorted(out.glob('model-*/cost.json')):
                    from scripts.evaluate_windows_probe import read_cost_ledger
                    try:
                        cost = read_cost_ledger(path)
                        report['cost_records'].append({'path': str(path.relative_to(out)),
                            'reserved_cny': cost['reserved_cny'], 'requests': len(cost['requests'])})
                    except (ValueError, OSError) as exc:
                        report['errors'].append({'type': 'cost_audit', 'message': str(exc)[:200]})
                report['model_calls'] = None
                report['model_request_accounting'] = 'See cumulative cost ledgers; missing usage is not zero cost'
            report['ok'] = report['ok'] and not report['errors'] and report['owned_processes_stopped'] and report['ports_released']
            (out / 'evidence.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=int)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--mode-file', type=Path)
    parser.add_argument('--downstream', type=int)
    parser.add_argument('--evaluation-preflight', action='store_true')
    parser.add_argument('--run-model', action='store_true',
        help='Paid two-case mode; requires separate explicit user authorization, cumulative <=5 CNY')
    parser.add_argument('--model-stage', choices=['smoke', 'extended', 'knowledge-control'], default='smoke')
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--smoke-review', type=Path, help='Human review JSON with smoke_passed=true, required before extended cases')
    args = parser.parse_args()
    if args.serve is not None:
        serve(args.serve, args.log, args.downstream, args.mode_file)
        return 0
    if args.run_model and args.model_stage == 'extended':
        if not args.smoke_review or json.loads(args.smoke_review.read_text(encoding='utf-8')).get('smoke_passed') is not True:
            parser.error('extended cases require a completed human smoke review')
    if args.run_model and args.model_stage in {'extended', 'knowledge-control'} and not args.previous_cost:
        parser.error('later stages require the cumulative cost ledger; retries must not reset the budget')
    out = ROOT / 'runtime' / ('windows-local-faults-' + uuid.uuid4().hex)
    report = asyncio.run(verify(out, evaluation_preflight=args.evaluation_preflight, run_model=args.run_model,
        model_stage=args.model_stage, previous_cost=args.previous_cost))
    print(json.dumps({'directory': str(out), **report}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
