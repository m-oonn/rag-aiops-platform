"""Disposable local faults; models disabled unless separately authorized and enabled.

Only owned loopback application processes are stopped. Installed Probe and
business configuration are untouched. Foreground Probe uses current identity.
"""
import argparse
import hashlib
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
import psutil
import shutil
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


FOUR_GROUP_SUITES = {
    'baseline-v1': ('normal', 'downstream_unreachable', 'application_error'),
    'mechanism-v1': ('normal', 'downstream_unreachable', 'application_config_error'),
    'e2-fault-pair-v1': ('downstream_unreachable', 'application_config_error'),
}

SYMPTOM_PROFILES = {
    'neutral': '请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。',
    'candidate-opportunity': (
        '请只读调查配置中的 edge 业务入口当前不可用问题。入口可能返回失败状态，但状态码本身不能确认根因。'
        '请从允许检查的入口、配置、相关依赖和日志中保留仍合理的候选；为每个未排除候选指定一个具体、可执行且能区分解释的检查，'
        '根据现场结果更新候选，遇到可靠相反证据时改查其他解释，最后分别说明已核实、未核实和检查受限之处。'
    ),
}


def symptom_text(profile):
    try:
        return SYMPTOM_PROFILES[profile]
    except KeyError as exc:
        raise ValueError('unknown symptom profile') from exc


def four_group_cases(suite):
    if suite not in FOUR_GROUP_SUITES:
        raise ValueError('unknown four-group scenario suite')
    return FOUR_GROUP_SUITES[suite]


def four_group_order(suite):
    cases = list(four_group_cases(suite))
    secrets.SystemRandom().shuffle(cases)
    order = []
    for case in cases:
        groups = ['G00', 'G10', 'G01', 'G11']
        secrets.SystemRandom().shuffle(groups)
        order.extend({'case': case, 'group': group} for group in groups)
    return order


def four_group_conditions(out):
    import hashlib
    paths = [out / 'config.toml', out / 'knowledge-manifest.json', *sorted((out / 'runbooks').rglob('*.md'))]
    if len(paths) <= 2:
        raise ValueError('four groups require fixed knowledge corpus')
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def get_local(port, timeout=2, *, path='/health', request_id=None, trace=None):
    connection = HTTPConnection('127.0.0.1', port, timeout=timeout)
    trace = trace if trace is not None else {}
    trace.update(timeout_seconds=timeout, phase='connect', connection_established=False)
    try:
        connection.connect()
        trace.update(connection_established=True, phase='send_request')
        connection.request('GET', path, headers={'X-Request-ID': request_id} if request_id else {})
        trace['phase'] = 'receive_headers'
        response = connection.getresponse()
        trace.update(response_status=response.status, phase='read_body')
        body = response.read(2048).decode('utf-8')
        trace['phase'] = 'completed'
        return response.status, body
    finally:
        connection.close()


def serve(port, log, downstream, mode_file, stop_file=None, runtime_config=None):
    # Opt-in fixture: this application's connection settings are loaded only at startup.
    loaded = None
    upstream_timeout = 0.5
    instance = uuid.uuid4().hex
    if runtime_config is not None:
        source = runtime_config.read_bytes()
        parsed = json.loads(source)
        downstream = parsed['downstream_port']
        upstream_timeout = parsed.get('upstream_timeout_seconds', 0.5)
        if type(upstream_timeout) not in (int, float) or not 0 < upstream_timeout <= 3:
            raise ValueError('invalid upstream_timeout_seconds')
        if downstream is not None and (type(downstream) is not int or not 1 <= downstream <= 65535):
            raise ValueError('invalid downstream_port')
        loaded = {'source': str(runtime_config.resolve()),
            'source_sha256': hashlib.sha256(source).hexdigest(), 'loading': 'startup'}

    def emit(event):
        with log.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                'pid': os.getpid(), 'instance_id': instance, **event}) + '\n')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            started = time.monotonic()
            request_id = self.headers.get('X-Request-ID') or uuid.uuid4().hex
            connection_error = None
            upstream_trace = {}
            config_bytes = mode_file.read_bytes()
            mode = config_bytes.decode('utf-8').strip()
            status, body = 200, 'healthy'
            detail, error_type = '', None
            configuration = None
            if mode.startswith('{'):
                parsed = None
                try:
                    # The controller may inject invalid application configuration.
                    parsed = json.loads(mode)
                    int(parsed['max_attempts'])
                    # A startup connection file doubles as the mode file so the
                    # loaded configuration hash and the injected mode stay identical.
                    mode = parsed.get('mode') if isinstance(parsed, dict) and parsed.get('mode') in {
                        'application_error', 'http_error'} else 'normal'
                except (ValueError, TypeError, KeyError) as exc:
                    status, body = 503, 'temporarily unavailable'
                    detail, error_type = 'invalid max_attempts configuration', type(exc).__name__
                    configuration = {'source': str(mode_file.resolve()), 'field': 'max_attempts',
                        'value': parsed.get('max_attempts') if isinstance(parsed, dict) else None,
                        'value_present': isinstance(parsed, dict) and 'max_attempts' in parsed,
                        'expected': 'integer-convertible',
                        'source_sha256': hashlib.sha256(config_bytes).hexdigest()}
            if error_type:
                pass
            elif mode == 'http_error':
                status, body = 503, 'temporarily unavailable'
            elif mode == 'application_error':
                status, body = 500, 'request failed'
            elif runtime_config is not None and self.path == '/live':
                status, body = 200, 'alive'
            elif downstream is not None:
                try:
                    if runtime_config is not None:
                        status, body = get_local(downstream, timeout=upstream_timeout, path=self.path,
                            request_id=request_id, trace=upstream_trace)
                    else:
                        status, body = get_local(downstream, timeout=0.5)
                except (URLError, OSError, HTTPException) as exc:
                    status, body = 503, 'temporarily unavailable'
                    detail = 'upstream connection failed'
                    connection_error = getattr(exc, 'reason', exc)
            elif runtime_config is not None and self.path == '/api/availability':
                body = json.dumps({'sku': 'demo-item', 'available': True})
            if runtime_config is not None:
                emit({'event': 'request_completed', 'request_id': request_id, 'path': self.path,
                    'status': status, 'detail': detail or body,
                    'duration_ms': round((time.monotonic() - started) * 1000, 3),
                    'configuration': configuration or loaded,
                    'upstream': {'host': '127.0.0.1', 'port': downstream},
                    **({'error_type': error_type} if error_type else {}),
                    **({'upstream_request': upstream_trace} if upstream_trace else {}),
                    **({'error_type': type(connection_error).__name__,
                        'errno': getattr(connection_error, 'errno', None)} if connection_error else {})})
                self.send_response(status)
                self.send_header('X-Request-ID', request_id)
                self.end_headers()
                self.wfile.write(body.encode())
                return
            with log.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                    'pid': os.getpid(), 'status': status, 'detail': detail or body,
                    **({'error_type': error_type, 'configuration': configuration} if error_type else {})}) + '\n')
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
            handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                'pid': os.getpid(), 'error': 'bind_failed',
                'errno': exc.errno, 'port': port}) + '\n')
        raise
    with server:
        if runtime_config is not None:
            emit({'event': 'service_started', 'listen_port': port, 'configuration': loaded,
                'upstream': {'host': '127.0.0.1', 'port': downstream}})
        if stop_file is not None:
            def watch_stop_request():
                while True:
                    if stop_file.exists():
                        with log.open('a', encoding='utf-8') as handle:
                            handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                                'pid': os.getpid(), 'event': 'shutdown_requested',
                                'reason': 'controlled_stop',
                                'stop_request': {'channel': 'file_presence',
                                    'path': str(stop_file.resolve()),
                                    'mtime_ns': stop_file.stat().st_mtime_ns,
                                    'initiator': 'unknown'}}) + '\n')
                        server.shutdown()
                        return
                    time.sleep(0.05)
            threading.Thread(target=watch_stop_request, daemon=True).start()
        server.serve_forever(poll_interval=0.1)
    if runtime_config is not None:
        emit({'event': 'service_exited', 'reason': 'shutdown_completed'})


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


def cleanup_owned(processes, ports):
    errors = []
    for process in reversed(processes):
        try:
            stop(process)
        except Exception as exc:
            errors.append({'type': 'cleanup', 'error_type': type(exc).__name__, 'pid': process.pid})
    try:
        listeners = listening_rows(ports)
    except Exception as exc:
        listeners = None
        errors.append({'type': 'cleanup_listener_check', 'error_type': type(exc).__name__})
    return {'owned_processes_stopped': all(proc.poll() is not None for proc in processes),
        'remaining_listeners': listeners, 'ports_released': listeners == [], 'cleanup_errors': errors}


