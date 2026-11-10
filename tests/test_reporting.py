"""Evidence-bound report composition, without model or host requests."""
from copy import deepcopy
import json

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def report_input(*, two_faults=False, mapped=True, stopped=False):
    rows = [
        ('inventory', {'configured_services': {name: {'process_names': [name + '.exe']}
                        for name in ('downstream', 'localapp', 'edge')}}),
        ('processes', {'service': 'downstream', 'processes': [], 'matched_count': 0,
                       'inspected_count': 3, 'skipped_count': 0}),
        ('dependency_probe', {'dependency': 'downstream', 'host': '127.0.0.1', 'port': 13980,
                              'tcp': 'failed', 'http': {'error': 'URLError'}}),
        ('ports', {'local_port': 13980, 'ports': [], 'listening_only': True}),
        ('dependency_probe', {'dependency': 'localapp', 'host': '127.0.0.1', 'port': 13979,
                              'tcp': 'ok', 'http': {'status': 503}}),
        ('dependency_probe', {'dependency': 'edge', 'host': '127.0.0.1', 'port': 13978,
                              'tcp': 'ok', 'http': {'status': 503}}),
        ('text_logs', {'service': 'localapp', 'path': 'D:/localapp.log',
                       'lines': ['upstream connection failed'], 'line_limit': 20}),
    ]
    if stopped:
        # One instance start, stop request and exit, as the stopped dependency writes them.
        lifecycle = [
            {'at': '2026-11-10T11:58:01.201909+00:00', 'event': 'service_started', 'pid': 19352,
             'instance_id': 'bb51f348aa094dcc9a732d18e3ded5bb', 'listen_port': 13980},
            {'at': '2026-11-10T11:58:01.404816+00:00', 'event': 'shutdown_requested', 'pid': 19352,
             'reason': 'controlled_stop', 'stop_request': {'channel': 'file_presence', 'initiator': 'unknown'}},
            {'at': '2026-11-10T11:58:01.499254+00:00', 'event': 'service_exited', 'pid': 19352,
             'instance_id': 'bb51f348aa094dcc9a732d18e3ded5bb', 'reason': 'shutdown_completed'},
        ]
        rows.append(('text_logs', {'service': 'downstream', 'path': 'D:/downstream.log',
                                   'lines': [json.dumps(event) for event in lifecycle], 'line_limit': 20}))
    if two_faults:
        rows.append(('services', {'service': 'edge', 'state': 'stopped'}))
    current = {'input': 'entry unavailable', 'plan': [], 'past_steps': [], 'raw_evidence': [],
        'autonomous_investigation': True, 'thread_id': 'report-test',
        'target_resolution': {'status': 'resolved', 'service': 'localapp',
            'target_id': settings.PROBE_TARGET_ID, 'services': {},
            'allowed_services': ['downstream', 'localapp', 'edge'],
            'allowed_dependencies': ['downstream', 'localapp', 'edge'],
            'dependency_services': {name: name for name in ('downstream', 'localapp', 'edge')} if mapped else {}}}
    for index, (operation, payload) in enumerate(rows):
        current['raw_evidence'].append((str(index), json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload))))
    records = inv.evidence_index(current)
    diagnosis = inv.diagnosis_result(current, inv.InvestigationDecision(hypothesis='原因尚未知'),
        'localized_fault', records, reason='现有检查已完成；缺少退出历史。')
    return current, diagnosis, records


def test_report_separates_priority_and_preserves_upstream_anomalies():
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout
    current, diagnosis, records = report_input()
    original = deepcopy(diagnosis)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    layout = rule_layout(bundle)
    report = render_report(bundle, layout)
    assert [bundle['objects'][key]['label'] for key in layout.focus_object_ids] == ['downstream']
    assert '其他异常对象：localapp、edge' in report
    assert '退出原因' in report and '尚未确认' in report
    assert '本次可枚举范围内未发现配置进程' in report
    assert '完整查询未发现配置进程' not in report
    assert '若仍失败' in report and '分别复测' in report
    assert '核查该接口对应应用的错误日志及近期变更' not in report
    assert diagnosis == original
    assert all(f"[{f['evidence_id']}]" in report for f in diagnosis['observed_findings'])


