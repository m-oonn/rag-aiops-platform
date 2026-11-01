import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluation_record import EvaluationRecord, audit_evaluation
from scripts.evaluate_autonomous_investigation import PaidRequestBudget
from scripts.summarize_evaluations import summarize


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture
def artifacts(tmp_path):
    root, source = tmp_path / 'repo', tmp_path / 'runs'
    source.mkdir()
    for name in ['scripts/evaluate_windows_probe.py', 'scripts/evaluation_record.py',
            'scripts/evaluate_autonomous_investigation.py', 'scripts/verify_windows_local_faults.py',
            'src/agent/aiops/strategies/investigation.py', 'src/settings.py']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# source fixture\n')
    def build(group='G00', directory=None):
        from scripts.evaluate_windows_probe import MECHANISM_GROUPS
        directory = directory or source / group
        directory.mkdir()
        switches = MECHANISM_GROUPS.get(group, (False, False))
        config = {'mechanism_group': group, 'mechanisms': {'hypothesis_protection': switches[0],
            'contradiction_trigger': switches[1], 'protection_steps': 2},
            'budget_limit_cny': 5, 'tool_names': ['probe_dependency_probe']}
        record = EvaluationRecord(root, directory, config)
        record.finish('completed')
        timing = {k: record.value[k] for k in ['started_at', 'ended_at', 'elapsed_ms']}
        save(directory.parent / ('model-attempt-' + directory.name + '.json'), {
            'result_dir': str(directory.resolve()), 'case': 'case', 'mechanism_group': group,
            'status': 'returned', 'exit_code': 0, **timing})
        (directory / 'model-inputs').mkdir()
        save(directory / 'model-inputs/1.json', {'model': 'deepseek-flash', 'max_tokens': 10})
        budget = PaidRequestBudget(directory)
        budget.ledger = [{'number': 1, 'reserved_cny': 0.2, 'model': 'deepseek-flash',
            'output_token_upper': 10, 'input_file': 'model-inputs/1.json',
            'input_sha256': hashlib.sha256((directory / 'model-inputs/1.json').read_bytes()).hexdigest(),
            'http_status': 200, 'status': 'returned', 'served_model': 'served-test',
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}, **timing}]
        budget.reserved = 0.2
        budget.save()
        summary = {'scenario': 'case', 'mechanism_group': group,
            'evaluation_record': 'evaluation-record.json', 'has_final_report': True, 'report_kind': 'unlocated',
            'knowledge_mode': 'disabled', 'tool_calls': ['probe_dependency_probe'],
            'model_requests': 1, 'reserved_cny': 0.2,
            'actual_estimated_cny_peak': budget.actual_cost_cny(),
            'mechanism_audit': {'passed': True, 'behavior': {'status': 'passed'},
                'actual_config': config['mechanisms'], 'expected_config': config['mechanisms']},
            'cost_scope': {'cumulative': budget.cost_summary(), 'this_run': budget.cost_summary()}}
        save(directory / 'summary.json', summary)
        save(directory / 'mechanism_trace.json', {'audit': summary['mechanism_audit']})
        save(directory / 'tool_trace.json', [{'tool': 'probe_dependency_probe', 'status': 'returned', **timing}])
        save(directory / 'events.json', [{'type': 'complete', 'response': '未定位根因：fixture'}])
        (directory / 'report.txt').write_text('未定位根因：fixture', encoding='utf-8')
        return directory
    return root, source, build


