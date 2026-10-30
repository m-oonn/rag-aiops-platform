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


def get_local(port, timeout=2):
    try:
        response = build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/health', timeout=timeout)
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
            detail, error_type = '', None
            if mode.startswith('{'):
                try:
                    # The controller may inject invalid application configuration.
                    int(json.loads(mode)['max_attempts'])
                    mode = 'normal'
                except (ValueError, TypeError, KeyError) as exc:
                    status, body = 503, 'temporarily unavailable'
                    detail, error_type = 'invalid max_attempts configuration', type(exc).__name__
            if error_type:
                pass
            elif mode == 'http_error':
                status, body = 503, 'temporarily unavailable'
            elif mode == 'application_error':
                status, body = 500, 'request failed'
            elif downstream is not None:
                try:
                    status, body = get_local(downstream, timeout=0.5)
                except (URLError, OSError):
                    status, body = 503, 'temporarily unavailable'
                    detail = 'upstream connection failed'
            with log.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                    'pid': os.getpid(), 'status': status, 'detail': detail or body,
                    **({'error_type': error_type} if error_type else {})}) + '\n')
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


def verify_case_state(out, case, app, dep, app_port, dep_port, log, blocker=None):
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


async def evaluate_model_case(out, case, launch, previous_cost=None, knowledge_url=None, knowledge_disabled=False, mechanism_group=None, budget_limit_cny=5, run_budget_cny=None, observation_not_before=None, allow_unpriced_model=False, max_model_requests=None, max_output_tokens=4096, isolate_history=False):
    """Only the caller's explicit paid mode may invoke this serial runner."""
    from scripts.evaluate_windows_probe import read_cost_ledger, MECHANISM_GROUPS
    sample_id = uuid.uuid4().hex
    result_dir = out / ('model-' + sample_id)
    symptom_file = out / ('symptom-' + sample_id + '.txt')
    symptom_file.write_text('请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。', encoding='utf-8')
    args = [str(ROOT / 'scripts/evaluate_windows_probe.py'), '--run-model',
        '--probe-config', str(out / 'config.toml'), '--symptom-file', str(symptom_file),
        '--output-dir', str(result_dir), '--local-runbooks', str(out / 'runbooks'),
        '--max-output-tokens', str(max_output_tokens)]
    if allow_unpriced_model:
        args += ['--allow-unpriced-model', '--max-model-requests', str(max_model_requests)]
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
    expected = {'normal': ['healthy_within_scope'], 'downstream_unreachable': ['localized_fault'],
        'application_error': ['localized_fault'], 'application_config_error': ['localized_fault'],
        'application_exit': ['localized_fault'],
        'port_conflict': ['localized_fault', 'confirmed_cause'], 'missing_evidence': ['unlocated', 'localized_fault']}
    allowed = {'probe_inventory', 'probe_resource_snapshot', 'probe_service_status', 'probe_process_snapshot',
        'probe_port_snapshot', 'probe_event_log', 'probe_text_log', 'probe_dependency_probe',
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
        'mechanical_status': 'passed' if mechanical_passed else 'failed',
        'workflow_status': 'completed' if completed else 'incomplete',
        'result_level_status': 'passed' if level_matches else 'failed',
        'semantic_status': 'pending_manual_review', 'capability_passed': False,
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


async def evaluate_blind_cases(out, launch, set_case, knowledge_url=None, suite=None, previous_cost=None, mechanism_group=None, budget_limit_cny=5, allow_unpriced_model=False, max_model_requests=None, max_output_tokens=4096):
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
            if allow_unpriced_model:
                options.update(allow_unpriced_model=True, max_model_requests=max_model_requests,
                    max_output_tokens=max_output_tokens)
            if budget_limit_cny != 5:
                options['budget_limit_cny'] = budget_limit_cny
            result = await evaluate_model_case(out, case, launch, previous, knowledge_url=knowledge_url, **options)
            results.append(result)
            (out / 'blind-controller.json').write_text(json.dumps(controller, ensure_ascii=False, indent=2), encoding='utf-8')
            if result.get('status') != 'passed' or result.get('workflow_completed') is not True:
                raise RuntimeError('blind model child failed mechanical gates')
            previous = Path(result['cost_file'])
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


async def evaluate_four_groups(out, launch, set_case, knowledge_url, previous_cost, budget_limit_cny, run_budget_cny):
    """Same controller-owned environment, serial fresh children; no implicit paid entry."""
    import math
    from scripts.evaluate_windows_probe import read_cost_ledger
    from scripts.evaluation_record import utc_now
    if type(run_budget_cny) not in (int, float) or not math.isfinite(run_budget_cny) or run_budget_cny <= 0:
        raise ValueError('four groups require a positive per-run reservation cap')
    previous = read_cost_ledger(previous_cost, for_resume=True, limit_cny=budget_limit_cny)
    # Reserve the same opportunity for every group before touching the business.
    cases = ['normal', 'downstream_unreachable', 'application_error']
    if budget_limit_cny - previous['reserved_cny'] < len(cases) * 4 * run_budget_cny:
        raise RuntimeError('insufficient cumulative allowance for equal four-group caps')
    def conditions():
        import hashlib
        paths = [out / 'config.toml', out / 'knowledge-manifest.json', *sorted((out / 'runbooks').rglob('*.md'))]
        if len(paths) <= 2:
            raise ValueError('four groups require fixed knowledge corpus')
        return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    fixed = conditions()
    secrets.SystemRandom().shuffle(cases)
    order = []
    for case in cases:
        groups = ['G00', 'G10', 'G01', 'G11']
        secrets.SystemRandom().shuffle(groups)
        order.extend({'case': case, 'group': group} for group in groups)
    record = {'version': 1, 'order': order, 'conditions_sha256': fixed, 'results': [],
        'started_at': utc_now(), 'ended_at': None, 'recovery': 'pending', 'status': 'started',
        'run_budget_cny': run_budget_cny, 'budget_limit_cny': budget_limit_cny,
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
            result = await evaluate_model_case(out, item['case'], launch, previous_path,
                knowledge_url=knowledge_url, mechanism_group=item['group'],
                budget_limit_cny=budget_limit_cny, run_budget_cny=run_budget_cny,
                observation_not_before=observation_boundary)
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
            if (integrity['comparison_config'].get('run_budget_cny') != run_budget_cny
                    or integrity['comparison_config'].get('shared_history_enabled') is not False
                    or integrity.get('observation_not_before') != observation_boundary):
                raise ValueError('four-group child did not preserve per-run cap or history isolation')
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


async def verify(out, evaluation_preflight=False, run_model=False, model_stage='smoke', previous_cost=None, mechanism_group=None, budget_limit_cny=5, run_budget_cny=None, allow_unpriced_model=False, max_model_requests=None, max_output_tokens=4096, smoke_case=None):
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
    app_mode, dep_mode = out / 'app.mode', out / 'downstream.mode'
    app_mode.write_text('normal', encoding='utf-8')
    dep_mode.write_text('normal', encoding='utf-8')
    (out / 'config.toml').write_text('\n'.join([f"target_id = '{target}'",
        f"gateway_url = 'ws://127.0.0.1:{gateway_port}/probe/ws'",
        f"token_file = '{(out / 'token').as_posix()}'", 'baseline_interval_seconds = 60',
        '[services.localapp]', "kind = 'process'",
        "process_names = ['python.exe']", f"text_logs = ['{log.as_posix()}']",
        f"process_args = ['--mode-file', '{app_mode}']",
        '[services.downstream]', "kind = 'process'", "process_names = ['python.exe']",
        f"process_args = ['--mode-file', '{dep_mode}']", f"text_logs = ['{dep_log.as_posix()}']",
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
            app_log = log if port == app_port else dep_log
            args = [str(Path(__file__).resolve()), '--serve', str(port), '--log', str(app_log), '--mode-file', str(mode)]
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
                    '--knowledge-mcp-url', knowledge_config['knowledge']['url'],
                    '--knowledge-manifest', str(out / 'knowledge-manifest.json')], 'evaluation-preflight-' + case)
                code = await asyncio.to_thread(process.wait, 45)
                assert code == 0, 'evaluation preflight failed: ' + case
                result = json.loads((result_dir / 'preflight.json').read_text(encoding='utf-8'))
                assert result['ok'] and result['model_calls'] == 0 and result['evidence_count'] == 5
                assert not (result_dir / 'cost.json').exists(), 'free preflight entered paid budget path'
                assert len(result['tool_names']) == 10
                assert result['knowledge_mcp']['transport'] == 'streamable_http_loopback'
                assert not result['knowledge_mcp']['autonomously_selected']
                tool_trace = json.loads((result_dir / 'tool_trace.json').read_text(encoding='utf-8'))
                assert len(tool_trace) == 6
                assert sum(row['validated_live_evidence'] for row in tool_trace) == 5
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
                app_mode.write_text(json.dumps({'max_attempts': 'invalid'}) if case == 'application_config_error'
                    else 'application_error' if case in {'application_error', 'missing_evidence'} else 'normal', encoding='utf-8')
                dep_mode.write_text('normal', encoding='utf-8')
                log.write_text('', encoding='utf-8')
                dep_log.write_text('', encoding='utf-8')
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
                snapshot = verify_case_state(out, case, app, dep, app_port, dep_port, log, blocker)
                return {**snapshot, 'app_pids': [row['pid'] for row in snapshot['listeners'] if row['port'] == app_port],
                    'downstream_pids': [row['pid'] for row in snapshot['listeners'] if row['port'] == dep_port]}
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
                        knowledge_config['knowledge']['url'], previous_cost, budget_limit_cny, run_budget_cny))
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
                    cases.extend(await evaluate_blind_cases(out, launch, set_model_case,
                        knowledge_url=knowledge_config['knowledge']['url'], suite=suite, previous_cost=previous_cost,
                        mechanism_group=mechanism_group, budget_limit_cny=budget_limit_cny,
                        allow_unpriced_model=allow_unpriced_model, max_model_requests=max_model_requests,
                        max_output_tokens=max_output_tokens))
            from scripts.verify_windows_probe_graph import verify_graph
            if evaluation_preflight and not run_model:
                from scripts.verify_probe_mechanisms import verify_mechanism_groups
                cases.append(await verify_mechanism_groups(tools, out, log, knowledge_tool, knowledge_config['knowledge']['url']))
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
            report.update(cleanup_owned(owned, ports))
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
    parser.add_argument('--evaluation-preflight', action='store_true')
    parser.add_argument('--run-model', action='store_true',
        help='Paid mode; requires separate explicit authorization for cases and cumulative budget')
    parser.add_argument('--model-stage', choices=['smoke', 'extended', 'knowledge-control', 'four-groups'], default='smoke')
    parser.add_argument('--run-budget-cny', type=float, help='Required equal per-run reservation cap for four-groups')
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--budget-limit-cny', type=float, default=5,
        help='Cumulative reservation ceiling; increasing it requires separate authorization')
    parser.add_argument('--allow-unpriced-model', action='store_true',
        help='Explicit smoke-only mode for a model without verified pricing; cost remains unknown')
    parser.add_argument('--max-model-requests', type=int,
        help='Hard request cap for allow-unpriced-model smoke runs')
    parser.add_argument('--max-output-tokens', type=int, default=4096,
        help='Per-request output token cap for model runs')
    parser.add_argument('--smoke-case', choices=['normal', 'downstream_unreachable', 'application_error'],
        help='Run one model smoke scenario instead of the default smoke pair')
    parser.add_argument('--mechanism-group', choices=['G00', 'G10', 'G01', 'G11'])
    parser.add_argument('--smoke-review', type=Path, help='Human review JSON with smoke_passed=true, required before extended cases')
    args = parser.parse_args()
    import math
    if not math.isfinite(args.budget_limit_cny) or args.budget_limit_cny <= 0:
        parser.error('budget limit must be finite and positive')
    if args.allow_unpriced_model and (not args.run_model or args.model_stage != 'smoke'):
        parser.error('allow-unpriced-model is restricted to smoke model runs')
    if args.allow_unpriced_model and (args.max_model_requests is None or args.max_model_requests <= 0):
        parser.error('allow-unpriced-model requires a positive max-model-requests')
    if args.max_output_tokens <= 0:
        parser.error('max-output-tokens must be positive')
    if args.smoke_case and args.model_stage != 'smoke':
        parser.error('smoke-case requires model-stage smoke')
    if args.mechanism_group and (not args.run_model or args.model_stage == 'knowledge-control'):
        parser.error('mechanism group requires --run-model and fixed knowledge conditions')
    if args.model_stage == 'four-groups' and (not args.run_model or args.mechanism_group
            or args.run_budget_cny is None or not math.isfinite(args.run_budget_cny) or args.run_budget_cny <= 0):
        parser.error('four-groups requires explicit paid mode, per-run cap and no single-group override')
    if args.serve is not None:
        serve(args.serve, args.log, args.downstream, args.mode_file)
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
        max_output_tokens=args.max_output_tokens, smoke_case=args.smoke_case))
    print(json.dumps({'directory': str(out), **report}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