def verify_case_state(out, case, app, dep, app_port, dep_port, log, blocker=None, edge=None, edge_port=None):
    """Controller-only observations; never supplied as Agent evidence or answers."""
    expected = {'normal': (200, 200), 'downstream_unreachable': (503, None),
        'application_error': (500, 200), 'application_exit': (None, 200),
        'port_conflict': (200, 200), 'missing_evidence': (500, 200),
        'application_config_error': (503, 200)}
    if case not in expected:
        raise ValueError('unknown controller case')
    snapshot = {'case': case, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'source': 'controller_direct_checks', 'agent_evidence': False, 'checks': {}}
    for name, port in [('app', app_port), ('downstream', dep_port)]:
        try:
            status, body = get_local(port)
            snapshot[name] = {'http_status': status, 'body': body}
        except (URLError, OSError) as exc:
            snapshot[name] = {'http_status': None, 'error_type': type(exc).__name__}
    rows = listening_rows([app_port, dep_port])
    snapshot['listeners'] = rows
    snapshot['app_exit_code'], snapshot['downstream_exit_code'] = app.poll(), dep.poll()
    checks = snapshot['checks']
    app_status, dep_status = expected[case]
    checks['http_states'] = (snapshot['app']['http_status'], snapshot['downstream']['http_status']) == (app_status, dep_status)
    if edge_port is not None:
        try:
            status, body = get_local(edge_port, path='/api/availability')
            snapshot['edge'] = {'http_status': status, 'body': body}
        except (URLError, OSError) as exc:
            snapshot['edge'] = {'http_status': None, 'error_type': type(exc).__name__}
        # The entry service forwards the application status; a stopped application
        # surfaces as an unavailable entry response.
        edge_expected = app_status if app_status is not None else 503
        checks['edge_http'] = snapshot['edge']['http_status'] == edge_expected
        checks['edge_process'] = edge.poll() is None
    checks['app_process'] = (app.poll() is not None) == (case in {'application_exit', 'port_conflict'})
    checks['downstream_process'] = (dep.poll() is not None) == (case == 'downstream_unreachable')
    for name, process, port, absent in [('app', blocker if case == 'port_conflict' else app, app_port,
            case == 'application_exit'), ('downstream', dep, dep_port, case == 'downstream_unreachable')]:
        owners = {row['pid'] for row in rows if row['port'] == port}
        if absent:
            checks[name + '_listener'] = not owners
        else:
            owned = set()
            if process is not None and process.poll() is None:
                try:
                    owned = {process.pid} | {p.pid for p in psutil.Process(process.pid).children(recursive=True)}
                except psutil.NoSuchProcess:
                    pass
            checks[name + '_listener'] = bool(owners) and owners <= owned
    if case == 'port_conflict':
        checks['bind_failure'] = app.poll() not in (None, 0) and 'bind_failed' in log.read_text(encoding='utf-8')
    if case in {'downstream_unreachable', 'application_config_error'}:
        checks['generic_response'] = snapshot['app'].get('body') == 'temporarily unavailable'
        entries = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        app_owners = {row['pid'] for row in rows if row['port'] == app_port}
        details = [row for row in entries if row.get('pid') in app_owners and row.get('status') == 503]
        checks['application_log'] = any(row.get('detail') == ('upstream connection failed'
            if case == 'downstream_unreachable' else 'invalid max_attempts configuration')
            and (case != 'application_config_error' or row.get('error_type') == 'ValueError') for row in details)
    snapshot['passed'] = all(checks.values())
    path = Path(out) / 'controller-observations.jsonl'
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + '\n')
    if not snapshot['passed']:
        raise RuntimeError('controller state verification failed: ' + case)
    return snapshot