@pytest.mark.parametrize('mutation', ['none', 'summary_limit', 'inherited_count', 'exceeded', 'unpriced_rate'])
def test_request_limit_audit_uses_ledger_and_configuration(artifacts, mutation):
    _, _, build = artifacts
    directory = build()
    record = json.loads((directory / 'evaluation-record.json').read_text())
    record['config'].update(max_model_requests=2, run_max_model_requests=2, allow_unpriced_model=False)
    summary = json.loads((directory / 'summary.json').read_text())
    cost = json.loads((directory / 'cost.json').read_text())
    limits = {'max_requests': 2, 'run_max_requests': 2, 'inherited_requests': 0}
    cost['request_limits'] = dict(limits)
    summary['request_limits'] = dict(limits)
    if mutation == 'summary_limit':
        summary['request_limits']['run_max_requests'] = 3
    elif mutation == 'inherited_count':
        cost['request_limits']['inherited_requests'] = 1
    elif mutation == 'exceeded':
        record['config']['run_max_model_requests'] = 0
        cost['request_limits']['run_max_requests'] = summary['request_limits']['run_max_requests'] = 0
    elif mutation == 'unpriced_rate':
        record['config']['allow_unpriced_model'] = True
    record['config_sha256'] = hashlib.sha256(json.dumps(record['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(directory / 'evaluation-record.json', record)
    save(directory / 'cost.json', cost)
    save(directory / 'summary.json', summary)
    result = audit_evaluation(directory)
    assert result['passed'] is (mutation == 'none'), result['issues']


@pytest.mark.parametrize('mutation', ['none', 'missing_record', 'config_hash', 'source_hash',
    'missing_source', 'unfinished_time', 'invalid_elapsed', 'cumulative_as_current',
    'missing_input', 'unfinished_tool', 'changed_report', 'escape_source', 'unknown_usage',
    'failed_summary', 'failed_event'])
def test_integrity_rejects_incomplete_or_changed_artifacts(artifacts, mutation):
    root, source, build = artifacts
    directory = build()
    record = json.loads((directory / 'evaluation-record.json').read_text(encoding='utf-8'))
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    if mutation == 'missing_record':
        (directory / 'evaluation-record.json').unlink()
    elif mutation == 'config_hash':
        record['config']['budget_limit_cny'] = 10
    elif mutation == 'source_hash':
        (directory / 'source-snapshot/src/settings.py').write_text('changed')
    elif mutation == 'missing_source':
        record['source']['sources'].pop('src/settings.py')
    elif mutation == 'unfinished_time':
        record['ended_at'] = None
    elif mutation == 'invalid_elapsed':
        record['elapsed_ms'] = True
    elif mutation == 'cumulative_as_current':
        summary['cost_scope']['this_run']['requests'] = 2
    elif mutation == 'missing_input':
        (directory / 'model-inputs/1.json').unlink()
    elif mutation == 'unfinished_tool':
        save(directory / 'tool_trace.json', [{'tool': 'probe_dependency_probe', 'status': 'started'}])
    elif mutation == 'changed_report':
        (directory / 'report.txt').write_text('changed')
    elif mutation == 'failed_summary':
        summary['workflow_completed'] = False
        summary['investigation_failure'] = {'code': 'model_request_failed'}
    elif mutation == 'failed_event':
        save(directory / 'events.json', [{'type': 'complete', 'response': '未定位根因：fixture',
            'investigation_failure': {'code': 'model_request_failed'}}])
    elif mutation == 'escape_source':
        record['source']['sources']['../../outside.py'] = 'hash'
    elif mutation == 'unknown_usage':
        cost = json.loads((directory / 'cost.json').read_text())
        cost['requests'][0]['usage'] = {}
        save(directory / 'cost.json', cost)
    if mutation != 'missing_record':
        save(directory / 'evaluation-record.json', record)
    save(directory / 'summary.json', summary)
    result = audit_evaluation(directory, expected_root=root)
    assert result['passed'] is (mutation == 'none'), result
    assert result['diagnostic_correctness_verified'] is False
    if mutation == 'missing_record':
        assert result['legacy'] is True


def test_failed_request_without_served_model_does_not_hide_later_audit_issues(artifacts):
    root, _, build = artifacts
    directory = build()
    cost = json.loads((directory / 'cost.json').read_text())
    cost['requests'][0].pop('served_model')
    cost['requests'][0]['status'] = 'ConnectError'
    save(directory / 'cost.json', cost)
    trace = json.loads((directory / 'tool_trace.json').read_text())
    trace[0]['status'] = 'started'
    save(directory / 'tool_trace.json', trace)

    result = audit_evaluation(directory, expected_root=root)

    assert result['passed'] is False
    assert 'model response metadata incomplete' in result['issues']
    assert 'tool attempt unfinished' in result['issues']
    assert not any('KeyError' in issue for issue in result['issues'])


@pytest.mark.parametrize('mutation', ['none', 'scope_empty', 'scope_bool', 'wrong_call',
    'missing_call_id', 'wrong_schema', 'missing_schema_enum'])
def test_integrity_verifies_recorded_and_advertised_knowledge_scope(artifacts, mutation):
    root, _, build = artifacts
    directory = build()
    record = json.loads((directory / 'evaluation-record.json').read_text(encoding='utf-8'))
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    timing = {key: record[key] for key in ('started_at', 'ended_at', 'elapsed_ms')}
    record['config']['knowledge_kb_ids'] = [14]
    record['config']['tool_names'].append('search_knowledge_base')
    kb_schema = {'type': 'integer', 'enum': [14], 'default': 14}
    arguments = {'query': 'x', 'kb_id': 14}
    if mutation == 'scope_empty':
        record['config']['knowledge_kb_ids'] = []
    elif mutation == 'scope_bool':
        record['config']['knowledge_kb_ids'] = [True]
    elif mutation == 'wrong_call':
        arguments['kb_id'] = 1
    elif mutation == 'missing_call_id':
        arguments.pop('kb_id')
    elif mutation == 'wrong_schema':
        kb_schema['enum'] = [1]
    elif mutation == 'missing_schema_enum':
        kb_schema.pop('enum')
    summary['knowledge_mode'] = 'local_bm25_mcp'
    summary['tool_calls'].append('search_knowledge_base')
    knowledge = {'passed': True, 'actual_sha256': 'fixture', 'expected_sha256': 'fixture'}
    for phase in ('before', 'after'):
        save(directory / ('knowledge-conditions-' + phase + '.json'), {**knowledge, 'phase': phase})
    summary['knowledge_conditions'] = {**knowledge, 'phase': 'after'}
    trace = json.loads((directory / 'tool_trace.json').read_text(encoding='utf-8'))
    trace.append({'tool': 'search_knowledge_base', 'arguments': arguments, 'status': 'returned', **timing})
    save(directory / 'tool_trace.json', trace)
    body = json.loads((directory / 'model-inputs/1.json').read_text(encoding='utf-8'))
    body['tools'] = [{'type': 'function', 'function': {'name': 'search_knowledge_base',
        'parameters': {'properties': {'kb_id': kb_schema}}}}]
    save(directory / 'model-inputs/1.json', body)
    cost = json.loads((directory / 'cost.json').read_text(encoding='utf-8'))
    cost['requests'][0]['input_sha256'] = hashlib.sha256((directory / 'model-inputs/1.json').read_bytes()).hexdigest()
    save(directory / 'cost.json', cost)
    record['config_sha256'] = hashlib.sha256(json.dumps(record['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(directory / 'evaluation-record.json', record)
    save(directory / 'summary.json', summary)
    result = audit_evaluation(directory, expected_root=root)
    assert result['passed'] is (mutation == 'none'), result


@pytest.mark.parametrize('mutation', ['none', 'missing_group', 'different_source', 'different_config', 'legacy',
    'missing_controller', 'malformed_controller', 'missing_controller_time', 'failed_suite', 'unrecovered_suite'])
def test_summary_only_compares_complete_matching_four_groups(artifacts, mutation):
    root, source, build = artifacts
    for group in ['G00', 'G10', 'G01', 'G11']:
        if mutation == 'missing_group' and group == 'G11':
            continue
        build(group)
    directory = source / 'G11'
    if mutation in {'different_source', 'different_config'}:
        path = directory / 'evaluation-record.json'
        record = json.loads(path.read_text())
        if mutation == 'different_source':
            saved = directory / 'source-snapshot/src/settings.py'
            saved.write_text('# changed source')
            record['source']['sources']['src/settings.py'] = hashlib.sha256(saved.read_bytes()).hexdigest()
        else:
            record['config']['mechanisms']['protection_steps'] = 3
            summary = json.loads((directory / 'summary.json').read_text())
            for key in ['actual_config', 'expected_config']:
                summary['mechanism_audit'][key]['protection_steps'] = 3
            save(directory / 'summary.json', summary)
            save(directory / 'mechanism_trace.json', {'audit': summary['mechanism_audit']})
            record['config_sha256'] = hashlib.sha256(json.dumps(record['config'],
                ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        save(path, record)
    if mutation == 'legacy':
        (directory / 'evaluation-record.json').unlink()
    if mutation == 'missing_controller':
        (source / 'model-attempt-G11.json').unlink()
    if mutation == 'malformed_controller':
        (source / 'model-attempt-G11.json').write_text('invalid')
    if mutation == 'missing_controller_time':
        path = source / 'model-attempt-G11.json'
        attempt = json.loads(path.read_text())
        attempt['ended_at'] = None
        save(path, attempt)
    if mutation in {'failed_suite', 'unrecovered_suite'}:
        save(source / 'four-group-controller.json', {'status': 'failed' if mutation == 'failed_suite' else 'completed',
            'recovery': 'pending', 'order': [], 'resets': [], 'results': []})
    result = summarize(source, source.parent / 'summary')
    assert result['passed'] is (mutation == 'none')
    assert all((row['vs_G00'] is not None) == (mutation == 'none') for row in result['runs'])
    assert result['human_reviewed'] == 0 and result['diagnostic_accuracy'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['legacy', 'isolated', 'lost_history', 'wrong_boundary'])
@pytest.mark.parametrize('missing', [False, True])
async def test_controller_uses_real_record_gate_and_rejects_missing_record(artifacts, monkeypatch, missing, isolation):
    from scripts import verify_windows_local_faults as controller
    root, source, build = artifacts
    monkeypatch.setattr(controller, 'ROOT', root)
    options = {} if isolation == 'legacy' else {'isolate_history': True,
        'observation_not_before': '2026-10-01T00:00:00+00:00'}
    def launch(args, name):
        output = Path(args[args.index('--output-dir') + 1])
        build(None, output)
        if options:
            assert '--isolate-history' in args
            assert args[args.index('--observation-not-before') + 1] == options['observation_not_before']
            path = output / 'evaluation-record.json'
            record = json.loads(path.read_text())
            record['config'].update(shared_history_enabled=isolation == 'lost_history', target_id='windows-local-01',
                observation_not_before=('2026-10-02T00:00:00+00:00' if isolation == 'wrong_boundary'
                    else options['observation_not_before']))
            record['config_sha256'] = hashlib.sha256(json.dumps(record['config'],
                ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
            save(path, record)
            trace_path = output / 'tool_trace.json'
            trace = json.loads(trace_path.read_text())
            trace[0]['validated_live_evidence'] = True
            from src.probe.protocol import evidence
            trace[0]['result'] = evidence(target_id='windows-local-01', operation='dependency_probe',
                payload={'dependency': 'localapp'}, collected_at=trace[0]['ended_at'])
            save(trace_path, trace)
        if missing:
            (output / 'evaluation-record.json').unlink()
        return SimpleNamespace(wait=lambda: 0)
    if missing:
        with pytest.raises(RuntimeError, match='record integrity failed'):
            await controller.evaluate_model_case(source, 'normal', launch, **options)
    elif isolation in {'lost_history', 'wrong_boundary'}:
        with pytest.raises(RuntimeError, match='did not preserve observation isolation'):
            await controller.evaluate_model_case(source, 'normal', launch, **options)
    else:
        result = await controller.evaluate_model_case(source, 'normal', launch, **options)
        assert result['record_integrity']['passed']
        assert result['diagnostic_correctness_verified'] is False
    result = json.loads(next(source.glob('model-*/record-integrity.json')).read_text())
    assert result['passed'] is (not missing) and result['legacy'] is missing


@pytest.mark.asyncio
@pytest.mark.parametrize('suite', ['baseline-v1', 'mechanism-v1'])
@pytest.mark.parametrize('unpriced', [False, True, 'priced_requests'])
async def test_four_group_orchestration_consumes_real_child_gate_and_summary(artifacts, monkeypatch, suite, unpriced):
    request_caps = bool(unpriced)
    unpriced = unpriced is True
    import sqlite3
    from scripts import verify_windows_local_faults as controller, knowledge_conditions
    root, source, build = artifacts
    monkeypatch.setattr(controller, 'ROOT', root)
    (source / 'runbooks').mkdir()
    (source / 'runbooks/guide.md').write_text('fixed fixture guide')
    (source / 'config.toml').write_text('fixed fixture allowlist')
    (source / 'knowledge-manifest.json').write_text('{}')
    knowledge = {'passed': True, 'phase': 'after', 'actual_sha256': 'fixture',
        'expected_sha256': 'fixture', 'endpoint': 'http://127.0.0.1:9200/mcp'}
    monkeypatch.setattr(knowledge_conditions, 'check_knowledge_conditions', lambda *args: knowledge)
    prior = source / 'prior-ledger.json'
    inherited = [{'number': i, 'reserved_cny': 0, 'pricing_verified': False, 'http_status': 200,
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1}} for i in range(1, 53)] if request_caps else []
    save(prior, {'limit_cny': 5, 'reserved_cny': 0, 'requests': inherited})
    prior_bytes = prior.read_bytes()
    launches, resets = [], []
    async def reset(case):
        resets.append(case)
    def launch(args, name):
        assert '--isolate-history' in args
        if request_caps:
            assert ('--allow-unpriced-model' in args) is unpriced
            assert '--run-budget-cny' not in args
            assert args[args.index('--max-model-requests') + 1] == '76'
            assert args[args.index('--run-max-model-requests') + 1] == '2'
        else:
            assert '--run-budget-cny' in args
        symptom = Path(args[args.index('--symptom-file') + 1]).read_text(encoding='utf-8')
        assert symptom == '请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。'
        group = args[args.index('--mechanism-group') + 1]
        output = Path(args[args.index('--output-dir') + 1])
        build(group, output)
        (source / ('model-attempt-' + output.name + '.json')).unlink()
        previous_path = Path(args[args.index('--previous-cost') + 1])
        old = json.loads(previous_path.read_text())
        budget = PaidRequestBudget(output, allow_unpriced_models=unpriced,
            max_requests=76 if request_caps else None, run_max_requests=2 if request_caps else None)
        row = json.loads((output / 'cost.json').read_text())['requests'][0]
        row['number'] = len(old['requests']) + 1
        if unpriced:
            row.update(reserved_cny=0, pricing_verified=False)
        budget.inherited_requests = len(old['requests'])
        budget.ledger = [*old['requests'], row]
        budget.reserved = old['reserved_cny'] + row['reserved_cny']
        budget.save()
        record_path = output / 'evaluation-record.json'
        record = json.loads(record_path.read_text())
        boundary = args[args.index('--observation-not-before') + 1]
        record['config'].update(previous_cost=str(previous_path), run_budget_cny=None if request_caps else 0.25, shared_history_enabled=False,
            target_id='windows-local-01', observation_not_before=boundary)
        if request_caps:
            record['config'].update(allow_unpriced_model=unpriced, max_model_requests=76,
                run_max_model_requests=2, max_output_tokens=4096)
        record['config_sha256'] = hashlib.sha256(json.dumps(record['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        save(record_path, record)
        summary_path = output / 'summary.json'
        summary = json.loads(summary_path.read_text())
        summary.update(previous_cost=str(previous_path), model_requests=len(budget.ledger), reserved_cny=budget.reserved,
            actual_estimated_cny_peak=budget.actual_cost_cny(), knowledge_mode='local_bm25_mcp', knowledge_conditions=knowledge,
            diagnosis={'version': 1, 'kind': 'unlocated', 'target_id': 'windows-local-01'},
            cost_scope={'cumulative': budget.cost_summary(), 'this_run': budget.cost_summary(len(old['requests']))})
        if request_caps:
            summary['request_limits'] = budget.request_limits()
        save(summary_path, summary)
        for phase in ('before', 'after'):
            save(output / ('knowledge-conditions-' + phase + '.json'), {**knowledge, 'phase': phase})
        trace_path = output / 'tool_trace.json'
        trace = json.loads(trace_path.read_text())
        trace[0]['validated_live_evidence'] = True
        from src.probe.protocol import evidence
        trace[0]['result'] = evidence(target_id='windows-local-01', operation='dependency_probe',
            payload={'dependency': 'localapp'}, collected_at=trace[0]['ended_at'])
        save(trace_path, trace)
        for filename in ('runs.sqlite', 'checkpoints.sqlite'):
            with sqlite3.connect(output / filename) as db:
                db.execute('create table isolated_marker (value text)')
        mechanism = output / 'mechanism_trace.json'
        data = json.loads(mechanism.read_text())
        data['thread_id'] = output.name
        save(mechanism, data)
        launches.append(output)
        return SimpleNamespace(wait=lambda: 0)
    options = dict(allow_unpriced_model=unpriced, max_model_requests=76, run_max_model_requests=2) if request_caps else {}
    results = await controller.evaluate_four_groups(source, launch, reset, knowledge['endpoint'], prior, 5,
        None if request_caps else 0.25, suite=suite, **options)
    assert len(results) == len(set(launches)) == 12
    assert resets[-1] == 'normal'
    report = summarize(source, source.parent / 'joined-summary')
    assert report['passed'], report['issues']
    assert len(report['runs']) == 12 and all(r['vs_G00'] is not None for r in report['runs'])
    assert all(r['audit']['this_run_cost']['requests'] == 1 for r in report['runs'])
    assert report['human_reviewed'] == 0 and report['diagnostic_accuracy'] is None
    assert prior.read_bytes() == prior_bytes
    if unpriced:
        assert all(r['audit']['this_run_cost']['estimated_cny_peak'] is None for r in report['runs'])
    assert all(r['mechanism_behavior']['status'] == 'passed' for r in report['runs'])
    assert all(r['mechanism_behavior']['opportunities'] is None for r in report['runs'])
    suite_path = source / 'four-group-controller.json'
    original_suite = json.loads(suite_path.read_text())
    if unpriced:
        for key, changed in [('max_model_requests', 75), ('run_max_model_requests', 1), ('inherited_requests', 51)]:
            save(suite_path, {**original_suite, key: changed})
            rejected = summarize(source, source.parent / ('wrong-budget-' + key))
            assert not rejected['passed'] and all(r['vs_G00'] is None for r in rejected['runs'])
        save(suite_path, original_suite)
    changed_suite = {**original_suite, 'suite': 'baseline-v1' if suite == 'mechanism-v1' else 'mechanism-v1'}
    save(suite_path, changed_suite)
    rejected_suite = summarize(source, source.parent / 'wrong-scenario-suite')
    assert rejected_suite['passed'] is False
    assert all(row['vs_G00'] is None for row in rejected_suite['runs'])
    save(suite_path, original_suite)
    first = launches[0]
    trace_path = first / 'tool_trace.json'
    original_trace = json.loads(trace_path.read_text())
    stale_trace = json.loads(trace_path.read_text())
    stale_trace[0]['result']['collected_at'] = '2000-01-01T00:00:00+00:00'
    save(trace_path, stale_trace)
    assert audit_evaluation(first)['passed'] is False
    save(trace_path, original_trace)
    suite_path = source / 'four-group-controller.json'
    suite = json.loads(suite_path.read_text())
    suite['resets'][0].pop('observation_not_before')
    save(suite_path, suite)
    rejected = summarize(source, source.parent / 'joined-summary-without-boundary')
    assert rejected['passed'] is False
    assert all(row['vs_G00'] is None for row in rejected['runs'])