def test_explanations_render_only_the_evidence_ids_linked_through_their_facts():
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout
    current, diagnosis, records = report_input(two_faults=True)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    report = render_report(bundle, rule_layout(bundle))
    explanation_section = report.split('证据支持的解释：', 1)[1].split('人工处理建议', 1)[0]

    for explanation in bundle['explanations'].values():
        linked_ids = list(dict.fromkeys(
            evidence_id
            for fact_id in explanation['fact_ids']
            for evidence_id in bundle['facts'][fact_id].get('evidence_ids', [])
        ))
        assert linked_ids
        line = next(line for line in explanation_section.splitlines()
                    if explanation['text'] in line)
        assert '依据：' + '、'.join(f'[{evidence_id}]' for evidence_id in linked_ids) in line


def test_legacy_explanation_without_fact_links_still_renders():
    from src.agent.aiops.reporting import render_report, rule_layout
    current, diagnosis, records = report_input()
    bundle = __import__('src.agent.aiops.reporting', fromlist=['build_bundle']).build_bundle(
        diagnosis, records=records, resolution=current['target_resolution'])
    explanation = next(iter(bundle['explanations'].values()))
    explanation.pop('fact_ids')

    report = render_report(bundle, rule_layout(bundle))

    assert explanation['text'] in report
    assert '证据支持的解释：' in report


def test_stopped_dependency_explains_its_logged_stop_instead_of_the_generic_sentence():
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout
    current, diagnosis, records = report_input(stopped=True)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    report = render_report(bundle, rule_layout(bundle))
    section = report.split('证据支持的解释：', 1)[1].split('人工处理建议', 1)[0]

    assert 'PID 19352' in section
    assert '监听端口 13980' in section
    assert 'controlled_stop' in section and 'file_presence' in section
    assert 'shutdown_completed' in section
    assert '上述有限观测支持该对象当前异常' not in section
    assert '。；依据：' not in report
    # What the log cannot say stays unconfirmed in the same sentence.
    assert '没有记录这次停止由谁请求、因何触发' in section


def test_independent_fault_cannot_be_hidden_by_model_layout():
    from src.agent.aiops.reporting import build_bundle, rule_layout, validate_layout
    current, diagnosis, records = report_input(two_faults=True)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    layout = rule_layout(bundle)
    assert {bundle['objects'][key]['label'] for key in layout.focus_object_ids} == {'downstream', 'edge'}
    layout.focus_object_ids = layout.focus_object_ids[:1]
    with pytest.raises(ValueError):
        validate_layout(layout, bundle)


def test_missing_mapping_does_not_merge_port_or_dependency_by_name():
    from src.agent.aiops.reporting import build_bundle, rule_layout
    current, diagnosis, records = report_input(mapped=False)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    objects = [bundle['objects'][key] for key in rule_layout(bundle).focus_object_ids]
    assert len(objects) == 3  # configured process, dependency and port have no verified mapping


@pytest.mark.asyncio
async def test_finalizer_keeps_status_history_and_one_source_for_advice():
    from src.agent.aiops.reporting import finalize_report
    current, diagnosis, _ = report_input()
    update = {'response': inv.localized_report(diagnosis), 'diagnosis': diagnosis, 'plan': [],
              'investigation_memory': {'candidates': ['preserve'], 'decision_trace': {'attempts': []}}}
    before = deepcopy(update)
    result = await finalize_report(current, update)
    assert update == before
    assert result['diagnosis']['kind'] == diagnosis['kind']
    assert result['diagnosis']['observed_findings'] == diagnosis['observed_findings']
    assert result['investigation_memory']['candidates'] == ['preserve']
    assert result['investigation_memory']['report']['mode'] == 'rules'
    for advice in result['diagnosis']['recommendations']:
        assert advice['action'] in result['response']
    assert result['investigation_memory']['report']['source_recommendations'] == diagnosis['recommendations']