async def evaluate_model_case(out, case, launch, previous_cost=None, knowledge_url=None, knowledge_disabled=False, mechanism_group=None, budget_limit_cny=5, run_budget_cny=None, observation_not_before=None, allow_unpriced_model=False, max_model_requests=None, max_output_tokens=4096, isolate_history=False, run_max_model_requests=None, symptom_profile='neutral'):
    """Only the caller's explicit paid mode may invoke this serial runner."""
    import hashlib
    from scripts.evaluate_windows_probe import read_cost_ledger, MECHANISM_GROUPS
    sample_id = uuid.uuid4().hex
    result_dir = out / ('model-' + sample_id)
    symptom_file = out / ('symptom-' + sample_id + '.txt')
    symptom_file.write_text(symptom_text(symptom_profile), encoding='utf-8')
    symptom_sha256 = hashlib.sha256(symptom_file.read_bytes()).hexdigest()
    args = [str(ROOT / 'scripts/evaluate_windows_probe.py'), '--run-model',
        '--probe-config', str(out / 'config.toml'), '--symptom-file', str(symptom_file),
        '--output-dir', str(result_dir), '--local-runbooks', str(out / 'runbooks'),
        '--max-output-tokens', str(max_output_tokens)]
    if allow_unpriced_model:
        args += ['--allow-unpriced-model']
    if max_model_requests is not None:
        args += ['--max-model-requests', str(max_model_requests)]
    if run_max_model_requests is not None:
        args += ['--run-max-model-requests', str(run_max_model_requests)]
    before = read_cost_ledger(previous_cost, for_resume=True, limit_cny=budget_limit_cny) if previous_cost else None
    args += ['--budget-limit-cny', str(budget_limit_cny)]
    if run_budget_cny is not None:
        args += ['--run-budget-cny', str(run_budget_cny)]
    if isolate_history or run_budget_cny is not None:
        args += ['--isolate-history']
    if observation_not_before is not None:
        args += ['--observation-not-before', observation_not_before]
    if mechanism_group is not None:
        if mechanism_group not in MECHANISM_GROUPS:
            raise ValueError('unknown mechanism group')
        if knowledge_disabled:
            raise ValueError('mechanism groups require unchanged knowledge conditions')
        args += ['--mechanism-group', mechanism_group]
    if knowledge_url:
        args += ['--knowledge-mcp-url', knowledge_url]
    if knowledge_disabled:
        args += ['--knowledge-disabled']
    if case == 'missing_evidence':
        args += ['--limited-evidence']
    if before is not None:
        args += ['--previous-cost', str(previous_cost)]
    manifest = out / 'knowledge-manifest.json'
    knowledge_baseline = None
    if manifest.exists() and not knowledge_disabled:
        from scripts.knowledge_conditions import check_knowledge_conditions
        knowledge_baseline = check_knowledge_conditions(manifest, out / 'runbooks', out, knowledge_url, 'controller-before-' + sample_id)
        args += ['--knowledge-manifest', str(manifest)]
    from scripts.evaluation_record import utc_now
    started = time.perf_counter()
    attempt = {'sample_id': sample_id, 'case': case, 'mechanism_group': mechanism_group,
        'result_dir': str(result_dir), 'started_at': utc_now(), 'ended_at': None,
        'elapsed_ms': None, 'exit_code': None, 'status': 'started',
        'timing_scope': 'controller child launch through wait; excludes fault injection, review and recovery'}
    attempt_file = out / ('model-attempt-' + sample_id + '.json')
    def save_attempt():
        attempt_file.write_text(json.dumps(attempt, ensure_ascii=False, indent=2), encoding='utf-8')
    save_attempt()
    try:
        process = launch(args, 'model-' + case)
        code = await asyncio.to_thread(process.wait)
        attempt.update(exit_code=code, status='returned' if code == 0 else 'failed')
    except BaseException as exc:
        attempt.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        attempt.update(ended_at=utc_now(), elapsed_ms=(time.perf_counter() - started) * 1000)
        save_attempt()
    if code != 0:
        raise RuntimeError('model scenario process failed: ' + case)
    summary = json.loads((result_dir / 'summary.json').read_text(encoding='utf-8'))
    if knowledge_baseline:
        knowledge_audit = summary.get('knowledge_conditions') or {}
        if (knowledge_audit.get('passed') is not True or knowledge_audit.get('phase') != 'after'
                or knowledge_audit.get('actual_sha256') != knowledge_baseline['actual_sha256']
                or knowledge_audit.get('endpoint') != knowledge_url):
            raise RuntimeError('model scenario knowledge conditions audit failed')
    if mechanism_group is not None:
        audit = summary.get('mechanism_audit') or {}
        config = audit.get('actual_config') or {}
        if (summary.get('mechanism_group') != mechanism_group or audit.get('passed') is not True
                or config != audit.get('expected_config')
                or (config.get('hypothesis_protection'), config.get('contradiction_trigger')) != MECHANISM_GROUPS[mechanism_group]):
            raise RuntimeError('model scenario mechanism audit failed')
    cost = read_cost_ledger(result_dir / 'cost.json')
    if cost['limit_cny'] != budget_limit_cny:
        raise ValueError('model scenario did not preserve requested budget limit')
    if before is not None and cost['requests'][:len(before['requests'])] != before['requests']:
        raise ValueError('model scenario did not preserve prior cost ledger')
    if (summary.get('budget_stopped') or summary.get('execution_error') or summary.get('error_events')
            or summary.get('investigation_failure') or summary.get('workflow_completed') is False
            or not summary.get('has_final_report') or summary.get('report_kind') not in {
                'unlocated', 'healthy_within_checked_scope', 'root_cause_reported',
                'confirmed_cause', 'localized_fault', 'healthy_within_scope'}):
        raise RuntimeError('model scenario incomplete or failed: ' + case)
    from scripts.evaluate_autonomous_investigation import model_usage_known
    if (len(cost['requests']) <= len((before or {}).get('requests', []))
            or any(not model_usage_known(row) for row in cost['requests'])):
        raise RuntimeError('model scenario has uncertain cost; stopping')
    from scripts.evaluation_record import audit_evaluation
    integrity = audit_evaluation(result_dir, expected_root=ROOT, previous=before)
    (result_dir / 'record-integrity.json').write_text(json.dumps(integrity, ensure_ascii=False, indent=2), encoding='utf-8')
    if not integrity['passed']:
        raise RuntimeError('model scenario record integrity failed; artifacts preserved')
    if integrity.get('comparison_config', {}).get('symptom_sha256') != symptom_sha256:
        raise ValueError('model scenario symptom input was not bound to evaluation record')
    if (((isolate_history or run_budget_cny is not None)
            and integrity.get('comparison_config', {}).get('shared_history_enabled') is not False)
            or (observation_not_before is not None
            and integrity.get('observation_not_before') != observation_not_before)):
        raise RuntimeError('model scenario did not preserve observation isolation')
    checks = review_model_artifacts(result_dir, case, summary)
    (result_dir / 'mechanical-review.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    workflow_completed = checks['workflow_status'] == 'completed'
    return {'case': 'real_model_workflow_' + case,
        'status': 'passed' if checks['passed'] and workflow_completed else 'failed',
        'workflow_completed': workflow_completed, 'diagnostic_correctness_verified': False,
        'requires_manual_review': True, 'report_kind': summary['report_kind'],
        'cumulative_requests': len(cost['requests']), 'reserved_cny': cost['reserved_cny'],
        'cost_file': str(result_dir / 'cost.json'), 'sample_id': sample_id,
        'knowledge_enabled': not knowledge_disabled, 'diagnosis': summary.get('diagnosis'),
        'knowledge_conditions': summary.get('knowledge_conditions'),
        'mechanism_group': mechanism_group, 'mechanism_audit': summary.get('mechanism_audit'),
        'record_integrity': integrity, 'this_run_cost': integrity['this_run_cost'],
        'manual_verdict': 'pending', 'mechanical_review': checks, 'result_dir': str(result_dir)}


def review_model_artifacts(directory, case, summary, *, events=None, trace=None):
    """Mechanical gates only; a human must judge causal meaning independently."""
    from src.probe.protocol import redact
    directory = Path(directory)
    if events is None:
        events = json.loads((directory / 'events.json').read_text(encoding='utf-8')) if (directory / 'events.json').exists() else []
    if trace is None:
        trace = json.loads((directory / 'tool_trace.json').read_text(encoding='utf-8')) if (directory / 'tool_trace.json').exists() else []
    ids = {row.get('evidence_id') for row in events if row.get('type') == 'evidence'}
    diagnosis = summary.get('diagnosis') or {}
    citations = diagnosis.get('evidence', [])
    recommendations = diagnosis.get('recommendations', [])
    advice_citations = [ref for item in recommendations for ref in item.get('evidence', [])]
    all_citations = citations + advice_citations
    expected = {'normal': ['healthy_within_scope'],
        'downstream_unreachable': ['localized_fault', 'confirmed_cause'],
        'application_error': ['localized_fault'], 'application_config_error': ['localized_fault'],
        'application_exit': ['localized_fault'],
        'port_conflict': ['localized_fault', 'confirmed_cause'], 'missing_evidence': ['unlocated', 'localized_fault']}
    allowed = {'probe_inventory', 'probe_resource_snapshot', 'probe_service_status', 'probe_process_snapshot',
        'probe_port_snapshot', 'probe_event_log', 'probe_text_log', 'probe_config_snapshot', 'probe_dependency_probe',
        'probe_list_evidence', 'search_knowledge_base', 'read_run_evidence'}
    # Model citations are produced from the persisted, redacted evidence view.
    # The tool trace contains a serialized transport representation instead;
    # nested JSON (especially text-log lines) can therefore differ in escaping
    # even when the citation is valid.  Prefer the evidence ledger and keep a
    # trace fallback for older/offline fixtures that do not have a database.
    evidence_text = _load_review_evidence_text(directory, all_citations)
    legacy_trace = not (directory / 'runs.sqlite').exists()
    if legacy_trace:
        evidence_text = {
            c.get('evidence_id'): json.dumps(redact(row.get('result')), ensure_ascii=False)
            for row in trace if row.get('validated_live_evidence')
            for c in all_citations if c.get('evidence_id') == row.get('evidence_id')
        }
    def quotes_observed(refs):
        return all(
            c.get('quote') and (
                (c.get('evidence_id') in evidence_text
                 and _citation_in_evidence(c['quote'], evidence_text[c['evidence_id']]))
            )
            for c in refs
        )
    gates = {'structured_result': diagnosis.get('version') == 1,
        'correct_target': diagnosis.get('target_id') == 'windows-local-01',
        'current_run_ids': all(c.get('evidence_id') in ids for c in citations),
        'quotes_observed': quotes_observed(citations),
        'recommendation_ids': all(c.get('evidence_id') in ids for c in advice_citations),
        'recommendation_quotes': quotes_observed(advice_citations),
        'recommendation_structure': all(
            item.get('status') == 'manual_review_required' and bool(item.get('scope'))
            and isinstance(item.get('action'), str) and bool(item['action'].strip())
            and bool(item.get('evidence'))
            and all(isinstance(item.get(key), list) and bool(item[key])
                    and all(isinstance(text, str) and bool(text.strip()) for text in item[key])
                    for key in ('preconditions', 'risks', 'verification_steps'))
            for item in recommendations),
        'no_unapproved_tool': bool(trace) and all(row.get('tool') in allowed for row in trace),
        'has_live_observation': any(row.get('validated_live_evidence') for row in trace),
        'evidence_for_assertion': diagnosis.get('kind') == 'unlocated' or bool(citations)}
    report = summary.get('report_generation')
    if report is not None or summary.get('report_model_enabled') is True:
        gates['report_generation'] = (isinstance(report, dict) and report.get('status') == 'ready')
    mechanical_passed = all(gates.values())
    level_matches = diagnosis.get('kind') in expected[case]
    completed = (summary.get('has_final_report') is True
        and summary.get('workflow_completed') is not False
        and not any(summary.get(key) for key in ('budget_stopped', 'execution_error', 'error_events', 'investigation_failure'))
        and not any(event.get('investigation_failure') for event in events)
        and not any(event.get('type') == 'error' for event in events)
        and any(event.get('type') == 'complete' and bool(str(event.get('response') or '').strip())
                for event in events))
    return {'passed': mechanical_passed, 'gates': gates,
        'report_generation_status': report.get('status', 'unknown') if isinstance(report, dict) else 'unknown',
        'mechanical_status': 'passed' if mechanical_passed else 'failed',
        'workflow_status': 'completed' if completed else 'incomplete',
        'result_level_status': 'passed' if level_matches else 'failed',
        'semantic_status': 'pending_manual_review', 'capability_passed': False,
        'capability_explanation': '待人工语义审核；capability_passed=false 表示尚未完成能力验收，不表示已证明诊断失败。流程、结果层与机械审核分别查看对应状态。',
        'recommendation_status': 'pending_manual_review' if recommendations else 'not_provided',
        'expected_result_levels': expected[case], 'level_matches_scenario': level_matches,
        'manual_verdict': 'pending', 'allowed_manual_verdicts': ['correct_localization', 'correct_healthy_within_scope', 'honest_unlocated', 'wrong_cause_or_false_positive', 'incomplete'],
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


async def evaluate_blind_cases(out, launch, set_case, knowledge_url=None, suite=None, previous_cost=None, mechanism_group=None, budget_limit_cny=5, run_budget_cny=None, allow_unpriced_model=False, max_model_requests=None, run_max_model_requests=None, max_output_tokens=4096, symptom_profile='neutral', after_case=None):
    """Controller keeps the scenario order outside the investigation context."""
    order = list(suite or ['normal', 'downstream_unreachable'])
    secrets.SystemRandom().shuffle(order)
    results, previous = [], previous_cost
    controller = {'results': results, 'injections': [], 'recovery': 'pending',
        'answer_visibility': 'not_in_model_context_or_probe_allowlist'}
    try:
        for case in order:
            observation_boundary = datetime.now(timezone.utc).isoformat()
            await set_case(case)
            controller['injections'].append({'case': case, 'injected_at': datetime.now(timezone.utc).isoformat(),
                'observation_not_before': observation_boundary})
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
            options = {'isolate_history': True, 'observation_not_before': observation_boundary}
            if mechanism_group is not None:
                options['mechanism_group'] = mechanism_group
            if (allow_unpriced_model or max_model_requests is not None
                    or run_max_model_requests is not None or max_output_tokens != 4096):
                options.update(allow_unpriced_model=allow_unpriced_model, max_model_requests=max_model_requests,
                    run_max_model_requests=run_max_model_requests, max_output_tokens=max_output_tokens)
            if budget_limit_cny != 5:
                options['budget_limit_cny'] = budget_limit_cny
            if run_budget_cny is not None:
                options['run_budget_cny'] = run_budget_cny
            if symptom_profile != 'neutral':
                options['symptom_profile'] = symptom_profile
            result = await evaluate_model_case(out, case, launch, previous, knowledge_url=knowledge_url, **options)
            results.append(result)
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
            if result.get('status') != 'passed' or result.get('workflow_completed') is not True:
                raise RuntimeError('blind model child failed mechanical gates')
            previous = Path(result['cost_file'])
            if after_case is not None:
                await after_case(result)
    except Exception as exc:
        controller['failure'] = {'case': case, 'status': 'incomplete', 'exception_type': type(exc).__name__,
            'failed_at': datetime.now(timezone.utc).isoformat()}
        raise
    finally:
        try:
            await set_case('normal')
            controller['recovery'] = 'normal_restored'
        except Exception as exc:
            controller['recovery'] = 'failed'
            controller['recovery_error'] = type(exc).__name__
            raise
        finally:
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


async def await_manual_config_repair(out, result, mode_file, app_port, dep_port, wait_seconds):
    """Observe an external edit before cleanup; never edit configuration or infer a human actor."""
    path = out / 'manual-repair.json'
    initial = mode_file.read_bytes()
    record = {'status': 'awaiting_manual_action', 'config_path': str(mode_file.resolve()),
        'report_path': str(Path(result['result_dir']) / 'report.txt'),
        'entry_url': f'http://127.0.0.1:{app_port}/health',
        'downstream_url': f'http://127.0.0.1:{dep_port}/health',
        'started_at': datetime.now(timezone.utc).isoformat(), 'wait_seconds': wait_seconds,
        'initial_sha256': hashlib.sha256(initial).hexdigest(),
        'human_confirmation': None, 'controller_repair_performed': False,
        'business_retest': None}
    def save():
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            current = mode_file.read_bytes()
            if current != initial:
                parsed = json.loads(current.decode('utf-8-sig'))
                value = parsed.get('max_attempts')
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    raise ValueError('not an integer configuration')
                int(value)
                downstream = await asyncio.to_thread(get_local, dep_port)
                entry = await asyncio.to_thread(get_local, app_port)
                record.update(status='external_edit_retested',
                    observed_sha256=hashlib.sha256(current).hexdigest(),
                    business_retest={'downstream': {'status': downstream[0], 'body': downstream[1]},
                        'entry': {'status': entry[0], 'body': entry[1]},
                        'passed': downstream == entry == (200, 'healthy')})
                save()
                if record['business_retest']['passed']:
                    break
        except (ValueError, OSError, URLError) as exc:
            record['last_observation_error'] = type(exc).__name__
        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
    else:
        record['status'] = 'pending_manual_acceptance_timeout'
    record['ended_at'] = datetime.now(timezone.utc).isoformat()
    save()
    return record


async def evaluate_four_groups(out, launch, set_case, knowledge_url, previous_cost, budget_limit_cny, run_budget_cny, suite='baseline-v1', *, allow_unpriced_model=False, max_model_requests=None, run_max_model_requests=None, max_output_tokens=4096, symptom_profile='neutral', selected_order=None):
    """Same controller-owned environment, serial fresh children; no implicit paid entry."""
    import hashlib
    import math
    from scripts.evaluate_windows_probe import read_cost_ledger
    from scripts.evaluation_record import utc_now
    if not allow_unpriced_model and run_max_model_requests is None and (type(run_budget_cny) not in (int, float) or not math.isfinite(run_budget_cny) or run_budget_cny <= 0):
        raise ValueError('four groups require a positive per-run reservation cap')
    for cap in (max_model_requests, run_max_model_requests):
        if cap is not None and (type(cap) is not int or cap <= 0):
            raise ValueError('request caps must be positive integers')
    if allow_unpriced_model and (max_model_requests is None or run_max_model_requests is None):
        raise ValueError('unpriced four groups require cumulative and per-run request caps')
    if (max_model_requests is None) != (run_max_model_requests is None):
        raise ValueError('four-group request limits require both cumulative and per-run caps')
    previous = read_cost_ledger(previous_cost, for_resume=True, limit_cny=budget_limit_cny)
    cases = four_group_cases(suite)
    symptom_sha256 = hashlib.sha256(symptom_text(symptom_profile).encode('utf-8')).hexdigest()
    if run_budget_cny is not None and (type(run_budget_cny) not in (int, float)
            or not math.isfinite(run_budget_cny) or run_budget_cny <= 0):
        raise ValueError('invalid per-run reservation cap')
    full_order = four_group_order(suite)
    order = full_order if selected_order is None else selected_order
    allowed = {(item['case'], item['group']) for item in full_order}
    keys = [(item.get('case'), item.get('group')) for item in order]
    if not order or any(key not in allowed for key in keys) or len(set(keys)) != len(keys):
        raise ValueError('four-group selected order must contain unique slots from the suite')
    if run_budget_cny is not None and budget_limit_cny - previous['reserved_cny'] < len(order) * run_budget_cny:
        raise RuntimeError('insufficient cumulative allowance for equal four-group caps')
    if run_max_model_requests is not None and (max_model_requests is None
            or max_model_requests - len(previous['requests']) < len(order) * run_max_model_requests):
        raise RuntimeError('insufficient cumulative requests for equal four-group caps')
    def conditions():
        return four_group_conditions(out)
    fixed = conditions()
    record = {'version': 4, 'suite': suite, 'scenario_cases': list(cases),
        'order': order, 'conditions_sha256': fixed, 'results': [],
        'started_at': utc_now(), 'ended_at': None, 'recovery': 'pending', 'status': 'started',
        'scheduled_slot_count': len(order), 'suite_slot_count': len(full_order),
        'suite_complete': len(order) == len(full_order),
        'run_budget_cny': run_budget_cny, 'budget_limit_cny': budget_limit_cny,
        'allow_unpriced_model': allow_unpriced_model, 'max_model_requests': max_model_requests,
        'run_max_model_requests': run_max_model_requests, 'max_output_tokens': max_output_tokens,
        'symptom_profile': symptom_profile, 'symptom_sha256': symptom_sha256,
        'previous_cost': str(Path(previous_cost).resolve()), 'inherited_requests': len(previous['requests']),
        'answer_visibility': 'controller only; neutral symptom and fixed Probe allowlist', 'resets': []}
    path = out / 'four-group-controller.json'
    def save():
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    directories, threads, baseline = set(), set(), None
    previous_path = previous_cost
    try:
        for item in order:
            if conditions() != fixed:
                raise ValueError('shared configuration or knowledge changed')
            observation_boundary = utc_now()
            await set_case('normal')
            await set_case(item['case'])
            record['resets'].append({**item, 'verified_at': utc_now(),
                'observation_not_before': observation_boundary})
            save()
            if conditions() != fixed:
                raise ValueError('reset changed shared configuration or knowledge')
            options = {}
            if allow_unpriced_model or max_model_requests is not None or run_max_model_requests is not None:
                options.update(allow_unpriced_model=allow_unpriced_model, max_model_requests=max_model_requests,
                    run_max_model_requests=run_max_model_requests, max_output_tokens=max_output_tokens,
                    isolate_history=True)
            elif max_output_tokens != 4096:
                options['max_output_tokens'] = max_output_tokens
            result = await evaluate_model_case(out, item['case'], launch, previous_path,
                knowledge_url=knowledge_url, mechanism_group=item['group'],
                budget_limit_cny=budget_limit_cny, run_budget_cny=run_budget_cny,
                observation_not_before=observation_boundary, symptom_profile=symptom_profile, **options)
            record['results'].append(result)
            save()
            if result.get('status') != 'passed' or result.get('workflow_completed') is not True:
                raise RuntimeError('four-group child failed mechanical gates')
            directory = Path(result['result_dir']).resolve()
            if directory in directories or not directory.is_relative_to(out.resolve()):
                raise ValueError('four-group child state directory reused or outside output')
            directories.add(directory)
            for name in ('runs.sqlite', 'checkpoints.sqlite'):
                if not (directory / name).is_file():
                    raise ValueError('four-group child missing isolated state database')
            trace = json.loads((directory / 'mechanism_trace.json').read_text(encoding='utf-8'))
            thread = trace.get('thread_id')
            if not thread or thread in threads:
                raise ValueError('four-group thread missing or reused')
            threads.add(thread)
            integrity = result['record_integrity']
            if len(integrity.get('comparison_config', {}).get('model_channels', [])) > 1:
                raise ValueError('four-group child mixed model channels; artifacts preserved')
            if options and any(integrity['comparison_config'].get(key) != value
                    for key, value in options.items() if key != 'isolate_history'):
                raise ValueError('four-group child request limits or pricing mode differ')
            if (integrity['comparison_config'].get('run_budget_cny') != run_budget_cny
                    or integrity['comparison_config'].get('shared_history_enabled') is not False
                    or integrity['comparison_config'].get('symptom_sha256') != symptom_sha256
                    or integrity.get('observation_not_before') != observation_boundary):
                raise ValueError('four-group child did not preserve per-run cap, symptom input or history isolation')
            signature = (integrity['source_signature'], integrity['comparison_config'])
            if not integrity['passed'] or (baseline is not None and signature != baseline):
                raise ValueError('four-group runtime source or fixed conditions differ')
            baseline = signature
            if conditions() != fixed:
                raise ValueError('shared conditions changed during child execution')
            previous_path = Path(result['cost_file'])
        record['status'] = 'completed'
    except BaseException as exc:
        record.update(status='failed', failure={'type': type(exc).__name__, 'at': utc_now()})
        raise
    finally:
        try:
            await set_case('normal')
            record['recovery'] = 'normal_restored'
        except BaseException as exc:
            record.update(status='failed', recovery='failed', recovery_error=type(exc).__name__)
            raise
        finally:
            record['ended_at'] = utc_now()
            save()
    return record['results']


async def preflight_four_group_scenarios(out, tools, target, log, set_case, suite):
    """Exercise the paid schedule's real resets and Probe windows, without decisions."""
    from scripts.verify_probe_observation_boundary import verify_boundary_rounds
    from scripts.evaluation_record import utc_now
    order = four_group_order(suite)
    fixed = four_group_conditions(out)
    report = {'suite': suite, 'order': order, 'conditions_sha256': fixed,
        'started_at': utc_now(), 'status': 'started', 'recovery': 'pending',
        'model_calls': 0, 'group_labels_only': True, 'mechanism_effectiveness_verified': False}
    path = out / 'four-group-scenario-preflight.json'
    lifecycle_observations = []

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    async def reset(case):
        if four_group_conditions(out) != fixed:
            raise ValueError('shared configuration or knowledge changed')
        await set_case('normal')
        snapshot = await set_case(case)
        if case == 'downstream_unreachable':
            from src.probe.evidence import validate_tool_evidence
            raw = await tools['probe_text_log'].ainvoke({
                'service': 'downstream', 'path': str(out / 'downstream.log'), 'lines': 100})
            item = validate_tool_evidence(raw, tool_name='probe_text_log', target_id=target)
            events = [json.loads(line) for line in item['payload'].get('lines', [])]
            if not any(event.get('event') == 'shutdown_requested'
                    and event.get('reason') == 'controlled_stop' for event in events):
                raise RuntimeError('Probe could not read the downstream shutdown lifecycle event')
            lifecycle_observations.append({'case': case, 'raw_hash': item.get('raw_hash')})
        if four_group_conditions(out) != fixed:
            raise ValueError('reset changed shared configuration or knowledge')
        return snapshot

    save()
    try:
        result = await verify_boundary_rounds(tools, target, out / 'scenario-windows', log, reset,
            scenarios=[item['case'] for item in order])
        report.update(status='passed', observations=result['evidence_count'], rounds=result['rounds'],
            lifecycle_observations=lifecycle_observations)
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        try:
            snapshot = await set_case('normal')
            if not snapshot or snapshot.get('case') != 'normal' or snapshot.get('passed') is not True:
                raise RuntimeError('normal recovery not independently verified')
            report.update(recovery='normal_restored', recovery_state=snapshot)
        except BaseException as exc:
            report.update(status='failed', recovery='failed', recovery_error=type(exc).__name__)
            raise
        finally:
            report['ended_at'] = utc_now()
            save()
    return {'case': 'four_group_scenario_preflight', 'status': report['status'], 'suite': suite,
        'rounds': report['rounds'], 'evidence_count': report['observations'],
        'lifecycle_observations': len(lifecycle_observations), 'model_calls': 0,
        'autonomous_model_investigation': False, 'mechanism_effectiveness_verified': False}


async def verify(out, evaluation_preflight=False, run_model=False, model_stage='smoke', previous_cost=None, mechanism_group=None, budget_limit_cny=5, run_budget_cny=None, allow_unpriced_model=False, max_model_requests=None, max_output_tokens=4096, smoke_case=None, four_group_suite='baseline-v1', scenario_preflight=False, run_max_model_requests=None, symptom_profile='neutral', four_group_slots=None, manual_repair_wait_seconds=0):
    four_group_cases(four_group_suite)
    if scenario_preflight and (run_model or evaluation_preflight):
        raise ValueError('scenario preflight is a separate free mode')
    from scripts.windows_probe import _set_acl
    from src.probe.evidence import validate_tool_evidence
    from langchain_mcp_adapters.client import MultiServerMCPClient

    target, token = 'windows-local-01', uuid.uuid4().hex + uuid.uuid4().hex
    ports = []
    while len(ports) < 5:
        candidate = free_port()
        if candidate not in ports:
            ports.append(candidate)
    gateway_port, edge_port, app_port, dep_port, knowledge_port = ports
    out.mkdir(parents=True, exist_ok=False)
    if os.name == 'nt':
        _set_acl(out)
    shutil.copytree(ROOT / 'docs/fixtures/windows-local-runbooks', out / 'runbooks')
    from scripts.knowledge_conditions import knowledge_conditions
    (out / 'knowledge-manifest.json').write_text(json.dumps(knowledge_conditions(out / 'runbooks'),
        ensure_ascii=False, indent=2), encoding='utf-8')
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
    dep_log = out / 'downstream.log'
    dep_log.touch()
    edge_log = out / 'edge.log'
    edge_log.touch()
    app_mode, dep_mode, edge_mode = out / 'app.mode', out / 'downstream.mode', out / 'edge.mode'
    dep_config, edge_config = out / 'downstream.connection.json', out / 'edge.connection.json'

    def write_app_mode(**fields):
        # The localapp startup connection file doubles as its mode file, so the
        # loaded configuration hash and the injected mode can never diverge.
        app_mode.write_text(json.dumps({'max_attempts': 3, 'downstream_port': dep_port,
            'upstream_timeout_seconds': 0.5, **fields}), encoding='utf-8')

    write_app_mode()
    dep_mode.write_text('normal', encoding='utf-8')
    edge_mode.write_text('normal', encoding='utf-8')
    dep_config.write_text(json.dumps({'downstream_port': None, 'upstream_timeout_seconds': 0.5}),
        encoding='utf-8')
    # The entry service waits longer than the application's own upstream timeout so
    # the forwarded request finishes after the application logged its failure; an
    # equal timeout lets the entry give up first and the two logs stop agreeing on
    # which one happened first.
    edge_config.write_text(json.dumps({'downstream_port': app_port, 'upstream_timeout_seconds': 1.5}),
        encoding='utf-8')
    (out / 'config.toml').write_text('\n'.join([f"target_id = '{target}'",
        f"gateway_url = 'ws://127.0.0.1:{gateway_port}/probe/ws'",
        f"token_file = '{(out / 'token').as_posix()}'", 'baseline_interval_seconds = 60',
        '[services.edge]', "kind = 'process'",
        "process_names = ['python.exe']", f"text_logs = ['{edge_log.as_posix()}']",
        f"process_args = ['--mode-file', '{edge_mode}']",
        '[services.localapp]', "kind = 'process'",
        "process_names = ['python.exe']", f"text_logs = ['{log.as_posix()}']",
        f"config_file = '{app_mode.as_posix()}'", "config_keys = ['max_attempts', 'downstream_port']",
        f"process_args = ['--mode-file', '{app_mode}']",
        '[services.downstream]', "kind = 'process'", "process_names = ['python.exe']",
        f"process_args = ['--mode-file', '{dep_mode}']", f"text_logs = ['{dep_log.as_posix()}']",
        '[dependencies.edge]', "host = '127.0.0.1'", f'port = {edge_port}',
        "health_scheme = 'http'", "health_path = '/health'",
        '[dependencies.localapp]', "host = '127.0.0.1'", f'port = {app_port}',
        "health_scheme = 'http'", "health_path = '/health'",
        '[dependencies.downstream]', "host = '127.0.0.1'", f'port = {dep_port}',
        "health_scheme = 'http'", "health_path = '/health'"]), encoding='utf-8')
    owned, records, cases = [], [], []
    process_records, process_handles = [], []
    controller_stop_ids = set()
    report = {'ok': False, 'model_calls': None if run_model else 0, 'target_id': target, 'cases': cases,
        'probe_identity': 'temporary foreground current-account probe, not installed LocalService',
        'model_investigation': 'requested_not_started' if run_model else 'not_run', 'ports': ports, 'errors': []}
    with ExitStack() as stack:
        def launch(args, name):
            started_at = datetime.now(timezone.utc).isoformat()
            output_path = out / (name + '.stderr')
            command = [sys.executable, *args]
            lifecycle = {'name': name, 'command': command, 'cwd': str(ROOT),
                'output_file': str(output_path.relative_to(out)), 'started_at': started_at,
                'status': 'starting', 'pid': None, 'ended_at': None, 'exit_code': None}
            process_records.append(lifecycle)
            (out / 'process-lifecycle.json').write_text(
                json.dumps(process_records, ensure_ascii=False, indent=2), encoding='utf-8')
            handle = stack.enter_context(output_path.open('wb'))
            try:
                proc = subprocess.Popen(command, cwd=ROOT, env=env,
                    stdout=handle, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            except BaseException as exc:
                lifecycle.update(status='start_failed', ended_at=datetime.now(timezone.utc).isoformat(),
                    error_type=type(exc).__name__, error=str(exc)[:300])
                (out / 'process-lifecycle.json').write_text(
                    json.dumps(process_records, ensure_ascii=False, indent=2), encoding='utf-8')
                raise
            lifecycle.update(status='running', pid=proc.pid)
            process_handles.append((proc, lifecycle))
            owned.append(proc)
            (out / 'process-lifecycle.json').write_text(
                json.dumps(process_records, ensure_ascii=False, indent=2), encoding='utf-8')
            return proc

        process_stop_files = {}

        def stop_owned(proc, *, graceful=False):
            controller_stop_ids.add(id(proc))
            stop_file = process_stop_files.get(proc.pid) if graceful else None
            if stop_file is not None and proc.poll() is None:
                stop_file.touch()
                try:
                    proc.wait(timeout=5)
                    return
                except subprocess.TimeoutExpired:
                    pass
            stop(proc)

        def application(port, mode, name, dependency=None, runtime_config=None, log_path=None):
            app_log = log_path or (log if port == app_port else dep_log)
            args = [str(Path(__file__).resolve()), '--serve', str(port), '--log', str(app_log), '--mode-file', str(mode)]
            if dependency is not None:
                args += ['--downstream', str(dependency)]
            else:
                stop_file = out / (name + '.stop')
                stop_file.unlink(missing_ok=True)
                args += ['--stop-file', str(stop_file)]
            if runtime_config is not None:
                args += ['--runtime-config', str(runtime_config)]
            proc = launch(args, name)
            if dependency is None:
                process_stop_files[proc.pid] = stop_file
            wait_listener(port, proc)
            return proc

        probe = None
        try:
            dep = application(dep_port, dep_mode, 'downstream', runtime_config=dep_config)
            app = application(app_port, app_mode, 'application', dep_port, runtime_config=app_mode)
            edge = application(edge_port, edge_mode, 'edge', app_port, runtime_config=edge_config,
                log_path=edge_log)
            gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host', '127.0.0.1',
                '--port', str(gateway_port)], 'gateway')
            wait_listener(gateway_port, gateway)
            probe = launch(['-c', 'import asyncio; from pathlib import Path; from scripts.windows_probe import run_probe; '
                f'asyncio.run(run_probe(lambda: Path({str(out / "stop-probe")!r}).exists()))'], 'probe')
            client = MultiServerMCPClient({'probe': {'transport': 'streamable_http',
                'url': f'http://127.0.0.1:{gateway_port}/mcp', 'headers': {'Authorization': 'Bearer ' + token}}})
            tools = {tool.name: tool for tool in await client.get_tools()}
            from src.probe.evidence import PROBE_TOOL_OPERATIONS
            assert set(tools) == set(PROBE_TOOL_OPERATIONS) | {'probe_list_evidence'}
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
                    '--knowledge-mcp-url', knowledge_config['knowledge']['url'],
                    '--knowledge-manifest', str(out / 'knowledge-manifest.json')], 'evaluation-preflight-' + case)
                code = await asyncio.to_thread(process.wait, 45)
                assert code == 0, 'evaluation preflight failed: ' + case
                result = json.loads((result_dir / 'preflight.json').read_text(encoding='utf-8'))
                assert result['ok'] and result['model_calls'] == 0 and result['evidence_count'] == 7
                assert not (result_dir / 'cost.json').exists(), 'free preflight entered paid budget path'
                assert set(result['tool_names']) == set(PROBE_TOOL_OPERATIONS) | {'probe_list_evidence', 'search_knowledge_base'}
                assert result['knowledge_mcp']['transport'] == 'streamable_http_loopback'
                assert not result['knowledge_mcp']['autonomously_selected']
                tool_trace = json.loads((result_dir / 'tool_trace.json').read_text(encoding='utf-8'))
                assert len(tool_trace) == 8
                assert sum(row['validated_live_evidence'] for row in tool_trace) == 7
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
                nonlocal dep, app, edge, blocker
                log.write_text('', encoding='utf-8')
                dep_log.write_text('', encoding='utf-8')
                edge_log.write_text('', encoding='utf-8')
                if blocker and blocker.poll() is None:
                    stop_owned(blocker)
                blocker = None
                if app.poll() is None:
                    stop_owned(app)
                if dep.poll() is None:
                    stop_owned(dep, graceful=(case == 'downstream_unreachable'))
                if edge.poll() is None:
                    stop_owned(edge)
                if case == 'application_config_error':
                    write_app_mode(max_attempts='invalid')
                elif case in {'application_error', 'missing_evidence'}:
                    write_app_mode(mode='application_error')
                else:
                    write_app_mode()
                dep_mode.write_text('normal', encoding='utf-8')
                if case == 'downstream_unreachable':
                    # Start the dependency so its log carries the start identity, then
                    # stop it gracefully before any Probe observation so the stop is provable.
                    dep = application(dep_port, dep_mode, 'model-dependency-' + uuid.uuid4().hex,
                        runtime_config=dep_config)
                    stop_owned(dep, graceful=True)
                else:
                    dep = application(dep_port, dep_mode, 'model-dependency-' + uuid.uuid4().hex,
                        runtime_config=dep_config)
                if case == 'port_conflict':
                    blocker = application(app_port, dep_mode, 'model-owner-' + uuid.uuid4().hex)
                    app = launch([str(Path(__file__).resolve()), '--serve', str(app_port), '--log', str(log),
                        '--mode-file', str(app_mode), '--downstream', str(dep_port),
                        '--runtime-config', str(app_mode)], 'model-bind-' + uuid.uuid4().hex)
                    assert await asyncio.to_thread(app.wait, 5) != 0
                elif case != 'application_exit':
                    app = application(app_port, app_mode, 'model-app-' + uuid.uuid4().hex, dep_port,
                        runtime_config=app_mode)
                edge = application(edge_port, edge_mode, 'edge', app_port, runtime_config=edge_config,
                    log_path=edge_log)
                if case == 'downstream_unreachable':
                    status, _ = await asyncio.to_thread(get_local, edge_port, path='/api/availability',
                        request_id=uuid.uuid4().hex)
                    assert status == 503, 'stopped dependency did not fail the business entry'
                snapshot = verify_case_state(out, case, app, dep, app_port, dep_port, log, blocker,
                    edge=edge, edge_port=edge_port)
                return {**snapshot, 'app_pids': [row['pid'] for row in snapshot['listeners'] if row['port'] == app_port],
                    'downstream_pids': [row['pid'] for row in snapshot['listeners'] if row['port'] == dep_port]}
            if scenario_preflight:
                cases.append(await preflight_four_group_scenarios(out, tools, target, log, set_model_case, four_group_suite))
                report.update(ok=True, evidence_count=len(records),
                    scope='scenario resets and real Probe windows only; no Agent decisions or model calls')
                engine.dispose()
                return report  # The existing finally still cleans all owned processes and writes the result.
            if evaluation_preflight:
                from scripts.verify_probe_observation_boundary import verify_boundary_rounds
                cases.append(await verify_boundary_rounds(tools, target, out / 'observation-boundary', log, set_model_case,
                    scenarios=('normal', 'downstream_unreachable', 'application_error') * 4 + ('normal',)))
                matching_503 = {}
                for case in ['normal', 'downstream_unreachable', 'application_error',
                             'application_exit', 'port_conflict', 'missing_evidence', 'application_config_error']:
                    await set_model_case(case)
                    health = (await query('probe_dependency_probe', {'dependency': 'localapp'}, 'controller-' + case))['payload']
                    downstream = (await query('probe_dependency_probe', {'dependency': 'downstream'}, 'controller-' + case))['payload']
                    if case == 'application_exit':
                        assert health['tcp'] == 'failed' and downstream['http']['status'] == 200
                    else:
                        expected = {'normal': 200, 'downstream_unreachable': 503,
                                    'application_error': 500, 'port_conflict': 200, 'missing_evidence': 500,
                                    'application_config_error': 503}[case]
                        assert health['http']['status'] == expected
                    assert downstream['tcp'] == ('failed' if case == 'downstream_unreachable' else 'ok')
                    if case in {'downstream_unreachable', 'application_config_error'}:
                        logs = (await query('probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 100},
                            'controller-' + case))['payload']
                        entries = [json.loads(line) for line in logs['lines']]
                        if case == 'application_config_error':
                            snapshot = (await query('probe_config_snapshot', {'service': 'localapp'},
                                'controller-' + case))['payload']
                            assert snapshot['values']['max_attempts'] == 'invalid'
                            assert snapshot['values']['downstream_port'] == dep_port
                            assert snapshot['source_sha256'] == hashlib.sha256(app_mode.read_bytes()).hexdigest()
                            assert any(row.get('configuration', {}).get('source_sha256') == snapshot['source_sha256']
                                for row in entries)
                        expected_detail = ('upstream connection failed' if case == 'downstream_unreachable'
                            else 'invalid max_attempts configuration')
                        app_owners = {row['pid'] for row in listening_rows([app_port])}
                        assert any(row.get('pid') in app_owners and row.get('status') == 503
                            and row.get('detail') == expected_detail for row in entries)
                        matching_503[case] = {'entry': health, 'downstream': downstream, 'logs': logs,
                            'evidence_ids': [r['evidence_id'] for r in records if r['case'] == 'controller-' + case]}
                        (out / 'matching-503-observations.json').write_text(json.dumps(matching_503,
                            ensure_ascii=False, indent=2), encoding='utf-8')
                    if case == 'port_conflict':
                        rows = (await query('probe_port_snapshot', {'local_port': app_port, 'listening_only': True}, 'controller-' + case))['payload']['ports']
                        owner_pids = {blocker.pid} | {p.pid for p in psutil.Process(blocker.pid).children(recursive=True)}
                        assert any(row['pid'] in owner_pids for row in rows)
                        assert 'bind_failed' in log.read_text(encoding='utf-8')
                    cases.append({'case': 'controller_preflight_' + case, 'status': 'passed',
                                  'model_calls': 0, 'autonomous_model_investigation': False})
                await set_model_case('normal')
                assert get_local(app_port)[0] == get_local(dep_port)[0] == 200
                # The stopped-dependency direct cause must be derivable from this
                # fixture's own evidence.  This is the structural check behind the
                # widened result level: it proves the lifecycle chain is complete
                # before any paid round is spent trying to use it.
                await set_model_case('downstream_unreachable')
                from scripts.evaluate_windows_probe import business_catalog
                from src.probe.windows.config import load_config
                from src.agent.aiops.target_catalog import resolve_target
                from src.agent.aiops.strategies import investigation
                collected = [
                    ('inventory', await query('probe_inventory', {}, 'stopped-cause')),
                    ('downstream-log', await query('probe_text_log',
                        {'service': 'downstream', 'path': str(dep_log), 'lines': 100}, 'stopped-cause')),
                    ('edge-log', await query('probe_text_log',
                        {'service': 'edge', 'path': str(edge_log), 'lines': 100}, 'stopped-cause')),
                    ('app-log', await query('probe_text_log',
                        {'service': 'localapp', 'path': str(log), 'lines': 100}, 'stopped-cause')),
                    ('app-config', await query('probe_config_snapshot', {'service': 'localapp'}, 'stopped-cause')),
                    ('dependency', await query('probe_dependency_probe', {'dependency': 'downstream'}, 'stopped-cause')),
                    ('ports', await query('probe_port_snapshot',
                        {'local_port': dep_port, 'listening_only': True}, 'stopped-cause')),
                    ('processes', await query('probe_process_snapshot', {'service': 'downstream'}, 'stopped-cause'))]
                stopped_state = {'input': 'edge 业务入口不可用', 'autonomous_investigation': True,
                    'past_steps': [],
                    'raw_evidence': [(name, json.dumps(raw)) for name, raw in collected],
                    'target_resolution': resolve_target(business_catalog(load_config(out / 'config.toml')),
                        'edge', collected[0][1]['payload'], target),
                    'investigation_tools': [{'name': name} for name in tools],
                    'investigation_config': {'hypothesis_protection': False, 'contradiction_trigger': False}}
                assert stopped_state['target_resolution']['status'] == 'resolved', stopped_state['target_resolution']
                direct = investigation._direct_cause_evidence(
                    investigation.evidence_index(stopped_state), stopped_state)
                assert direct['downstream_stopped_after_request'], sorted(direct)
                (out / 'stopped-cause-evidence.json').write_text(json.dumps({
                    'direct_cause_evidence': {key: sorted(value) for key, value in direct.items()},
                    'evidence': [{'case': name, 'evidence_id': raw.get('raw_hash')} for name, raw in collected],
                    'model_calls': 0, 'fixed_decisions': True}, ensure_ascii=False, indent=2), encoding='utf-8')
                cases.append({'case': 'downstream_stopped_cause_derivable', 'status': 'passed',
                    'model_calls': 0, 'autonomous_model_investigation': False,
                    'cause_code': 'downstream_stopped_after_request'})
                await set_model_case('normal')
                left, right = matching_503['downstream_unreachable'], matching_503['application_config_error']
                assert left['entry']['http']['status'] == right['entry']['http']['status'] == 503
                assert left['entry']['http']['body_prefix'] == right['entry']['http']['body_prefix'] == 'temporarily unavailable'
                assert right['downstream']['http']['status'] == 200
                cases.append({'case': 'matching_503_distinguishable_by_live_evidence', 'status': 'passed',
                    'model_calls': 0, 'autonomous_model_investigation': False, 'recovery': 'independently_verified_normal'})
            if run_model:
                report['model_investigation'] = 'started_requires_manual_review'
                if model_stage == 'four-groups':
                    cases.extend(await evaluate_four_groups(out, launch, set_model_case,
                        knowledge_config['knowledge']['url'], previous_cost, budget_limit_cny, run_budget_cny,
                        suite=four_group_suite, allow_unpriced_model=allow_unpriced_model,
                        max_model_requests=max_model_requests, run_max_model_requests=run_max_model_requests,
                        max_output_tokens=max_output_tokens, symptom_profile=symptom_profile,
                        selected_order=four_group_slots))
                elif model_stage == 'knowledge-control':
                    previous = previous_cost
                    modes = [False, True]
                    secrets.SystemRandom().shuffle(modes)
                    for disabled in modes:
                        await set_model_case('downstream_unreachable')
                        result = await evaluate_model_case(out, 'downstream_unreachable', launch, previous,
                            knowledge_url=knowledge_config['knowledge']['url'], knowledge_disabled=disabled,
                            budget_limit_cny=budget_limit_cny)
                        cases.append(result)
                        previous = Path(result['cost_file'])
                    await set_model_case('normal')
                else:
                    suite = ['application_error', 'application_exit', 'port_conflict', 'missing_evidence'] if model_stage == 'extended' else ([smoke_case] if smoke_case else None)
                    async def manual_repair(result):
                        report['manual_repair'] = await await_manual_config_repair(
                            out, result, app_mode, app_port, dep_port, manual_repair_wait_seconds)
                    cases.extend(await evaluate_blind_cases(out, launch, set_model_case,
                        knowledge_url=knowledge_config['knowledge']['url'], suite=suite, previous_cost=previous_cost,
                        mechanism_group=mechanism_group, budget_limit_cny=budget_limit_cny,
                        run_budget_cny=run_budget_cny,
                        allow_unpriced_model=allow_unpriced_model, max_model_requests=max_model_requests,
                        run_max_model_requests=run_max_model_requests,
                        max_output_tokens=max_output_tokens, symptom_profile=symptom_profile,
                        after_case=manual_repair if manual_repair_wait_seconds else None))
            from scripts.verify_windows_probe_graph import verify_graph
            if evaluation_preflight and not run_model:
                from scripts.verify_probe_mechanisms import verify_mechanism_groups
                cases.append(await verify_mechanism_groups(tools, out, log, knowledge_tool,
                    knowledge_config['knowledge']['url'], set_model_case))
            cases.append(await verify_graph(tools, out, log, 'normal', knowledge_tool))
            process_snapshot = await query('probe_process_snapshot', {'service': 'localapp'}, 'normal')
            app_pids = {app.pid} | {p.pid for p in psutil.Process(app.pid).children(recursive=True)}
            assert app_pids & {row['pid'] for row in process_snapshot['payload']['processes']}
            dependency_snapshot = await query('probe_process_snapshot', {'service': 'downstream'}, 'normal')
            dep_pids = {dep.pid} | {p.pid for p in psutil.Process(dep.pid).children(recursive=True)}
            observed_app = {row['pid'] for row in process_snapshot['payload']['processes']}
            observed_dep = {row['pid'] for row in dependency_snapshot['payload']['processes']}
            assert observed_app <= app_pids and observed_dep and observed_dep <= dep_pids
            assert not observed_app & observed_dep
            dep_logs = await query('probe_text_log', {'service': 'downstream', 'path': str(dep_log)}, 'normal')
            assert dep_logs['payload']['lines']
            assert all(json.loads(line)['pid'] in dep_pids for line in dep_logs['payload']['lines'])
            cases.append({'case': 'separate_process_and_log_identities', 'status': 'passed', 'model_calls': 0})
            stop_owned(app)
            exited, _ = await observe('application_exit')
            assert exited['app_tcp'] == 'failed' and exited['dependency_http'] == 200
            assert app.poll() is not None
            after_exit = await query('probe_process_snapshot', {'service': 'localapp'}, 'application_exit')
            assert not app_pids & {row['pid'] for row in after_exit['payload']['processes']}
            exited['status'] = 'passed'
            app = application(app_port, app_mode, 'application-recovered', dep_port, runtime_config=app_mode)
            recovered, _ = await observe('application_recovered')
            assert recovered['app_http'] == 200
            recovered['status'] = 'passed'
            stop_owned(dep)
            down, logs = await observe('downstream_unreachable')
            assert app.poll() is None and down['app_tcp'] == 'ok' and down['app_http'] == 503
            assert down['dependency_tcp'] == 'failed' and 'upstream connection failed' in str(logs)
            down['status'] = 'passed'
            from scripts.evaluate_windows_probe import business_catalog
            from src.probe.windows.config import load_config
            from src.agent.aiops.target_catalog import resolve_target
            from src.agent.aiops.strategies import investigation
            from src.agent.aiops.executor import _probe_request_limit
            inventory = await query('probe_inventory', {}, 'mapped-downstream-checks')
            failed_dependency = await query('probe_dependency_probe', {'dependency': 'downstream'}, 'mapped-downstream-checks')
            mapped_state = {'input': 'localapp unavailable', 'autonomous_investigation': True,
                'past_steps': [], 'raw_evidence': [('inventory', json.dumps(inventory)),
                    ('dependency', json.dumps(failed_dependency))],
                'target_resolution': resolve_target(business_catalog(load_config(out / 'config.toml')),
                    'localapp', inventory['payload'], target),
                'investigation_tools': [{'name': name} for name in tools],
                'investigation_config': {'hypothesis_protection': False, 'contradiction_trigger': False}}
            selected = []
            for expected_tool in ['probe_port_snapshot', 'probe_process_snapshot', 'probe_text_log']:
                update = investigation.decide_from_evidence(mapped_state,
                    investigation.InvestigationDecision(hypothesis='dependency unavailable', blocked_reason='fixed stop proposal'),
                    investigation.evidence_index(mapped_state))
                mapped_state.update(update)
                memory = update['investigation_memory']
                assert update['plan'] and memory['next_tools'] == [expected_tool]
                args = memory['policy_selected_check']['arguments']
                assert not _probe_request_limit({'name': expected_tool, 'args': args}, mapped_state)
                observed = await query(expected_tool, args, 'mapped-downstream-checks')
                if expected_tool == 'probe_process_snapshot':
                    assert observed['payload']['processes'] == []
                if expected_tool == 'probe_text_log':
                    assert all(json.loads(line)['pid'] in dep_pids for line in observed['payload']['lines'])
                mapped_state['raw_evidence'].append((update['plan'][0], json.dumps(observed)))
                mapped_state['past_steps'].append((update['plan'][0], 'observed'))
                selected.append({'tool': expected_tool, 'arguments': args, 'raw_hash': observed['raw_hash']})
            final = investigation.decide_from_evidence(mapped_state,
                investigation.InvestigationDecision(hypothesis='dependency unavailable', blocked_reason='fixed stop proposal'),
                investigation.evidence_index(mapped_state))
            assert final['plan'] == [] and final['diagnosis']['kind'] == 'localized_fault'
            assert '事件通道未配置' in final['response']
            (out / 'mapped-downstream-checks.json').write_text(json.dumps({
                'selected': selected, 'diagnosis': final['diagnosis'], 'report': final['response'],
                'model_calls': 0, 'fixed_decisions': True, 'autonomous_effectiveness_verified': False},
                ensure_ascii=False, indent=2), encoding='utf-8')
            cases.append({'case': 'mapped_downstream_checks_executed', 'status': 'passed', 'model_calls': 0,
                          'fixed_decisions': True, 'tools': [row['tool'] for row in selected]})
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
            write_app_mode(mode='application_error')
            error, logs = await observe('application_error')
            assert error['app_http'] == 500 and error['dependency_http'] == 200 and 'request failed' in str(logs)
            error['status'] = 'passed'
            write_app_mode()
            stop_owned(app)
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
            stop_owned(blocker)
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
            stop_owned(gateway)
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
            report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:300],
                'traceback': traceback.format_exc(limit=12)[-8000:]})
        finally:
            (out / 'stop-probe').touch()
            if probe and probe.poll() is None:
                try:
                    await asyncio.to_thread(probe.wait, 20)
                except subprocess.TimeoutExpired:
                    report['errors'].append({'type': 'cleanup', 'message': 'probe did not stop gracefully'})
            pre_cleanup = {id(proc): proc.poll() for proc in owned}
            report.update(cleanup_owned(owned, ports))
            ended_at = datetime.now(timezone.utc).isoformat()
            for proc, lifecycle in process_handles:
                before_cleanup = pre_cleanup[id(proc)]
                controller_stopped = id(proc) in controller_stop_ids or before_cleanup is None
                lifecycle.update(status=('stopped_by_controller' if controller_stopped
                    else 'exited_before_cleanup'), ended_at=ended_at,
                    exit_code=proc.poll(),
                    controller_stop_requested=controller_stopped)
            (out / 'process-lifecycle.json').write_text(
                json.dumps(process_records, ensure_ascii=False, indent=2), encoding='utf-8')
            report['process_lifecycle_file'] = 'process-lifecycle.json'
            report['process_lifecycle_count'] = len(process_records)
            report['errors'].extend(report['cleanup_errors'])
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
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--runtime-config', type=Path, help='Disposable fixture startup connection configuration')
    parser.add_argument('--evaluation-preflight', action='store_true')
    parser.add_argument('--scenario-preflight', action='store_true',
        help='Free mode: real scenario resets and Probe isolation in the four-group schedule, no Agent decisions')
    parser.add_argument('--four-group-suite', choices=list(FOUR_GROUP_SUITES), default='baseline-v1',
        help='Explicit versioned scenario suite; e2-fault-pair-v1 runs two same-entry-503 faults across four groups')
    parser.add_argument('--four-group-slot', action='append', metavar='CASE/GROUP',
        help='Run selected four-group slots only, e.g. downstream_unreachable/G10; repeat per slot')
    parser.add_argument('--run-model', action='store_true',
        help='Paid mode; requires separate explicit authorization for cases and cumulative budget')
    parser.add_argument('--model-stage', choices=['smoke', 'extended', 'knowledge-control', 'four-groups'], default='smoke')
    parser.add_argument('--run-budget-cny', type=float, help='Equal per-run cost cap; four-groups may instead use equal per-run request caps with the shared CNY ceiling')
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--budget-limit-cny', type=float, default=5,
        help='Cumulative reservation ceiling; increasing it requires separate authorization')
    parser.add_argument('--allow-unpriced-model', action='store_true',
        help='Smoke or four-groups: pricing remains unknown, explicit request caps required')
    parser.add_argument('--max-model-requests', type=int,
        help='Cumulative request cap including inherited requests')
    parser.add_argument('--run-max-model-requests', type=int,
        help='Equal per-run new request cap for four-groups')
    parser.add_argument('--max-output-tokens', type=int, default=4096,
        help='Per-request output token cap for model runs')
    parser.add_argument('--smoke-case', choices=['normal', 'downstream_unreachable', 'application_error', 'application_config_error'],
        help='Run one model smoke scenario instead of the default smoke pair')
    parser.add_argument('--symptom-profile', choices=list(SYMPTOM_PROFILES), default='neutral',
        help='Model input profile; candidate-opportunity is for targeted mechanism pre-experiments')
    parser.add_argument('--mechanism-group', choices=['G00', 'G10', 'G01', 'G11'])
    parser.add_argument('--smoke-review', type=Path, help='Human review JSON with smoke_passed=true, required before extended cases')
    parser.add_argument('--manual-repair-wait-seconds', type=int, default=0,
        help='Keep the single config-error business alive for a bounded human repair window, then always clean up')
    args = parser.parse_args()
    if args.manual_repair_wait_seconds and (not 1 <= args.manual_repair_wait_seconds <= 900
            or not args.run_model or args.model_stage != 'smoke' or args.smoke_case != 'application_config_error'):
        parser.error('manual repair window requires one paid config-error smoke, 1..900 seconds')
    import math
    if args.scenario_preflight and (args.run_model or args.evaluation_preflight):
        parser.error('scenario-preflight cannot be combined with model or full evaluation modes')
    if args.four_group_suite != 'baseline-v1' and not (args.scenario_preflight or args.model_stage == 'four-groups'):
        parser.error('four-group-suite requires scenario-preflight or model-stage four-groups')
    four_group_slots = None
    if args.four_group_slot:
        if args.model_stage != 'four-groups' or not args.run_model:
            parser.error('four-group-slot requires a paid four-groups run')
        slots = []
        for value in args.four_group_slot:
            case, separator, group = value.partition('/')
            if not separator or group not in {'G00', 'G10', 'G01', 'G11'}:
                parser.error('four-group-slot must use CASE/GROUP with a valid group')
            slots.append({'case': case, 'group': group})
        slot_keys = [(item['case'], item['group']) for item in slots]
        allowed_slots = {(item['case'], item['group']) for item in four_group_order(args.four_group_suite)}
        if len(set(slot_keys)) != len(slot_keys) or any(key not in allowed_slots for key in slot_keys):
            parser.error('four-group-slot values must be unique slots in the selected suite')
        four_group_slots = slots
    if not math.isfinite(args.budget_limit_cny) or args.budget_limit_cny <= 0:
        parser.error('budget limit must be finite and positive')
    if args.allow_unpriced_model and (not args.run_model or args.model_stage not in {'smoke', 'four-groups'}):
        parser.error('allow-unpriced-model requires smoke or four-groups model runs')
    if args.allow_unpriced_model and (args.max_model_requests is None or args.max_model_requests <= 0):
        parser.error('allow-unpriced-model requires a positive max-model-requests')
    if args.max_output_tokens <= 0:
        parser.error('max-output-tokens must be positive')
    for cap in (args.max_model_requests, args.run_max_model_requests):
        if cap is not None and cap <= 0:
            parser.error('request caps must be positive')
    # A per-run request cap is also valid for a single smoke/extended child;
    # the cumulative cap remains the separate task-wide ceiling.
    if args.model_stage == 'four-groups' and args.allow_unpriced_model and args.run_max_model_requests is None:
        parser.error('unpriced four-groups require a per-run request cap')
    if args.smoke_case and args.model_stage != 'smoke':
        parser.error('smoke-case requires model-stage smoke')
    if args.mechanism_group and (not args.run_model or args.model_stage == 'knowledge-control'):
        parser.error('mechanism group requires --run-model and fixed knowledge conditions')
    if args.model_stage == 'four-groups' and (not args.run_model or args.mechanism_group
            or (not args.allow_unpriced_model and args.run_max_model_requests is None and (args.run_budget_cny is None
                or not math.isfinite(args.run_budget_cny) or args.run_budget_cny <= 0))):
        parser.error('four-groups requires explicit paid mode, per-run cap and no single-group override')
    if args.serve is not None:
        serve(args.serve, args.log, args.downstream, args.mode_file, args.stop_file, args.runtime_config)
        return 0
    if args.run_model and args.model_stage in {'extended', 'four-groups'}:
        if not args.smoke_review or json.loads(args.smoke_review.read_text(encoding='utf-8')).get('smoke_passed') is not True:
            parser.error('extended cases require a completed human smoke review')
    if args.run_model and args.model_stage in {'extended', 'knowledge-control', 'four-groups'} and not args.previous_cost:
        parser.error('later stages require the cumulative cost ledger; retries must not reset the budget')
    out = ROOT / 'runtime' / ('windows-local-faults-' + uuid.uuid4().hex)
    report = asyncio.run(verify(out, evaluation_preflight=args.evaluation_preflight, run_model=args.run_model,
        model_stage=args.model_stage, previous_cost=args.previous_cost, mechanism_group=args.mechanism_group,
        budget_limit_cny=args.budget_limit_cny, run_budget_cny=args.run_budget_cny,
        allow_unpriced_model=args.allow_unpriced_model, max_model_requests=args.max_model_requests,
        run_max_model_requests=args.run_max_model_requests,
        max_output_tokens=args.max_output_tokens, smoke_case=args.smoke_case,
        four_group_suite=args.four_group_suite, scenario_preflight=args.scenario_preflight,
        symptom_profile=args.symptom_profile, four_group_slots=four_group_slots,
        manual_repair_wait_seconds=args.manual_repair_wait_seconds))
    print(json.dumps({'directory': str(out), **report}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
