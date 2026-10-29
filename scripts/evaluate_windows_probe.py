"""Windows Probe preflight; real model mode requires separate user authorization."""
import asyncio
import argparse
import importlib
import json
import os
import math
import hashlib
from contextlib import contextmanager, asynccontextmanager, ExitStack
from unittest.mock import patch
from pathlib import Path
import sys
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit
import time
from datetime import datetime
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation_record import EvaluationRecord, utc_now
MECHANISM_GROUPS = {'G00': (False, False), 'G10': (True, False),
                    'G01': (False, True), 'G11': (True, True)}


def configure_mechanisms(group):
    from src.settings import settings
    from src.agent.aiops.strategies.investigation import mechanism_config
    if group is not None:
        protection, trigger = MECHANISM_GROUPS[group]
        settings.INVESTIGATION_HYPOTHESIS_PROTECTION = protection
        settings.INVESTIGATION_CONTRADICTION_TRIGGER = trigger
    return mechanism_config()


def audit_mechanisms(expected, values, snapshots, *, executed_steps=None, execution_records=None):
    """Check actual checkpoint data, never infer switches from a group label."""
    from src.agent.aiops.strategies.investigation import _public_tracking
    diagnosis = values.get('diagnosis') or {}
    tracking = (values.get('investigation_memory') or {}).get('hypothesis_tracking') or {}
    checks = {'initial_config': values.get('investigation_config') == expected,
        'diagnosis_config': diagnosis.get('mechanism_config') == expected,
        'tracking_config': tracking.get('config') == expected,
        # Old checkpoints store full tracking; new diagnoses store its public projection.
        'diagnosis_tracking': bool(tracking) and diagnosis.get('mechanisms') in (
            tracking, _public_tracking(tracking)),
        'has_decision_trace': bool(snapshots),
        'trace_configs': bool(snapshots) and all(row['tracking'].get('config') == expected for row in snapshots)}
    events = tracking.get('events', [])
    checks['disabled_protection_has_no_events'] = expected['hypothesis_protection'] or not any(
        e.get('kind') in {'hypothesis_protected', 'protection_check_selected', 'protection_expired'} for e in events)
    checks['disabled_trigger_has_no_events'] = expected['contradiction_trigger'] or not any(
        e.get('kind') in {'contradiction_triggered', 'contradiction_blocked'} for e in events)
    from scripts.mechanism_behavior import audit_behavior
    behavior = audit_behavior(snapshots, executed_steps, execution_records)
    return {'passed': all(checks.values()) and behavior['status'] != 'failed',
        'checks': checks, 'behavior': behavior, 'expected_config': expected,
        'actual_config': values.get('investigation_config'),
        'event_counts': {kind: sum(e.get('kind') == kind for e in events) for kind in sorted({e.get('kind', '') for e in events})},
        'mechanism_effectiveness_verified': False}