@pytest.mark.asyncio
async def test_finalizer_preserves_knowledge_appendix_in_saved_render_and_input_hash():
    from src.agent.aiops import reporting
    current, diagnosis, _ = report_input()
    before = await reporting.finalize_report(current, update_for(diagnosis))
    current['raw_evidence'].append(('检索经验', json.dumps({'results': [{
        'source': 'downstream-runbook.md', 'page': 2, 'chunk_id': 'chunk-7',
        'content': 'knowledge only, not an observation'}]})))
    result = await reporting.finalize_report(current, update_for(diagnosis))
    record = result['investigation_memory']['report']
    assert result['response'].count('## 参考知识库') == 1
    assert 'downstream-runbook.md，第 2 页，chunk chunk-7' in result['response']
    assert '现场指标、日志和变更证据优先' in result['response']
    assert 'knowledge only, not an observation' not in result['response']
    assert record['input_sha256'] != before['investigation_memory']['report']['input_sha256']
    assert reporting.render_report(record['bundle'], reporting.ReportLayout(**record['layout'])) == result['response']


@pytest.mark.parametrize('change', ['foreign_fact', 'duplicate', 'missing_action', 'wrong_object', 'followup_first', 'free_cause'])
def test_layout_rejects_invented_omitted_or_misordered_content(change):
    from pydantic import ValidationError
    from src.agent.aiops.reporting import build_bundle, rule_layout, validate_layout, ReportLayout
    current, diagnosis, records = report_input(two_faults=True)
    bundle = build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    data = rule_layout(bundle).model_dump()
    if change == 'foreign_fact': data['fact_order'][0] = 'fact-foreign'
    if change == 'duplicate': data['fact_order'].append(data['fact_order'][0])
    if change == 'missing_action': data['action_order'].pop()
    if change == 'wrong_object': data['focus_object_ids'][0] = 'controller-answer'
    if change == 'followup_first': data['action_order'].reverse()
    if change == 'free_cause': data['root_cause'] = 'process crashed'
    with pytest.raises((ValueError, ValidationError)):
        validate_layout(ReportLayout.model_validate(data), bundle)


def update_for(diagnosis):
    return {'response': inv.localized_report(diagnosis), 'diagnosis': diagnosis, 'plan': [],
            'investigation_memory': {'candidates': ['preserve']}}


def test_core_projection_uses_object_membership_and_preserves_fixed_facts():
    from src.agent.aiops import reporting as module
    current, diagnosis, records = report_input()
    bundle = module.build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    # A core fact need not start with fact-, and fixed material may have that prefix.
    obj = next(iter(bundle['objects'].values()))
    ident = obj['facts'][0]
    bundle['facts']['arbitrary-core'] = bundle['facts'].pop(ident)
    obj['facts'][0] = 'arbitrary-core'
    bundle['facts']['fact-fixed'] = {'text': '必须保留的覆盖说明'}
    before = deepcopy(bundle)
    projection = module.core_fact_projection(bundle)
    assert 'arbitrary-core' in projection['allowed_core_fact_ids']
    assert 'fact-fixed' not in projection['allowed_core_fact_ids']
    assert set(projection) == {'allowed_core_fact_ids', 'core_facts'}
    assert all(set(item) == {'id', 'object', 'text'} for item in projection['core_facts'])
    order = module.CoreFactOrder(core_fact_order=projection['allowed_core_fact_ids'][::-1])
    layout = module.layout_from_core_order(bundle, order)
    fixed = [key for key in bundle['facts'] if key not in projection['allowed_core_fact_ids']]
    assert layout.fact_order == order.core_fact_order + fixed
    expected = module.rule_layout(bundle)
    for field in ('focus_object_ids', 'explanation_ids', 'action_order'):
        assert getattr(layout, field) == getattr(expected, field)
    rendered = module.render_report(bundle, layout)
    assert all(item['text'] in rendered for key, item in bundle['facts'].items() if key in fixed)
    assert bundle == before


