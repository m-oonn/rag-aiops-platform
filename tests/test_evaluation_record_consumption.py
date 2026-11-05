import hashlib
import json
from copy import deepcopy
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
        from scripts.verify_windows_local_faults import symptom_text
        directory = directory or source / group
        directory.mkdir()
        switches = MECHANISM_GROUPS.get(group, (False, False))
        config = {'mechanism_group': group, 'mechanisms': {'hypothesis_protection': switches[0],
            'contradiction_trigger': switches[1], 'protection_steps': 2},
            'budget_limit_cny': 5, 'tool_names': ['probe_dependency_probe'],
            'symptom_sha256': hashlib.sha256(symptom_text('neutral').encode('utf-8')).hexdigest()}
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


@pytest.mark.parametrize('mutation', ['none', 'baseline', 'missing', 'sources', 'mode', 'implementation'])
def test_local_runbook_baseline_is_consumed_and_audited(artifacts, tmp_path, mutation):
    from scripts.knowledge_conditions import ROOT, knowledge_conditions, check_knowledge_conditions
    root, _, build = artifacts
    for name in ('scripts/evaluate_windows_probe.py', 'scripts/knowledge_conditions.py',
                 'src/agent/aiops/local_retrieval.py'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    directory = build()
    corpus = tmp_path / 'runbooks'
    corpus.mkdir()
    (corpus / 'topology.md').write_text('localapp connects to downstream', encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    baseline = knowledge_conditions(corpus, mode='local_runbooks')
    save(manifest, baseline)
    check_knowledge_conditions(manifest, corpus, directory, None, 'before')
    after = check_knowledge_conditions(manifest, corpus, directory, None, 'after')
    summary = json.loads((directory / 'summary.json').read_text())
    summary.update(knowledge_mode='local_runbooks', knowledge_conditions=after)
    save(directory / 'summary.json', summary)
    save(directory / 'knowledge_trace.json', {'mode': 'local_runbooks', 'sources': baseline['sources'], 'queries': []})
    if mutation == 'missing': (directory / 'knowledge-baseline.json').unlink()
    if mutation == 'baseline':
        baseline['sources'][0]['sha256'] = 'changed'
        save(directory / 'knowledge-baseline.json', baseline)
    if mutation == 'sources': save(directory / 'knowledge_trace.json', {'sources': []})
    if mutation == 'mode':
        after['mode'] = 'mcp_fixture'
        save(directory / 'knowledge-conditions-after.json', after)
    if mutation == 'implementation':
        baseline['implementations']['src/agent/aiops/local_retrieval.py'] = 'changed'
        value = {k: v for k, v in baseline.items() if k != 'sha256'}
        baseline['sha256'] = hashlib.sha256(json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        save(directory / 'knowledge-baseline.json', baseline)
        for phase in ('before', 'after'):
            audit = json.loads((directory / ('knowledge-conditions-' + phase + '.json')).read_text())
            audit.update(expected_sha256=baseline['sha256'], actual_sha256=baseline['sha256'])
            save(directory / ('knowledge-conditions-' + phase + '.json'), audit)
            if phase == 'after': summary['knowledge_conditions'] = audit
        save(directory / 'summary.json', summary)
    result = audit_evaluation(directory, expected_root=root)
    assert result['passed'] is (mutation == 'none'), result


@pytest.mark.parametrize('mutation', ['none', 'authorization_hash', 'binding', 'new_unknown', 'missing'])
def test_authorized_timeout_record_keeps_unknown_cost_without_waiving_new_failures(artifacts, mutation):
    root, source, build = artifacts
    directory = build()
    old = {'number': 1, 'reserved_cny': .092916, 'reservation_upper_cny': .092916,
        'status': 'ReadTimeout', 'error_type': 'ReadTimeout', 'pricing_verified': True}
    prior = {'limit_cny': 5, 'reserved_cny': old['reserved_cny'], 'requests': [old]}
    previous = source / 'previous.json'
    save(previous, prior)
    authorization = source / 'authorization.json'
    value = {'version': 1, 'kind': 'single_historical_read_timeout', 'user_authorization': '一次续测',
        'request_number': 1, 'reserved_cny': old['reserved_cny'], 'limit_cny': 5, 'run_limit_cny': 5,
        'output_dir': str(directory), 'previous_sha256': hashlib.sha256(previous.read_bytes()).hexdigest(),
        'request_sha256': hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    save(authorization, value)
    binding = {'path': str(authorization), 'sha256': hashlib.sha256(authorization.read_bytes()).hexdigest()}
    save(directory / 'timeout-authorization-use.json', binding)
    record = json.loads((directory / 'evaluation-record.json').read_text())
    record['config'].update(previous_cost=str(previous), run_budget_cny=5, timeout_resume_authorization=binding)
    cost = json.loads((directory / 'cost.json').read_text())
    cost['requests'][0]['number'] = 2
    cost['requests'].insert(0, old)
    cost['reserved_cny'] += old['reserved_cny']
    cost['request_limits']['inherited_requests'] = 1
    if mutation == 'new_unknown':
        cost['requests'][1].pop('usage')
    save(directory / 'cost.json', cost)
    budget = PaidRequestBudget(directory)
    budget.ledger = cost['requests']
    summary = json.loads((directory / 'summary.json').read_text())
    summary.update(previous_cost=str(previous), model_requests=2, reserved_cny=cost['reserved_cny'],
        actual_estimated_cny_peak=None, cost_scope={'cumulative': budget.cost_summary(), 'this_run': budget.cost_summary(1)})
    save(directory / 'summary.json', summary)
    if mutation == 'authorization_hash':
        value['request_number'] = 2
        save(authorization, value)
    if mutation == 'binding': save(directory / 'timeout-authorization-use.json', {})
    if mutation == 'missing': record['config'].pop('timeout_resume_authorization')
    record['config_sha256'] = hashlib.sha256(json.dumps(record['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(directory / 'evaluation-record.json', record)
    result = audit_evaluation(directory, expected_root=root)
    assert result['passed'] is (mutation == 'none'), result


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
    'missing_controller', 'malformed_controller', 'missing_controller_time', 'failed_suite', 'unrecovered_suite', 'different_channel'])
def test_summary_only_compares_complete_matching_four_groups(artifacts, mutation):
    root, source, build = artifacts
    for group in ['G00', 'G10', 'G01', 'G11']:
        if mutation == 'missing_group' and group == 'G11':
            continue
        build(group)
    directory = source / 'G11'
    if mutation == 'different_channel':
        for child in source.iterdir():
            if child.is_dir():
                cost = json.loads((child / 'cost.json').read_text())
                cost['requests'][0]['api_base'] = ('https://fallback.invalid/v1'
                    if child == directory else 'https://primary.invalid/v1')
                save(child / 'cost.json', cost)
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
    if mutation == 'none':
        assert {(r['group'], r['baseline_group']) for r in result['comparisons']} == {
            ('G10', 'G00'), ('G01', 'G00'), ('G11', 'G10'), ('G11', 'G01')}


def test_summary_keeps_unexecuted_slots_and_unknown_review_fields(artifacts):
    _, source, build = artifacts
    build('G00')
    save(source / 'four-group-controller.json', {
        'suite': 'e2-fault-pair-v1', 'status': 'failed', 'recovery': 'normal_restored',
        'order': [{'case': case, 'group': group}
            for case in ('downstream_unreachable', 'application_config_error')
            for group in ('G00', 'G10', 'G01', 'G11')], 'results': [], 'resets': []})
    report = summarize(source, source.parent / 'incomplete-summary')
    assert len(report['scheduled_slots']) == 8
    assert all(row['status'] == 'not_run' for row in report['scheduled_slots'])
    assert report['comparisons'] == []
    row = report['runs'][0]
    assert row['semantic_status'] == 'pending_manual_review'
    assert row['mechanical_status'] is None
    assert row['repeated_queries'] is None and row['irrelevant_checks'] is None


@pytest.mark.parametrize('exit_code', [0, 1])
def test_summary_keeps_controller_failure_even_when_child_record_passes(artifacts, exit_code):
    _, source, build = artifacts
    directory = build('G00')
    save(source / 'four-group-controller.json', {
        'suite': 'e2-fault-pair-v1', 'status': 'failed', 'recovery': 'pending',
        'order': [{'case': 'case', 'group': 'G00'},
                  {'case': 'downstream_unreachable', 'group': 'G10'}],
        'results': [{'case': 'real_model_workflow_case', 'mechanism_group': 'G00', 'status': 'failed',
                     'result_dir': str(directory)}], 'resets': []})
    attempt_path = source / 'model-attempt-G00.json'
    attempt = json.loads(attempt_path.read_text())
    save(attempt_path, {**attempt, 'exit_code': exit_code})
    report = summarize(source, source.parent / 'controller-failed-summary')
    assert [row['status'] for row in report['scheduled_slots']] == ['failed', 'not_run']
    assert report['runs'][0]['workflow_status'] == ('completed' if exit_code == 0 else 'not_verified')
    assert report['passed'] is False


def test_summary_keeps_failed_slot_without_child_artifacts(artifacts):
    _, source, _ = artifacts
    save(source / 'four-group-controller.json', {
        'suite': 'e2-fault-pair-v1', 'status': 'failed', 'recovery': 'pending',
        'order': [{'case': 'downstream_unreachable', 'group': 'G00'}],
        'results': [{'case': 'real_model_workflow_downstream_unreachable',
            'mechanism_group': 'G00', 'status': 'failed', 'result_dir': str(source / 'missing')}],
        'resets': []})
    report = summarize(source, source.parent / 'missing-child-summary')
    assert report['scheduled_slots'][0]['status'] == 'failed'
    assert report['passed'] is False


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
@pytest.mark.parametrize('suite', ['baseline-v1', 'mechanism-v1', 'e2-fault-pair-v1'])
@pytest.mark.parametrize('unpriced', [False, True, 'priced_requests'])
async def test_four_group_orchestration_consumes_real_child_gate_and_summary(artifacts, monkeypatch, suite, unpriced):
    request_caps = bool(unpriced)
    unpriced = unpriced is True
    import sqlite3
    from scripts import verify_windows_local_faults as controller, knowledge_conditions
    root, source, build = artifacts
    monkeypatch.setattr(controller, 'ROOT', root)
    expected_runs = len(controller.four_group_cases(suite)) * 4
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
    assert len(results) == len(set(launches)) == expected_runs
    assert resets[-1] == 'normal'
    report = summarize(source, source.parent / 'joined-summary')
    assert report['passed'], report['issues']
    assert len(report['runs']) == expected_runs and all(r['vs_G00'] is not None for r in report['runs'])
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
    changed_symptom = {**original_suite, 'symptom_sha256': 'wrong-symptom-hash'}
    save(suite_path, changed_symptom)
    rejected_symptom = summarize(source, source.parent / 'wrong-symptom-suite')
    assert rejected_symptom['passed'] is False
    assert all(row['vs_G00'] is None for row in rejected_symptom['runs'])
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



@pytest.mark.parametrize('mutation', ['none', 'degraded', 'missing', 'hash', 'request', 'summary', 'view', 'bundle_missing', 'bundle_hash'])
def test_report_generation_record_is_consumed_without_rewriting_legacy(artifacts, mutation):
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout
    _, _, build = artifacts
    directory = build()
    config_record = json.loads((directory / 'evaluation-record.json').read_text())
    config_record['config']['report_model_enabled'] = True
    config_record['config_sha256'] = hashlib.sha256(json.dumps(config_record['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(directory / 'evaluation-record.json', config_record)
    # An empty statement pool isolates record/view binding; diagnosis gates are separate.
    diagnosis = {'kind': 'localized_fault', 'recommendations': []}
    bundle = build_bundle(diagnosis)
    layout = rule_layout(bundle)
    rendered = render_report(bundle, layout)
    (directory / 'report.txt').write_text(rendered, encoding='utf-8')
    save(directory / 'events.json', [{'type': 'complete', 'response': rendered, 'diagnosis': diagnosis}])
    report = {'version': 1, 'mode': 'model', 'status': 'ready', 'model_requested': True,
              'request_numbers': [1], 'report_sha256': hashlib.sha256(rendered.encode()).hexdigest(),
              'bundle': bundle, 'layout': layout.model_dump(),
              'input_sha256': hashlib.sha256(json.dumps(bundle, ensure_ascii=False, sort_keys=True,
                  separators=(',', ':')).encode()).hexdigest()}
    if mutation == 'degraded': report['status'] = 'degraded'
    if mutation == 'hash': report['report_sha256'] = 'changed'
    if mutation == 'request': report['request_numbers'] = [2]
    if mutation == 'bundle_missing': report.pop('bundle')
    if mutation == 'bundle_hash': report['bundle']['stop_reason'] = 'tampered after composition'
    if mutation == 'view':
        report['bundle'] = {'version': 1}
        report['layout'] = {}
    summary = json.loads((directory / 'summary.json').read_text())
    summary.update(report_model_enabled=True, diagnosis=diagnosis,
        report_generation={k: v for k, v in report.items() if k not in {'bundle', 'layout'}},
        report_generation_passed=True)
    if mutation == 'summary': summary['report_generation']['mode'] = 'rules'
    save(directory / 'summary.json', summary)
    if mutation != 'missing': save(directory / 'report-generation.json', report)
    result = audit_evaluation(directory)
    assert result['passed'] is (mutation == 'none'), result['issues']


@pytest.mark.parametrize('mutation', ['none', 'trivial', 'projection_hash', 'posted_projection',
    'output_order', 'missing_output', 'missing_contract', 'stripped_metadata', 'unknown_contract',
    'fixed_order', 'trivial_missing_bundle'])
def test_core_report_record_binds_projection_output_and_final_layout(artifacts, mutation):
    from src.agent.aiops import reporting as module
    _, _, build = artifacts
    directory = build()
    config = json.loads((directory / 'evaluation-record.json').read_text())
    config['config']['report_model_enabled'] = True
    config['config_sha256'] = hashlib.sha256(json.dumps(config['config'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(directory / 'evaluation-record.json', config)
    diagnosis = {'kind': 'localized_fault', 'recommendations': []}
    bundle = module.build_bundle(diagnosis)
    ids = ['arbitrary-a'] if mutation.startswith('trivial') else ['arbitrary-a', 'arbitrary-b']
    bundle['objects'] = {'obj': {'label': 'downstream', 'scope': {'service': 'downstream'},
                                'codes': [], 'facts': ids}}
    bundle['facts'] = {key: {'object_id': 'obj', 'text': key} for key in ids}
    bundle['facts']['fixed-a'] = {'text': '日志来源说明'}
    bundle['facts']['fixed-b'] = {'text': '采样范围说明'}
    projection = module.core_fact_projection(bundle)
    order = module.CoreFactOrder(core_fact_order=ids[::-1])
    layout = module.layout_from_core_order(bundle, order)
    output = {'schema': 'CoreFactOrder', 'status': 'parsed', 'decoded_arguments': order.model_dump(),
              'parsed_proposal': order.model_dump()}
    report = {'version': 1, 'mode': 'model', 'status': 'ready', 'model_requested': True,
        'request_numbers': [1], 'bundle': bundle, 'layout': layout.model_dump(),
        'input_sha256': module._hash(bundle), 'model_contract': module.MODEL_CONTRACT,
        'model_input_sha256': module._hash(projection), 'model_outputs': [output]}
    body = {'model': 'deepseek-flash', 'max_tokens': 10,
        'messages': [{'role': 'user', 'content': json.dumps(projection)}],
        'tools': [{'type': 'function', 'function': {'name': 'CoreFactOrder',
                   'parameters': module.CoreFactOrder.model_json_schema()}}]}
    if mutation.startswith('trivial'):
        report.update(mode='rules', request_numbers=[], model_outputs=[], fallback_reason='no_sortable_core_facts')
        report['layout'] = module.rule_layout(bundle).model_dump()
    if mutation == 'projection_hash': report['model_input_sha256'] = 'tampered'
    if mutation == 'posted_projection':
        posted = deepcopy(projection)
        posted['core_facts'][0]['text'] = 'different model input'
        body['messages'][0]['content'] = json.dumps(posted)
    if mutation == 'output_order':
        output['parsed_proposal'] = {'core_fact_order': ids}
        output['decoded_arguments'] = output['parsed_proposal']
    if mutation == 'missing_output': report['model_outputs'] = []
    if mutation == 'missing_contract': report.pop('model_contract')
    if mutation == 'stripped_metadata':
        for key in ('model_contract', 'model_input_sha256', 'model_outputs'):
            report.pop(key)
    if mutation == 'unknown_contract': report['model_contract'] = 'future-unknown'
    if mutation == 'fixed_order': report['layout']['fact_order'][-2:] = ['fixed-b', 'fixed-a']
    rendered = module.render_report(bundle, module.ReportLayout(**report['layout']))
    report['report_sha256'] = hashlib.sha256(rendered.encode()).hexdigest()
    if mutation == 'trivial_missing_bundle': report.pop('bundle')
    save(directory / 'model-inputs/1.json', body)
    cost = json.loads((directory / 'cost.json').read_text())
    cost['requests'][0]['input_sha256'] = hashlib.sha256((directory / 'model-inputs/1.json').read_bytes()).hexdigest()
    save(directory / 'cost.json', cost)
    (directory / 'report.txt').write_text(rendered, encoding='utf-8')
    save(directory / 'events.json', [{'type': 'complete', 'response': rendered, 'diagnosis': diagnosis}])
    summary = json.loads((directory / 'summary.json').read_text())
    summary.update(report_model_enabled=True, diagnosis=diagnosis, report_generation_passed=True,
        report_generation={key: report[key] for key in ('version', 'mode', 'status', 'model_requested',
            'request_numbers', 'input_sha256', 'report_sha256')})
    save(directory / 'summary.json', summary)
    save(directory / 'report-generation.json', report)
    result = audit_evaluation(directory)
    assert result['passed'] is (mutation in {'none', 'trivial'}), result['issues']