async def save_mechanism_audit(service, thread_id, expected, output):
    from src.probe.protocol import redact
    from src.agent.aiops.evidence_sources import knowledge_context
    from scripts.mechanism_behavior import behavior_snapshot
    snapshots, values = [], {}
    error = None
    try:
        if not thread_id:
            raise ValueError('missing completed thread id')
        graph = await service._persistent_graph(service._create_strategy())
        final = await graph.aget_state({'configurable': {'thread_id': thread_id}})
        values = final.values or {}
        async for snapshot in graph.aget_state_history({'configurable': {'thread_id': thread_id}}):
            # Replanner outputs schedule executor or end; pre-replan states are not decisions.
            if snapshot.next and 'executor' not in snapshot.next:
                continue
            state = snapshot.values or {}
            tracking = (state.get('investigation_memory') or {}).get('hypothesis_tracking')
            if tracking:
                knowledge = knowledge_context(state.get('raw_evidence'))
                encoded = json.dumps(knowledge, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                snapshots.append({**behavior_snapshot(state, snapshot.created_at),
                    'knowledge': knowledge, 'knowledge_sha256': hashlib.sha256(encoded.encode('utf-8')).hexdigest()})
        snapshots.reverse()
    except Exception as exc:
        error = type(exc).__name__
    from src.agent.aiops.strategies.investigation import execution_checks
    executions = execution_checks(values)
    audit = audit_mechanisms(expected, values, snapshots,
        executed_steps=[step for step, _ in values.get('past_steps', [])], execution_records=executions)
    if error:
        audit.update(passed=False, read_error=error)
    (output / 'mechanism_trace.json').write_text(json.dumps(redact({
        'thread_id': thread_id, 'audit': audit, 'decisions': snapshots,
        'execution_records': executions,
        'executed_steps': [step for step, _ in values.get('past_steps', [])]}),
        ensure_ascii=False, indent=2), encoding='utf-8')
    return audit


def classify_report(report: str, diagnosis: dict | None = None) -> str:
    """Classify the report format; this does not grade diagnostic correctness."""
    if diagnosis and diagnosis.get('version') == 1 and diagnosis.get('kind') in {
            'confirmed_cause', 'localized_fault', 'healthy_within_scope', 'unlocated'}:
        return diagnosis['kind']
    text = report.strip()
    if not text:
        return 'none'
    if text.startswith('未定位根因：'):
        return 'unlocated'
    if text.startswith('当前检查范围内未发现故障'):
        return 'healthy_within_checked_scope'
    if text.startswith('根因：'):
        return 'root_cause_reported'
    if text.startswith('已定位故障层：'):
        return 'localized_fault'
    return 'unrecognized'


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--run-budget-cny', type=float, help='Equal per-run reservation cap for matched groups')
    parser.add_argument('--isolate-history', action='store_true', help='Exclude shared gateway history from matched group investigations')
    parser.add_argument('--observation-not-before', help='Reject Probe evidence and test-app log rows collected before this run boundary')
    parser.add_argument('--budget-limit-cny', type=float, default=5,
        help='Explicit cumulative reservation ceiling; increases require separate user authorization')
    parser.add_argument('--probe-config', type=Path)
    parser.add_argument('--symptom-file', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--mechanism-group', choices=MECHANISM_GROUPS,
        help='Same investigation implementation; only protection/contradiction switches differ')
    parser.add_argument('--local-runbooks', type=Path,
        help='Isolated local runbook retrieval; no embedding/rerank calls, not vector RAG validation')
    parser.add_argument('--knowledge-mcp-url', type=local_knowledge_url,
        help='Loopback knowledge MCP; only search_knowledge_base is used')
    parser.add_argument('--knowledge-kb-id', type=int, default=14, help='Free preflight library scope (legacy fixture: 14)')
    parser.add_argument('--knowledge-query', default='localapp availability', help='Free preflight retrieval query')
    parser.add_argument('--knowledge-source', help='Free preflight expected source filename')
    parser.add_argument('--knowledge-manifest', type=Path, help='Controller-owned fixture baseline to verify before/after execution')
    parser.add_argument('--run-model', action='store_true',
        help='Paid mode; use only after explicit user authorization for this run')
    parser.add_argument('--allow-unpriced-model', action='store_true',
        help='Explicit smoke-only mode for a model without verified pricing; cost remains unknown')
    parser.add_argument('--max-model-requests', type=int,
        help='Hard request cap for allow-unpriced-model smoke runs')
    parser.add_argument('--max-output-tokens', type=int, default=4096,
        help='Per-request output token cap for model runs')
    parser.add_argument('--knowledge-disabled', action='store_true',
        help='Disable planning references and knowledge tools for a matched control run')
    parser.add_argument('--limited-evidence', action='store_true',
        help='Controller-only case: withhold downstream and log observations without changing Probe permissions')
    args = parser.parse_args(argv)
    if not math.isfinite(args.budget_limit_cny) or args.budget_limit_cny <= 0:
        parser.error('budget limit must be finite and positive')
    if args.allow_unpriced_model and not args.run_model:
        parser.error('allow-unpriced-model requires --run-model')
    if args.allow_unpriced_model and (args.max_model_requests is None or args.max_model_requests <= 0):
        parser.error('allow-unpriced-model requires a positive max-model-requests')
    if args.max_output_tokens <= 0:
        parser.error('max-output-tokens must be positive')
    if args.run_budget_cny is not None and (not math.isfinite(args.run_budget_cny) or args.run_budget_cny <= 0):
        parser.error('per-run budget must be finite and positive')
    if args.observation_not_before:
        try:
            boundary = datetime.fromisoformat(args.observation_not_before.replace('Z', '+00:00'))
            if boundary.tzinfo is None:
                raise ValueError
        except ValueError:
            parser.error('observation boundary must be a timezone-aware ISO timestamp')
    if args.mechanism_group and args.knowledge_disabled:
        parser.error('mechanism groups require unchanged knowledge conditions')
    if args.knowledge_kb_id <= 0 or not args.knowledge_query.strip():
        parser.error('knowledge library must be positive and query must not be empty')
    if args.knowledge_source is not None and not args.knowledge_source.strip():
        parser.error('knowledge source must not be empty')
    custom_knowledge = args.knowledge_kb_id != 14 or args.knowledge_query != 'localapp availability' or args.knowledge_source is not None
    if custom_knowledge and (not args.knowledge_mcp_url or args.knowledge_disabled or args.run_model):
        parser.error('knowledge scope/query/source options require enabled free MCP preflight')
    if args.knowledge_manifest and (not args.local_runbooks or not args.knowledge_mcp_url or args.knowledge_disabled):
        parser.error('knowledge manifest requires enabled fixture runbooks and MCP')
    return args


def local_knowledge_url(value):
    parsed = urlsplit(value)
    try:
        valid = (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
            and parsed.port is not None and 0 < parsed.port < 65536
            and not parsed.username and not parsed.password
            and parsed.path == '/mcp' and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError('knowledge MCP must use http://127.0.0.1:<port>/mcp')
    return value


@asynccontextmanager
async def load_evaluation_tools(cfg, knowledge_url=None):
    from src.agent.mcp_client import load_tools_for_config, close_client_for_config
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    configs = []
    try:
        probe_config = {'probe': {'transport': 'streamable_http', 'url': mcp_url(cfg.gateway_url),
            'tls_verify': True, 'headers': {'Authorization': 'Bearer ' + cfg.token_file.read_text(encoding='utf-8').strip()}}}
        configs.append(probe_config)
        tools, error = await load_tools_for_config(probe_config)
        assert error is None and len(tools) == 9, 'Probe tools unavailable'
        assert {tool.name for tool in tools} == set(PROBE_TOOL_OPERATIONS) | {'probe_list_evidence'}, 'unexpected Probe tools'
        if knowledge_url:
            knowledge_config = {'knowledge': {'transport': 'streamable_http',
                'url': local_knowledge_url(knowledge_url)}}
            configs.append(knowledge_config)
            knowledge, error = await load_tools_for_config(knowledge_config)
            names = [tool.name for tool in knowledge]
            if error or names.count('search_knowledge_base') != 1 or not set(names) <= {
                    'search_knowledge_base', 'list_knowledge_bases', 'get_document_info'}:
                raise RuntimeError('Unexpected or unavailable local knowledge MCP tools')
            tools = [*tools, *[tool for tool in knowledge if tool.name == 'search_knowledge_base']]
        yield tools
    finally:
        for config in reversed(configs):
            close_client_for_config(config)


def mcp_url(gateway_url):
    parsed = urlsplit(gateway_url)
    return urlunsplit(('https' if parsed.scheme == 'wss' else 'http', parsed.netloc, '/mcp', '', ''))


def target_catalog(cfg):
    """Expose configured query names, never the token, CA or gateway settings."""
    from dataclasses import asdict
    return json.dumps({'target_id': cfg.target_id,
        'services': {name: {key: item for key, item in asdict(value).items() if key != 'process_args'}
                     for name, value in cfg.services.items()},
        'dependencies': {name: asdict(value) for name, value in cfg.dependencies.items()}},
        ensure_ascii=False)


def business_catalog(cfg):
    """The disposable app is a process, not an installed Windows service."""
    dependencies = sorted(cfg.dependencies)
    entries = {}
    for name, dep in cfg.dependencies.items():
        if name == 'localapp' and dep.health_scheme:
            entries[f'{dep.health_scheme}://{dep.host}:{dep.port}{dep.health_path}'] = name
    return json.dumps({'version': 1, 'target_id': cfg.target_id, 'services': {
        'localapp': {'aliases': ['测试应用'], 'entries': entries,
            'probe_service': 'localapp' if 'localapp' in cfg.services else None,
            'log_refs': ['localapp'] if 'localapp' in cfg.services else [],
            'dependency_services': {name: name for name in dependencies if name in cfg.services},
            'dependencies': dependencies}}}, ensure_ascii=False)


@contextmanager
def local_runbook_retrieval(directory, output):
    """Use the real local retriever, isolated from the existing knowledge corpus."""
    from src.agent.aiops import local_retrieval
    directory = Path(directory).resolve(strict=True)
    files = sorted(directory.rglob('*.md'))
    if not files:
        raise ValueError('local runbook directory contains no Markdown documents')
    sources = [{'path': path.relative_to(directory).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    trace = []
    def retrieve(query):
        context = local_retrieval.retrieve_local(query)
        trace.append({'query': query, 'context': context, 'retrieved': bool(context),
            'context_sha256': hashlib.sha256(context.encode('utf-8')).hexdigest()})
        (output / 'knowledge_trace.json').write_text(json.dumps({
            'mode': 'local_runbooks', 'vector_rag_evaluated': False,
            'sources': sources, 'queries': trace}, ensure_ascii=False, indent=2), encoding='utf-8')
        return context
    with ExitStack() as stack:
        for name, value in {'_RUNBOOKS_DIR': directory, '_KAGGLE_SOURCES': [],
                '_HF_DIR': directory / 'huggingface', '_jsonl_index': None}.items():
            stack.enter_context(patch.object(local_retrieval, name, value))
        yield retrieve


def read_cost_ledger(path, *, for_resume=False, limit_cny=None):
    """Reject incomplete/corrupt accounting instead of resetting the budget."""
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    def amount(number):
        return isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0
    if not isinstance(value, dict) or not amount(value.get('limit_cny')) or value['limit_cny'] <= 0:
        raise ValueError('invalid cumulative cost limit')
    rows, reserved = value.get('requests'), value.get('reserved_cny')
    if not isinstance(rows, list) or not amount(reserved) or reserved > value['limit_cny']:
        raise ValueError('invalid cumulative cost ledger')
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get('number') != index or not amount(row.get('reserved_cny')):
            raise ValueError('invalid request reservation')
    if not math.isclose(math.fsum(row['reserved_cny'] for row in rows), reserved, abs_tol=1e-9, rel_tol=1e-9):
        raise ValueError('cumulative cost does not match request reservations')
    ceiling = value['limit_cny'] if limit_cny is None else limit_cny
    if not amount(ceiling) or ceiling <= 0:
        raise ValueError('invalid cumulative cost limit')
    from scripts.evaluate_autonomous_investigation import model_usage_known
    if for_resume and (reserved >= ceiling or any(not model_usage_known(row) for row in rows)):
        raise RuntimeError('prior scenario has exhausted or uncertain cost; stopping')
    return value


async def knowledge_preflight(tool, output, *, kb_id=14, query='localapp availability', expected_source=None):
    """Read-only retrieval and provenance check, independent of Probe availability."""
    from src.agent.aiops.evidence_sources import knowledge_context
    from src.probe.protocol import redact
    knowledge_check = {'transport': 'streamable_http_loopback', 'kb_id': kb_id, 'query': query,
        'expected_source': expected_source, 'fragments': [], 'passed': False,
        'vector_rag_evaluated': False, 'autonomously_selected': False}
    try:
        if type(kb_id) is not int or kb_id <= 0 or not query.strip():
            raise ValueError('invalid knowledge preflight scope or query')
        raw = await tool.ainvoke({'query': query, 'kb_id': kb_id, 'top_k': 3})
        fragments = knowledge_context([('local knowledge', raw)])
        knowledge_check['fragments'] = fragments
        checks = {'has_results': bool(fragments),
            'traceable_sources': bool(fragments) and all(
                item['source'].strip() not in {'', 'unknown'} and item['chunk_id'].strip()
                and str(item['page']).isdecimal() and int(item['page']) > 0 for item in fragments),
            'library_scope': bool(fragments) and all(item.get('kb_id') == kb_id for item in fragments),
            'expected_source': expected_source is None or any(item['source'] == expected_source for item in fragments)}
        knowledge_check['checks'] = checks
        if not all(checks.values()):
            raise ValueError('knowledge preflight source verification failed')
        knowledge_check['passed'] = True
    except Exception as exc:
        knowledge_check['error'] = str(redact(str(exc)))
        raise
    finally:
        (output / 'knowledge-preflight.json').write_text(json.dumps(knowledge_check,
            ensure_ascii=False, indent=2), encoding='utf-8')
    return knowledge_check


async def preflight(cfg, output, knowledge_url=None, *, kb_id=14, query='localapp availability', expected_source=None):
    from src.probe.evidence import validate_tool_evidence
    rows = []
    async with load_evaluation_tools(cfg, knowledge_url) as tools:
        trace = []
        tools = trace_evaluation_tools(tools, cfg.target_id, output, trace)
        by_name = {tool.name: tool for tool in tools}
        knowledge_check = None
        if knowledge_url:
            knowledge_check = await knowledge_preflight(by_name['search_knowledge_base'], output,
                kb_id=kb_id, query=query, expected_source=expected_source)
        checks = [('probe_inventory', {})]
        checks += [('probe_dependency_probe', {'dependency': name}) for name in cfg.dependencies]
        checks += [('probe_text_log', {'service': name, 'path': path, 'lines': 20})
            for name, service in cfg.services.items() for path in service.text_logs
            if not any(char in path for char in '*?[')]
        for name, arguments in checks:
            raw = validate_tool_evidence(await by_name[name].ainvoke(arguments),
                tool_name=name, target_id=cfg.target_id)
            rows.append({'tool': name, 'arguments': arguments, 'raw': raw})
        result = {'ok': True, 'mode': 'preflight', 'model_calls': 0,
            'autonomous_model_investigation': False, 'target_id': cfg.target_id,
            'evidence_count': len(rows), 'checks': rows, 'target_catalog': json.loads(target_catalog(cfg)),
            'tool_names': [tool.name for tool in tools], 'knowledge_mcp': knowledge_check}
        (output / 'preflight.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'output': str(output), 'mode': 'preflight', 'ok': True,
            'model_calls': 0, 'evidence_count': len(rows)}, ensure_ascii=False), flush=True)


def trace_evaluation_tools(tools, target_id, output, trace, observation_not_before=None):
    from src.probe.protocol import redact
    from src.probe.evidence import validate_tool_evidence, validate_observation_window, PROBE_TOOL_OPERATIONS
    from langchain_core.tools import StructuredTool
    def traced(tool):
        async def invoke(**kwargs):
            started = time.perf_counter()
            row = {'tool': tool.name, 'arguments': redact(kwargs), 'status': 'started',
                'started_at': utc_now(), 'ended_at': None, 'elapsed_ms': None,
                'validated_live_evidence': False,
                'source': 'knowledge_base' if tool.name == 'search_knowledge_base' else 'probe'}
            trace.append(row)
            def save():
                (output / 'tool_trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            save()
            try:
                value = await tool.ainvoke(kwargs)
                row['result'] = redact(value)
                if tool.name in PROBE_TOOL_OPERATIONS:
                    item = validate_tool_evidence(value, target_id=target_id, tool_name=tool.name)
                    if observation_not_before:
                        validate_observation_window(item, observation_not_before)
                    row['validated_live_evidence'] = True
                row['status'] = 'returned'
                return value
            except BaseException as exc:
                row.update(status='failed', error_type=type(exc).__name__)
                raise
            finally:
                row.update(ended_at=utc_now(), elapsed_ms=(time.perf_counter() - started) * 1000)
                save()
        return StructuredTool.from_function(coroutine=invoke, name=tool.name,
            description=tool.description, args_schema=tool.args_schema)
    return [traced(tool) for tool in tools]


async def main():
    args = parse_args()
    from scripts.windows_probe import _set_acl, config_path
    from src.probe.windows.config import load_config

    symptom_override = None
    if args.symptom_file:
        symptom_override = args.symptom_file.read_text(encoding='utf-8').strip()
        if not symptom_override:
            raise ValueError('symptom file is empty')
    output = (args.output_dir or ROOT / 'runtime' / ('windows-model-' + uuid4().hex)).resolve()
    output.mkdir(parents=True, exist_ok=False)
    _set_acl(output)
    if symptom_override:
        (output / 'symptom.txt').write_text(symptom_override, encoding='utf-8')
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output / 'runs.sqlite').as_posix()
    os.environ['AIOPS_CHECKPOINT_DB_PATH'] = str(output / 'checkpoints.sqlite')
    os.environ['ENABLE_EXPERIENCE_CONTEXT'] = 'false'
    if args.knowledge_disabled:
        args.local_runbooks = None
        args.knowledge_mcp_url = None
    cfg = load_config(args.probe_config or config_path())
    if cfg.tls_ca_file and cfg.gateway_url.startswith('wss://'):
        os.environ['SSL_CERT_FILE'] = str(cfg.tls_ca_file)
    if not args.run_model:
        from scripts.knowledge_conditions import check_knowledge_conditions
        if args.knowledge_manifest:
            check_knowledge_conditions(args.knowledge_manifest, args.local_runbooks, output, args.knowledge_mcp_url, 'before')
        await preflight(cfg, output, args.knowledge_mcp_url, kb_id=args.knowledge_kb_id,
            query=args.knowledge_query, expected_source=args.knowledge_source)
        requested = configure_mechanisms(args.mechanism_group)
        (output / 'mechanism-preflight.json').write_text(json.dumps({
            'requested_group': args.mechanism_group, 'requested_config': requested,
            'runtime_verified': False, 'model_calls': 0}, ensure_ascii=False, indent=2), encoding='utf-8')
        if args.local_runbooks:
            with local_runbook_retrieval(args.local_runbooks, output) as retrieve:
                retrieve(symptom_override or 'Windows 主机运行概况')
        if args.knowledge_manifest:
            check_knowledge_conditions(args.knowledge_manifest, args.local_runbooks, output, args.knowledge_mcp_url, 'after')
        return
    async with load_evaluation_tools(cfg, args.knowledge_mcp_url) as tools:
        await run_model(args, cfg, output, tools, symptom_override)


async def run_model(args, cfg, output, tools, symptom_override=None):
    record = EvaluationRecord(ROOT, output, {'mechanism_group': getattr(args, 'mechanism_group', None),
        'target_id': getattr(cfg, 'target_id', None),
        'previous_cost': str(args.previous_cost) if args.previous_cost else None,
        'budget_limit_cny': getattr(args, 'budget_limit_cny', 5)})
    try:
        await _run_model(args, cfg, output, tools, symptom_override, record)
    except BaseException as exc:
        record.finish('failed', type(exc).__name__)
        raise
    else:
        summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
        record.finish('completed' if summary.get('workflow_completed') is True else 'incomplete')


async def _run_model(args, cfg, output, tools, symptom_override, record):
    if getattr(args, 'mechanism_group', None) and getattr(args, 'knowledge_disabled', False):
        raise ValueError('mechanism groups require unchanged knowledge conditions')
    limit_cny = getattr(args, 'budget_limit_cny', 5)
    previous = read_cost_ledger(args.previous_cost, for_resume=True, limit_cny=limit_cny) if args.previous_cost else None
    from scripts.knowledge_conditions import check_knowledge_conditions
    manifest = getattr(args, 'knowledge_manifest', None)
    knowledge_audit = None
    if manifest:
        knowledge_audit = check_knowledge_conditions(manifest, args.local_runbooks, output, args.knowledge_mcp_url, 'before')
    import httpx
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
    from src.settings import settings
    from src.agent.aiops_llm import create_agent_llm as factory
    from src.agent.aiops.graph import AIOpsService
    from src.probe.protocol import redact
    if getattr(args, 'knowledge_disabled', False):
        args.local_runbooks = None
        args.knowledge_mcp_url = None
        tools = [t for t in tools if t.name not in {'search_knowledge_base', 'list_knowledge_bases', 'get_document_info'}]
    if getattr(args, 'isolate_history', False):
        tools = [t for t in tools if t.name != 'probe_list_evidence']

    settings.PROBE_ENABLED = True
    settings.PROBE_TARGET_ID = cfg.target_id
    settings.DIAGNOSTIC_TARGET_CATALOG = business_catalog(cfg) if 'localapp' in cfg.dependencies else target_catalog(cfg)
    settings.PROBE_EVIDENCE_DIR = str(output / 'evidence')
    settings.TERMCP_ENABLED = False
    settings.ENABLE_HITL = False
    settings.ENABLE_LLM_RETRY = False
    group = getattr(args, 'mechanism_group', None)
    expected_config = configure_mechanisms(group)
    run_limit = getattr(args, 'run_budget_cny', None)
    max_output_tokens = getattr(args, 'max_output_tokens', 4096)
    allow_unpriced_model = bool(getattr(args, 'allow_unpriced_model', False))
    max_model_requests = getattr(args, 'max_model_requests', None)
    budget = PaidRequestBudget(output, max_output_tokens=max_output_tokens, limit_cny=limit_cny,
        run_limit_cny=run_limit, allow_unpriced_models=allow_unpriced_model,
        max_requests=max_model_requests)
    budget_stopped = False
    if previous is not None:
        budget.reserved = previous['reserved_cny']
        budget.ledger = previous['requests']
        budget.inherited_reserved = previous['reserved_cny']
        budget.blocked_requests = previous.get('blocked_requests', [])
    prior_requests = len(budget.ledger)
    budget_stop_reason = None
    record.value['config'].update(mechanisms=expected_config, business_catalog=json.loads(settings.DIAGNOSTIC_TARGET_CATALOG),
        retry={'sdk_max_retries': 0, 'agent_retry_enabled': settings.ENABLE_LLM_RETRY,
            'structured_format_fallback': True, 'request_relation': 'not inferred; each HTTP attempt recorded separately'},
        probe_allowlist={'services': {key: asdict(value) for key, value in cfg.services.items()},
            'dependencies': {key: asdict(value) for key, value in cfg.dependencies.items()}},
        tool_names=[tool.name for tool in tools], limited_evidence=getattr(args, 'limited_evidence', False),
        knowledge_disabled=getattr(args, 'knowledge_disabled', False), max_output_tokens=max_output_tokens)
    record.value['config'].update(run_budget_cny=run_limit, http_timeout_seconds=60,
        observation_not_before=getattr(args, 'observation_not_before', None),
        shared_history_enabled=not getattr(args, 'isolate_history', False))
    record.save()

    class BudgetTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport()
        async def handle_async_request(self, request):
            nonlocal budget_stopped, budget_stop_reason
            allowed_host = 'api.deepseek.com'
            if allow_unpriced_model:
                from urllib.parse import urlsplit
                allowed_host = urlsplit(settings.RESOLVED_LLM_API_BASE).hostname
            if request.url.host != allowed_host or not request.url.path.endswith('/chat/completions'):
                raise RuntimeError('Evaluation permits only the explicitly configured model endpoint')
            body = json.loads(await request.aread())
            input_dir = output / 'model-inputs'
            input_dir.mkdir(exist_ok=True)
            try:
                row = budget.reserve(body)
            except EvaluationBudgetExceeded as error:
                budget_stopped = True
                budget_stop_reason = error.reason_code
                blocked = input_dir / ('blocked-' + uuid4().hex + '.json')
                blocked.write_text(json.dumps(redact(body), ensure_ascii=False, indent=2), encoding='utf-8')
                record.value.setdefault('blocked_requests', []).append({
                    'input_file': blocked.relative_to(output).as_posix(), 'at': utc_now(),
                    'sent': False, 'reason_code': error.reason_code, 'reason': str(error)})
                record.save()
                return httpx.Response(402, request=request, json={'error': {
                    'message': str(error), 'type': 'evaluation_budget_exceeded',
                    'code': error.reason_code}})
            input_path = input_dir / (str(row['number']) + '.json')
            input_path.write_text(json.dumps(redact(body), ensure_ascii=False, indent=2), encoding='utf-8')
            row.update(input_file=input_path.relative_to(output).as_posix(),
                input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest())
            revised = httpx.Request(request.method, request.url,
                headers={k: v for k, v in request.headers.items() if k.lower() != 'content-length'},
                content=json.dumps(body).encode(), extensions=request.extensions)
            from scripts.model_request_diagnostics import record_model_response
            return await record_model_response(self.inner, revised, row, budget.save)
        async def aclose(self):
            await self.inner.aclose()

    http = httpx.AsyncClient(transport=BudgetTransport(), timeout=60)
    def bounded_factory(**kwargs):
        llm = factory(**kwargs)
        llm.max_tokens = max_output_tokens
        # ChatOpenAI keeps retry state on the underlying OpenAI clients;
        # changing only the wrapper attribute leaves the SDK default (2).
        llm.max_retries = 0
        for client_name in ('root_async_client', 'root_client'):
            client = getattr(llm, client_name, None)
            if client is not None:
                client.max_retries = 0
        llm.http_async_client = http
        llm.root_async_client._client = http
        return llm
    for module in ('planner', 'executor', 'strategies.investigation'):
        importlib.import_module('src.agent.aiops.' + module).create_agent_llm = bounded_factory
    trace = []
    wrapped = trace_evaluation_tools(tools, cfg.target_id, output, trace,
        getattr(args, 'observation_not_before', None))
    if getattr(args, 'limited_evidence', False):
        from langchain_core.tools import StructuredTool
        narrowed = []
        for candidate in wrapped:
            if candidate.name == 'probe_text_log':
                continue
            if candidate.name == 'probe_dependency_probe':
                original = candidate
                async def entry_only(dependency: str):
                    if dependency != 'localapp':
                        raise PermissionError('This observation is unavailable in the current run')
                    return await original.ainvoke({'dependency': dependency})
                candidate = StructuredTool.from_function(coroutine=entry_only, name=original.name,
                    description=original.description, args_schema=original.args_schema)
            narrowed.append(candidate)
        wrapped = narrowed
    async def tool_loader(*args, **kwargs):
        return wrapped, None
    for module in ('planner', 'executor'):
        importlib.import_module('src.agent.aiops.' + module).load_agent_tools = tool_loader
    executor = importlib.import_module('src.agent.aiops.executor')
    executor._tools_cache.clear()
    executor._tools_cache_at.clear()
    knowledge_stack = ExitStack()
    if args.local_runbooks:
        retrieve = knowledge_stack.enter_context(local_runbook_retrieval(args.local_runbooks, output))
        knowledge_stack.enter_context(patch.object(importlib.import_module('src.agent.aiops.planner'),
            '_retrieve_experience', retrieve))
    service = AIOpsService()
    events = []
    symptom = ('只读验收这台 Windows 电脑的运行概况，没有预设故障。请自主选择检查，'
        '核实资源、允许查询的系统服务、进程和端口，并按证据决定是否需要补查。'
        '不要修改或重启。结论只覆盖实际看到的范围；部分或截断快照不能证明所有业务正常。'
        '报告实际数值、目标、采集时间、证据引用，以及缺失数据和无法排除的解释。'
        '服务清单之外的服务、完整进程路径、完整端口普查不在此次可检查范围；'
        '如工具无相应能力，应明确 unavailable，不反复请求同样数据。')
    if symptom_override:
        symptom = symptom_override
    scenario = 'provided_symptom' if args.symptom_file else 'local_overview'
    try:
        print(json.dumps({'stage': 'started', 'scenario': scenario, 'output': str(output)}), flush=True)
        execution_error = None
        try:
            async for event in service.execute(symptom, session_id='windows-overview', user_id=1, terminal_enabled=False):
                events.append(event)
                (output / 'events.json').write_text(json.dumps(redact(events), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
                print(json.dumps({'stage': event.get('type'), 'paid_requests': len(budget.ledger),
                                  'reserved_cny': budget.reserved}), flush=True)
        except Exception as exc:
            execution_error = type(exc).__name__
            events.append({'type': 'error', 'stage': 'evaluation_execution_failed', 'exception_type': execution_error})
            (output / 'events.json').write_text(json.dumps(redact(events), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        final = next((e.get('response') or e.get('report') for e in reversed(events)
                      if e.get('type') in {'complete', 'report', 'error'} and (e.get('response') or e.get('report'))), '')
        diagnosis = next((e['diagnosis'] for e in reversed(events) if e.get('diagnosis')), None)
        failure = next((e['investigation_failure'] for e in reversed(events) if e.get('investigation_failure')), None)
        workflow_completed = (bool(final) and any(e.get('type') == 'complete' for e in events)
            and not failure and not execution_error and not budget_stopped
            and not any(e.get('type') == 'error' for e in events))
        thread_id = next((e.get('thread_id') for e in reversed(events) if e.get('thread_id')), None)
        mechanism_audit = await save_mechanism_audit(service, thread_id, expected_config, output)
        if manifest:
            knowledge_audit = check_knowledge_conditions(manifest, args.local_runbooks, output, args.knowledge_mcp_url, 'after')
        (output / 'report.txt').write_text(final, encoding='utf-8')
        summary = {'scenario': scenario, 'scenarios_in_this_process': 1,
            'tool_calls': [t['tool'] for t in trace], 'validated_live_returns': sum(t['validated_live_evidence'] for t in trace),
            'has_final_report': bool(final), 'report_kind': classify_report(final, diagnosis), 'diagnosis': diagnosis,
            'workflow_completed': workflow_completed, 'investigation_failure': failure,
            'error_events': sum(event.get('type') == 'error' for event in events),
            'requires_manual_review': bool(final), 'model_requests': len(budget.ledger),
            'budget_stopped': budget_stopped, 'budget_stop_reason': budget_stop_reason,
            'mechanism_group': group, 'mechanism_audit': mechanism_audit,
            'knowledge_conditions': knowledge_audit,
            'execution_error': execution_error,
            'reserved_cny': budget.reserved, 'actual_estimated_cny_peak': budget.actual_cost_cny(),
            'limit_cny': limit_cny, 'knowledge_base_evaluated': False, 'fault_location_evaluated': False,
            'previous_cost': str(args.previous_cost) if args.previous_cost else None,
            'evaluation_record': 'evaluation-record.json',
            'cost_scope': {'cumulative': budget.cost_summary(), 'this_run': budget.cost_summary(prior_requests)},
            'knowledge_mode': 'local_bm25_mcp' if args.knowledge_mcp_url else ('local_runbooks' if args.local_runbooks else 'disabled'),
            'knowledge_mcp_calls': sum(t['tool'] == 'search_knowledge_base' for t in trace),
            'vector_rag_evaluated': False}
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if group is not None and (not mechanism_audit['passed']
                or mechanism_audit.get('behavior', {}).get('status') != 'passed'):
            raise RuntimeError('Mechanism configuration/behavior audit failed; artifacts preserved')
    finally:
        budget.save()
        try:
            await service.close()
        finally:
            try:
                await http.aclose()
            finally:
                knowledge_stack.close()


if __name__ == '__main__':
    asyncio.run(main())