def test_five_core_facts_keep_two_logs_and_three_sampling_notes():
    from src.agent.aiops import reporting as module
    current, _, _ = report_input()
    for service in ('downstream', 'localapp', 'edge'):
        processes = [] if service == 'downstream' else [{'pid': 12, 'name': service + '.exe'}]
        current['raw_evidence'].append((service, json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
                'service': service, 'processes': processes, 'selection': 'top_accessible_processes',
                'matched_count': len(processes), 'inspected_count': 3, 'skipped_count': 0}))))
    current['raw_evidence'].append(('edge-log', json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
            'service': 'edge', 'path': 'D:/edge.log', 'lines': ['upstream connection failed'],
            'line_limit': 20}))))
    records = inv.evidence_index(current)
    diagnosis = inv.diagnosis_result(current, inv.InvestigationDecision(hypothesis='原因尚未知'),
        'localized_fault', records, reason='检查完成；历史未知。')
    bundle = module.build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    core = module.core_fact_projection(bundle)['allowed_core_fact_ids']
    fixed = [key for key in bundle['facts'] if key not in core]
    assert len(core) == len(fixed) == 5
    assert sum(bundle['facts'][key]['text'].startswith('现场日志观察') for key in fixed) == 2
    assert sum(bundle['facts'][key]['text'].startswith('独立采集说明') for key in fixed) == 3
    old = module.rule_layout(bundle)
    old.fact_order = core[::-1]
    with pytest.raises(ValueError, match='report_layout_missing_duplicate_or_foreign_id'):
        module.validate_layout(old, bundle)
    new = module.layout_from_core_order(bundle, module.CoreFactOrder(core_fact_order=core[::-1]))
    rendered = module.render_report(bundle, new)
    assert new.fact_order == core[::-1] + fixed
    assert all(fact['text'] in rendered for fact in bundle['facts'].values())
    assert all('[' + ref['evidence_id'] + ']' in rendered
        for fact in bundle['facts'].values() for ref in fact.get('citations', []))
    assert all(bundle['facts'][key]['text'] not in json.dumps(module.core_fact_projection(bundle),
        ensure_ascii=False) for key in fixed)


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'foreign', 'extra'])
def test_core_order_rejects_invalid_output(case):
    from src.agent.aiops import reporting as module
    from pydantic import ValidationError
    current, diagnosis, records = report_input()
    bundle = module.build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    keys = module.core_fact_projection(bundle)['allowed_core_fact_ids']
    data = {'core_fact_order': list(keys)}
    if case == 'missing': data['core_fact_order'].pop()
    if case == 'duplicate': data['core_fact_order'].append(keys[0])
    if case == 'foreign': data['core_fact_order'][0] = 'fixed-or-foreign'
    if case == 'extra': data['root_cause'] = 'invented'
    with pytest.raises((ValueError, ValidationError)):
        module.layout_from_core_order(bundle, module.CoreFactOrder.model_validate(data))


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [0, 1])
async def test_zero_or_one_core_fact_does_not_call_model(tmp_path, monkeypatch, count):
    from unittest.mock import Mock
    from src.agent.aiops import reporting as module
    current, diagnosis, records = report_input()
    bundle = module.build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    for obj in bundle['objects'].values():
        obj['facts'] = []
    if count:
        key, fact = next((key, fact) for key, fact in bundle['facts'].items() if 'object_id' in fact)
        bundle['objects'][fact['object_id']]['facts'] = [key]
    factory = Mock(side_effect=AssertionError('no model for trivial ordering'))
    monkeypatch.setattr(module, 'create_agent_llm', factory)
    record = {'status': 'ready', 'mode': 'rules', 'input_sha256': module._hash(bundle), 'request_numbers': []}
    with module.report_model_session(tmp_path, lambda: []):
        layout = await module._model_layout(bundle, current['thread_id'], record, module.rule_layout(bundle))
    assert layout == module.rule_layout(bundle)
    assert record['status'] == 'ready' and record['mode'] == 'rules'
    assert record['fallback_reason'] == 'no_sortable_core_facts'
    assert not list(tmp_path.glob('report-attempt-*'))
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['valid', 'missing', 'duplicate', 'foreign', 'extra', 'timeout', 'budget', 'refusal'])
async def test_optional_model_is_single_attempt_and_falls_back_safely(tmp_path, monkeypatch, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from src.agent.aiops import reporting as module
    current, diagnosis, _ = report_input()
    calls = []
    llm = SimpleNamespace(max_tokens=2048)
    factory = Mock(return_value=llm)
    monkeypatch.setattr(module, 'create_agent_llm', factory)
    async def compose(model, schema, prompt, inputs, **kwargs):
        assert kwargs == {'format_fallback': False, 'max_attempts': 1}
        projection = json.loads(inputs['projection'])
        assert set(projection) == {'allowed_core_fact_ids', 'core_facts'}
        assert schema is module.CoreFactOrder
        assert json.loads(inputs['example']) == {'core_fact_order': projection['allowed_core_fact_ids']}
        calls.append({'number': 1})
        if outcome == 'timeout': raise TimeoutError('private-provider-body')
        if outcome == 'budget':
            error = RuntimeError('private-budget-details')
            error.status_code = 402
            raise error
        if outcome == 'refusal': raise ValueError('private refusal')
        order = module.CoreFactOrder(core_fact_order=projection['allowed_core_fact_ids'])
        if outcome == 'missing': order.core_fact_order.pop()
        if outcome == 'duplicate': order.core_fact_order.append(order.core_fact_order[0])
        if outcome == 'foreign': order.core_fact_order[0] = 'foreign'
        if outcome == 'extra': return schema.model_validate({**order.model_dump(), 'extra': []})
        return order
    invoke = AsyncMock(side_effect=compose)
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    with module.report_model_session(tmp_path, lambda: calls):
        result = await module.finalize_report(current, update_for(diagnosis))
        again = await module.finalize_report(current, update_for(diagnosis))
    record = result['investigation_memory']['report']
    assert record['status'] == ('ready' if outcome == 'valid' else 'degraded')
    assert record['mode'] == ('model' if outcome == 'valid' else 'rules')
    assert record['request_numbers'] == [1]
    assert record['model_contract'] == module.MODEL_CONTRACT
    assert record['model_input_sha256'] == module._hash(module.core_fact_projection(record['bundle']))
    if outcome in {'missing', 'duplicate', 'foreign'}:
        assert record['fallback_reason'] == 'report_core_order_missing_duplicate_or_foreign_id'
    if outcome == 'extra':
        assert record['fallback_reason'] == 'ValidationError'
    assert 'private' not in json.dumps(record)
    assert again['investigation_memory']['report']['fallback_reason'] == 'previous_report_attempt_not_replayed'
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert all(a['action'] in result['response'] for a in result['diagnosis']['recommendations'])
    assert '其他异常对象：localapp、edge' in result['response']
    assert llm.max_tokens == 2048  # do not raise an inherited smaller output cap
    invoke.assert_awaited_once()
    factory.assert_called_once_with(streaming=False, max_retries=0)


@pytest.mark.asyncio
async def test_report_timeout_deadline_is_bounded(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.agent.aiops import reporting as module
    current, diagnosis, _ = report_input()
    monkeypatch.setattr(module, 'create_agent_llm', lambda **kw: SimpleNamespace(max_tokens=None))
    invoke = AsyncMock()
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    async def timeout(coroutine, *, timeout):
        assert timeout == 60
        coroutine.close()
        raise TimeoutError
    monkeypatch.setattr(module.asyncio, 'wait_for', timeout)
    with module.report_model_session(tmp_path, lambda: []):
        result = await module.finalize_report(current, update_for(diagnosis))
    assert result['investigation_memory']['report']['fallback_reason'] == 'TimeoutError'


@pytest.mark.asyncio
async def test_unwritable_marker_stops_before_request(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from src.agent.aiops import reporting as module
    current, diagnosis, _ = report_input()
    output = tmp_path / 'file'
    output.write_text('not a directory')
    factory = Mock(side_effect=AssertionError('no request'))
    monkeypatch.setattr(module, 'create_agent_llm', factory)
    with module.report_model_session(output, lambda: []):
        result = await module.finalize_report(current, update_for(diagnosis))
    assert result['investigation_memory']['report']['fallback_reason'] == 'report_attempt_record_unwritable'
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_leaves_marker_and_never_replays(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.agent.aiops import reporting as module
    current, diagnosis, _ = report_input()
    monkeypatch.setattr(module, 'create_agent_llm', lambda **kw: SimpleNamespace(max_tokens=9000))
    invoke = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    with module.report_model_session(tmp_path, lambda: []):
        with pytest.raises(asyncio.CancelledError):
            await module.finalize_report(current, update_for(diagnosis))
        assert json.loads(next(tmp_path.glob('report-attempt-*')).read_text())['status'] == 'interrupted'
        result = await module.finalize_report(current, update_for(diagnosis))
    assert result['investigation_memory']['report']['fallback_reason'] == 'previous_report_attempt_not_replayed'
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['unlocated', 'healthy_within_scope', 'investigation_failure', 'bad_reference'])
async def test_failed_or_unvalidated_result_never_pays_or_upgrades(tmp_path, monkeypatch, case):
    from unittest.mock import Mock
    from src.agent.aiops import reporting as module
    current, diagnosis, _ = report_input()
    update = update_for(diagnosis)
    if case == 'bad_reference': diagnosis['observed_findings'][0]['quote'] = 'invented quote'
    elif case == 'investigation_failure': update['investigation_failure'] = {'code': 'failed'}
    else: diagnosis['kind'] = case
    factory = Mock(side_effect=AssertionError('must not call'))
    monkeypatch.setattr(module, 'create_agent_llm', factory)
    with module.report_model_session(tmp_path, lambda: []):
        result = await module.finalize_report(current, update)
    assert result['diagnosis']['kind'] == diagnosis['kind']
    if case == 'bad_reference':
        assert result['investigation_memory']['report']['status'] == 'failed'
        assert '核验未通过' in result['response']
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_old_terminal_checkpoint_is_read_without_regeneration(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from src.agent.aiops import reporting
    from src.agent.aiops.replanner import create_replanner
    compose = AsyncMock(side_effect=AssertionError('do not backfill'))
    monkeypatch.setattr(reporting, 'finalize_report', compose)
    current = {'response': 'original report', 'diagnosis': {'version': 1, 'kind': 'localized_fault'},
               'autonomous_investigation': True}
    strategy = type('Strategy', (), {'decide': AsyncMock(side_effect=AssertionError('already terminal'))})()
    with reporting.report_model_session(tmp_path, lambda: []):
        result = await create_replanner(strategy)(current)
    assert result['response'] == 'original report' and result['diagnosis'] == current['diagnosis']
    compose.assert_not_awaited()



def test_factory_disables_sdk_retries_on_both_channels(monkeypatch):
    from src.agent.aiops_llm import create_agent_llm
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    monkeypatch.setattr(settings, 'LLM_API_KEY', 'offline-test-key')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_API_KEY', 'offline-test-key')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_API_BASE', 'https://api.deepseek.com')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_ENABLED', True)
    model = create_agent_llm(model='deepseek-v4.1-flash-1017', max_retries=0)
    for leaf in [model.runnable, *model.fallbacks]:
        assert leaf.max_retries == leaf.root_async_client.max_retries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['valid', 'invalid_layout', 'budget', 'primary_transient'])
async def test_report_http_is_in_evaluation_budget_and_degradation_is_preserved(tmp_path, monkeypatch, mode):
    import httpx
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from scripts import evaluate_windows_probe as evaluation
    from src.agent.aiops import graph, reporting, planner, executor
    from src.probe.windows.config import ProbeConfig
    # The evaluation function temporarily configures these process-local settings.
    for name in ['PROBE_ENABLED', 'PROBE_TARGET_ID', 'DIAGNOSTIC_TARGET_CATALOG',
            'PROBE_EVIDENCE_DIR', 'TERMCP_ENABLED', 'ENABLE_HITL', 'ENABLE_LLM_RETRY',
            'INVESTIGATION_HYPOTHESIS_PROTECTION', 'INVESTIGATION_CONTRADICTION_TRIGGER']:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    monkeypatch.setattr(settings, 'LLM_API_KEY', 'offline-test-key')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_API_KEY', 'offline-test-key')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_API_BASE', 'https://api.deepseek.com')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_ENABLED', True)
    monkeypatch.setenv('AGENT_MODEL', 'deepseek-v4.1-flash-1017')
    for module in [planner, executor]:
        monkeypatch.setattr(module, 'load_agent_tools', module.load_agent_tools)
    monkeypatch.setattr(executor, '_tools_cache', {})
    monkeypatch.setattr(executor, '_tools_cache_at', {})
    original_factory = reporting.create_agent_llm
    network = []
    async def respond(request):
        body = json.loads(request.content)
        network.append(body)
        assert body['max_tokens'] == 1024 and body['stream'] is False
        assert body['model'] == 'deepseek-v4.1-flash-1017'
        if mode == 'primary_transient':
            return httpx.Response(503, json={'error': {'message': 'offline unavailable'}})
        projection = json.loads(body['messages'][-1]['content'])
        assert set(projection) == {'allowed_core_fact_ids', 'core_facts'}
        layout = {'core_fact_order': projection['allowed_core_fact_ids'][::-1]}
        if mode == 'invalid_layout': layout['core_fact_order'][0] = 'invented'
        return httpx.Response(200, json={'id': 'offline-completion', 'model': body['model'],
            'object': 'chat.completion', 'created': 1,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'call-report', 'type': 'function',
                    'function': {'name': 'CoreFactOrder', 'arguments': json.dumps(layout)}}]}}]})
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(respond))
    results = []
    class Service:
        async def execute(self, symptom, **kwargs):
            current, diagnosis, _ = report_input()
            result = await reporting.finalize_report(current, update_for(diagnosis))
            results.append(result)
            yield {'type': 'complete', 'thread_id': current['thread_id'],
                'response': result['response'], 'diagnosis': result['diagnosis']}
        async def close(self): pass
    async def save_audit(*args):
        (tmp_path / 'report-generation.json').write_text(json.dumps(results[0]['investigation_memory']['report']))
        return {'passed': True, 'behavior': {'status': 'passed'}}
    monkeypatch.setattr(graph, 'AIOpsService', Service)
    monkeypatch.setattr(evaluation, 'save_mechanism_audit', AsyncMock(side_effect=save_audit))
    args = SimpleNamespace(previous_cost=None, budget_limit_cny=5,
        run_budget_cny=0.000001 if mode == 'budget' else 1,
        local_runbooks=None, knowledge_mcp_url=None, knowledge_disabled=True,
        symptom_file=None, mechanism_group=None, report_model=True, max_output_tokens=1024)
    cfg = ProbeConfig('test-target', 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'token')
    await evaluation.run_model(args, cfg, tmp_path, [], 'offline only')
    assert reporting.create_agent_llm is original_factory
    summary = json.loads((tmp_path / 'summary.json').read_text())
    ledger = json.loads((tmp_path / 'cost.json').read_text())
    record = json.loads((tmp_path / 'evaluation-record.json').read_text())
    assert record['config']['report_model_enabled'] is True
    assert summary['report_generation_passed'] is (mode == 'valid')
    assert summary['report_generation']['mode'] == ('model' if mode == 'valid' else 'rules')
    assert record['status'] == ('completed' if mode == 'valid' else 'incomplete')
    assert summary['report_generation']['request_numbers'] == ([] if mode == 'budget' else [1])
    if mode == 'budget':
        assert network == [] and ledger['requests'] == []
        assert ledger['blocked_requests'][0]['sent'] is False
        assert summary['budget_stopped']
    else:
        assert len(network) == len(ledger['requests']) == 1
        assert ledger['requests'][0]['input_sha256']
    if mode == 'primary_transient':
        # Provider fallback is retained, but the prior-unknown-usage guard must win.
        assert ledger['blocked_requests'][-1]['reason_code'] == 'previous_request_usage_unknown'
        assert ledger['blocked_requests'][-1]['model'] == 'deepseek-v4-flash'
        assert summary['report_generation']['status'] == 'degraded'
    if mode == 'valid':
        assert ledger['requests'][0]['usage']['prompt_tokens'] == 100
        assert ledger['requests'][0]['pricing_verified'] is True


