"""Local, credential-free provenance and timing for the Windows evaluation runner."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess
import time
import math
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def validate_timing(row):
    start = datetime.fromisoformat(row['started_at'])
    end = datetime.fromisoformat(row['ended_at'])
    elapsed = row['elapsed_ms']
    if (start.tzinfo is None or end.tzinfo is None or end < start
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
        raise ValueError('invalid or incomplete timing')


def source_snapshot(root, output):
    root, output = Path(root), Path(output)
    # Only program sources/dependency declarations, never .env, data or runtime.
    paths = {p for folder in ('src', 'mcp_servers') for p in (root / folder).rglob('*.py')}
    paths.update(root / name for name in (
        'scripts/evaluate_windows_probe.py', 'scripts/evaluate_autonomous_investigation.py',
        'scripts/verify_windows_local_faults.py', 'scripts/evaluation_record.py',
        'scripts/model_request_diagnostics.py',
        'scripts/replay_model_request.py',
        'scripts/mechanism_behavior.py', 'scripts/knowledge_conditions.py',
        'scripts/windows_probe.py', 'scripts/verify_windows_probe_graph.py',
        'scripts/with_agent_test_env.py', 'scripts/audit_configuration.py',
        'requirements.txt', 'pyproject.toml', 'uv.lock', 'poetry.lock'))
    sources = {}
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        saved = output / 'source-snapshot' / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(data)
        sources[relative] = hashlib.sha256(data).hexdigest()
    git = {}
    for key, args in (('head', ['rev-parse', 'HEAD']), ('branch', ['branch', '--show-current'])):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=False)
        git[key] = result.stdout.strip() if result.returncode == 0 else None
    packages = {}
    for name in ('langgraph', 'langchain-openai', 'httpx', 'fastmcp', 'pydantic', 'rank-bm25'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {'git': git, 'sources': sources, 'python': platform.python_version(),
        'packages': packages, 'scope': 'selected evaluation sources; excludes credentials, runtime data and OS state'}


class EvaluationRecord:
    def __init__(self, root, output, config):
        self.output = Path(output)
        self.started = time.perf_counter()
        self.value = {'version': 1, 'started_at': utc_now(), 'ended_at': None,
            'elapsed_ms': None, 'status': 'started', 'config': config,
            'timing_scope': 'run_model entry through cleanup; excludes controller injection and MCP connection setup',
            'source': source_snapshot(root, output)}
        self.save()

    def save(self):
        self.value['config_sha256'] = hashlib.sha256(json.dumps(
            self.value['config'], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        (self.output / 'evaluation-record.json').write_text(
            json.dumps(self.value, ensure_ascii=False, indent=2), encoding='utf-8')

    def finish(self, status, error=None):
        self.value.update(status=status, ended_at=utc_now(),
            elapsed_ms=(time.perf_counter() - self.started) * 1000, error_type=error)
        self.save()


def audit_evaluation(directory, *, expected_root=None, previous=None):
    """Read-only integrity gate; passing never grades diagnostic correctness."""
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget
    from scripts.evaluate_windows_probe import read_cost_ledger, MECHANISM_GROUPS
    directory = Path(directory).resolve()
    issues = []
    def fail(message):
        issues.append(message)
    def local(base, name):
        path = (base / name).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError('artifact path escapes directory')
        return path
    def load(name):
        return json.loads(local(directory, name).read_text(encoding='utf-8'))
    result = {'passed': False, 'issues': issues, 'legacy': not (directory / 'evaluation-record.json').exists(),
        'diagnostic_correctness_verified': False, 'source_signature': None, 'comparison_config': None,
        'this_run_cost': None, 'duration_ms': None}
    try:
        record, summary = load('evaluation-record.json'), load('summary.json')
        if record.get('version') != 1 or record.get('status') != 'completed':
            fail('evaluation lifecycle not completed')
        validate_timing(record)
        config = record['config']
        encoded = json.dumps(config, ensure_ascii=False, sort_keys=True).encode('utf-8')
        if hashlib.sha256(encoded).hexdigest() != record['config_sha256']:
            fail('configuration fingerprint mismatch')
        group, mechanism = config.get('mechanism_group'), config.get('mechanisms', {})
        if group != summary.get('mechanism_group'):
            fail('summary group differs from runtime')
        if group is not None:
            audit = summary.get('mechanism_audit') or {}
            trace_audit = load('mechanism_trace.json').get('audit')
            if trace_audit != audit:
                fail('mechanism trace and summary disagree')
            if (group not in MECHANISM_GROUPS or (mechanism.get('hypothesis_protection'),
                    mechanism.get('contradiction_trigger')) != MECHANISM_GROUPS.get(group)
                    or audit.get('expected_config') != mechanism or audit.get('actual_config') != mechanism
                    or audit.get('passed') is not True or audit.get('behavior', {}).get('status') != 'passed'):
                fail('mechanism configuration or behavior not verified')
        if record.get('error_type') or summary.get('evaluation_record') != 'evaluation-record.json':
            fail('record error or summary binding missing')
        sources = record['source']['sources']
        required = {'scripts/evaluate_windows_probe.py', 'scripts/evaluation_record.py',
            'scripts/evaluate_autonomous_investigation.py', 'scripts/verify_windows_local_faults.py',
            'src/agent/aiops/strategies/investigation.py', 'src/settings.py'}
        if not required <= sources.keys():
            fail('required source snapshot missing')
        snapshot = directory / 'source-snapshot'
        for name, expected in sources.items():
            data = local(snapshot, name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                fail('source snapshot hash mismatch: ' + name)
            if expected_root is not None and hashlib.sha256(local(Path(expected_root), name).read_bytes()).hexdigest() != expected:
                fail('source differs from controller workspace: ' + name)
        if set(sources) != {p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()}:
            fail('source manifest and snapshot file set differ')
        cost = read_cost_ledger(directory / 'cost.json')
        if previous is None and config.get('previous_cost'):
            previous = read_cost_ledger(config['previous_cost'])
        prior = (previous or {}).get('requests', [])
        if cost['requests'][:len(prior)] != prior:
            fail('prior ledger prefix changed')
        budget = PaidRequestBudget(directory, limit_cny=cost['limit_cny'])
        budget.ledger = cost['requests']
        scopes = {'cumulative': budget.cost_summary(), 'this_run': budget.cost_summary(len(prior))}
        if summary.get('cost_scope') != scopes:
            fail('cost scopes disagree with ledger')
        if (summary.get('previous_cost') != config.get('previous_cost')
                or summary.get('actual_estimated_cny_peak') != scopes['cumulative']['estimated_cny_peak']):
            fail('cost lineage or estimated total differs')
        if (summary.get('reserved_cny') != cost['reserved_cny']
                or summary.get('model_requests') != len(cost['requests'])
                or config.get('budget_limit_cny') != cost['limit_cny']):
            fail('summary budget differs from ledger')
        if scopes['this_run']['requests'] <= 0 or scopes['cumulative']['usage_unknown_requests']:
            fail('no new requests or uncertain usage')
        run_cap = config.get('run_budget_cny')
        if run_cap is not None and (type(run_cap) not in (int, float) or not math.isfinite(run_cap)
                or run_cap <= 0 or scopes['this_run']['reserved_cny'] > run_cap + 1e-9):
            fail('per-run reservation cap invalid or exceeded')
        inputs, models = set(), []
        for row in cost['requests'][len(prior):]:
            validate_timing(row)
            name = row['input_file']
            if name in inputs:
                fail('model input reused across requests')
            inputs.add(name)
            body = load(name)
            if hashlib.sha256(local(directory, name).read_bytes()).hexdigest() != row.get('input_sha256'):
                fail('model input fingerprint mismatch')
            if body.get('model') != row.get('model') or body.get('max_tokens') != row.get('output_token_upper'):
                fail('model request metadata disagrees with input')
            if row.get('status') != 'returned' or not row.get('served_model'):
                fail('model response metadata incomplete')
            models.append({k: body.get(k) for k in ('model', 'temperature', 'top_p', 'max_tokens',
                'stream', 'thinking', 'reasoning_effort', 'seed', 'presence_penalty', 'frequency_penalty')})
            models[-1]['served_model'] = row['served_model']
        trace = load('tool_trace.json')
        boundary = config.get('observation_not_before')
        if config.get('shared_history_enabled') is False and not boundary:
            fail('isolated run missing observation boundary')
        if boundary:
            start = datetime.fromisoformat(boundary.replace('Z', '+00:00'))
            if start.tzinfo is None or start > datetime.fromisoformat(record['started_at']):
                fail('observation boundary must precede run entry')
            if 'probe_list_evidence' in config.get('tool_names', []):
                fail('shared history available in bounded run')
        for row in trace:
            validate_timing(row)
            if row.get('status') not in {'returned', 'failed'}:
                fail('tool attempt unfinished')
            if boundary:
                from src.probe.evidence import PROBE_TOOL_OPERATIONS, validate_tool_evidence, validate_observation_window
                if row.get('tool') in PROBE_TOOL_OPERATIONS and row.get('status') == 'returned':
                    item = validate_tool_evidence(row.get('result'), tool_name=row['tool'],
                        target_id=config['target_id'], now=datetime.fromisoformat(row['ended_at']))
                    validate_observation_window(item, boundary)
                    if row.get('validated_live_evidence') is not True:
                        fail('bounded Probe return not validated')
        if not trace or summary.get('tool_calls') != [row['tool'] for row in trace]:
            fail('tool trace missing or disagrees with summary')
        events = load('events.json')
        complete = next((e for e in reversed(events) if e.get('type') == 'complete'), {})
        if (not complete.get('response') or any(e.get('type') == 'error' or e.get('investigation_failure') for e in events)
                or local(directory, 'report.txt').read_text(encoding='utf-8') != complete['response']):
            fail('report and completed event disagree')
        if (not summary.get('has_final_report') or summary.get('workflow_completed') is False
                or any(summary.get(k) for k in ('error_events', 'execution_error', 'budget_stopped', 'investigation_failure'))):
            fail('summary workflow incomplete')
        comparable = dict(config)
        comparable.pop('previous_cost', None)
        comparable.pop('mechanism_group', None)
        comparable.pop('observation_not_before', None)
        comparable['mechanisms'] = {k: v for k, v in mechanism.items() if k not in {'hypothesis_protection', 'contradiction_trigger'}}
        comparable['model_parameters'] = sorted({json.dumps(m, sort_keys=True) for m in models})
        comparable['knowledge_mode'] = summary.get('knowledge_mode')
        knowledge = summary.get('knowledge_conditions') or {}
        if summary.get('knowledge_mode') != 'disabled':
            before, after = load('knowledge-conditions-before.json'), load('knowledge-conditions-after.json')
            if (not before.get('passed') or not after.get('passed') or knowledge != after
                    or not before.get('actual_sha256') or before.get('actual_sha256') != after.get('actual_sha256')
                    or before.get('expected_sha256') != before.get('actual_sha256')
                    or after.get('expected_sha256') != after.get('actual_sha256')):
                fail('knowledge conditions not verified')
            comparable['knowledge_sha256'] = after.get('actual_sha256')
        result.update(source_signature=record['source'], comparison_config=comparable, observation_not_before=boundary,
            this_run_cost=scopes['this_run'], duration_ms=record['elapsed_ms'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        fail('artifact unavailable or invalid: ' + type(exc).__name__)
    result['passed'] = not issues
    return result