def test_report_model_cli_requires_paid_mode():
    from scripts.evaluate_windows_probe import parse_args
    with pytest.raises(SystemExit): parse_args(['--report-model'])
    assert parse_args(['--run-model', '--report-model']).report_model



def test_conflicts_and_unresolved_cause_survive_any_layout():
    from src.agent.aiops import reporting
    current, diagnosis, records = report_input(two_faults=True)
    diagnosis['observation_conflicts'] = [{'reason': '端口采样存在冲突，尚未消解'}]
    diagnosis['limitations'] = ['采样只覆盖允许对象']
    diagnosis['unresolved_questions'].append({'id': 'gap-dependency-history',
        'question': '停止由谁触发？', 'limitation': '无历史来源'})
    bundle = reporting.build_bundle(diagnosis, records=records, resolution=current['target_resolution'])
    layout = reporting.rule_layout(bundle)
    layout.focus_object_ids.reverse()
    report = reporting.render_report(bundle, layout)
    assert '端口采样存在冲突，尚未消解' in report and '停止由谁触发？' in report
    assert '无历史来源' in report and bundle['limitations'] == ['采样只覆盖允许对象']
    assert '进程崩溃' not in report


@pytest.mark.asyncio
async def test_model_view_events_checkpoint_and_closed_reopen_are_identical(tmp_path, engine, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sqlalchemy.orm import sessionmaker
    from src.agent.aiops import reporting, run_store
    graph_module = importlib.import_module('src.agent.aiops.graph')
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'TERMCP_ENABLED', False)
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(tmp_path / 'report.sqlite'))
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    current, diagnosis, _ = report_input()
    async def planner(state):
        return {key: current[key] for key in ('raw_evidence', 'target_resolution')} | {'plan': ['finish']}
    async def executor(state): return {'plan': []}
    class Strategy:
        async def decide(self, state): return update_for(diagnosis)
    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    monkeypatch.setattr(graph_module.AIOpsService, '_create_run_strategy', lambda *a: Strategy())
    monkeypatch.setattr(reporting, 'create_agent_llm', lambda **kw: SimpleNamespace(max_tokens=4096))
    async def compose(model, schema, prompt, inputs, **kwargs):
        projection = json.loads(inputs['projection'])
        return reporting.CoreFactOrder(core_fact_order=projection['allowed_core_fact_ids'][::-1])
    invoke = AsyncMock(side_effect=compose)
    monkeypatch.setattr(reporting, 'ainvoke_structured', invoke)
    service = graph_module.AIOpsService()
    try:
        with reporting.report_model_session(tmp_path, lambda: []):
            events = [e async for e in service.execute('report fixture', user_id=17)]
        final = next(e for e in events if e['type'] == 'complete')
        report_event = next(e for e in events if e['type'] == 'report')
        assert report_event['report'] == final['response']
        assert report_event['diagnosis'] == final['diagnosis']
        tid = final['thread_id']
        assert run_store.get_run(tid).report == final['response']
    finally:
        await service.close()
    reopened = graph_module.AIOpsService()
    try:
        with reporting.report_model_session(tmp_path, lambda: []):
            graph = await reopened._persistent_graph(Strategy())
            saved = (await graph.aget_state({'configurable': {'thread_id': tid}})).values
            details = await reopened.run_details(tid)
            assert details['diagnosis'] == final['diagnosis']
            assert saved['response'] == final['response']
            record = saved['investigation_memory']['report']
            assert record['mode'] == 'model'
            assert reporting.render_report(record['bundle'], reporting.ReportLayout(**record['layout'])) == final['response']
            assert all(a['action'] in final['response'] for a in details['diagnosis']['recommendations'])
            await reopened.run_details(tid)
        invoke.assert_awaited_once()
    finally:
        await reopened.close()
