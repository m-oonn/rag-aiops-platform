import json
from unittest.mock import AsyncMock

import httpx
import pytest

from src.agent.aiops.strategies import investigation as module


def state(payload=None):
    return {"input": "service unavailable", "plan": [], "past_steps": [("查日志", "summary")],
            "raw_evidence": [("查日志", json.dumps(payload or {
                "data_source": "diagnostic_target", "content": "connection refused; worker healthy",
            }))]}


def decision(**kwargs):
    return module.InvestigationDecision(hypothesis="dependency down", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('answer', ['corrected', 'still_missing', 'forbidden', 'timeout'])
async def test_missing_check_contract_gets_one_model_correction(monkeypatch, protection, trigger, answer):
    from copy import deepcopy
    current = state()
    current['investigation_tools'] = [{'name': 'diagnostic_query'}]
    current['investigation_config'] = {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}
    before = deepcopy(current)
    invalid = decision(next_check='inspect permitted logs', next_tools=['diagnostic_query'])
    valid = invalid.model_copy(deep=True)
    valid.discriminating_question = 'application error or downstream error?'
    valid.expected_observation = 'actual log exception and dependency status'
    second = {'corrected': valid, 'still_missing': invalid, 'forbidden': valid.model_copy(
        update={'next_tools': ['not_available']}), 'timeout': httpx.ReadTimeout('offline') }[answer]
    invoke = AsyncMock(side_effect=[invalid, second])
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    result = await module.InvestigationStrategy().decide(current)
    assert invoke.await_count == 2 and current == before
    feedback = json.loads(invoke.call_args.args[3]['check_feedback'])
    assert feedback['missing_fields'] == ['decision.discriminating_question', 'decision.expected_observation']
    assert feedback['rejected_model_suggestion'] == invalid.model_dump()
    correction = result['investigation_memory']['check_correction']
    assert correction['attempts'] == 1
    assert bool(result.get('plan')) is (answer == 'corrected')
    assert correction['status'] == ('continued' if answer == 'corrected' else 'model_request_failed' if answer == 'timeout' else 'rejected')


@pytest.mark.asyncio
async def test_structured_failure_returns_incomplete_report_with_evidence(monkeypatch):
    from src.agent.aiops.structured import StructuredOutputError
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(side_effect=StructuredOutputError('invalid output')))
    current = state()
    before = list(current['raw_evidence'])
    result = await module.InvestigationStrategy().decide(current)
    assert result['response'].startswith('未定位根因')
    assert '结构化' in result['response']
    assert '[e1.1]' in result['response']
    assert 'connection refused' in result['response']
    assert current['raw_evidence'] == before
    assert result['plan'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('error', ['missing_path', 'unconfigured_events', 'still_invalid'])
async def test_invalid_probe_check_gets_one_feedback_and_keeps_guards(monkeypatch, protection, trigger, error):
    from copy import deepcopy
    from src.probe.protocol import evidence
    from src.settings import settings
    from scripts.mechanism_behavior import behavior_snapshot
    from datetime import datetime, timezone
    current = state(evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={
        'configured_services': {'entry': {'kind': 'process', 'text_logs_available': True,
            'text_logs': ['D:/allowed/app.log'], 'event_logs_available': False}}}))
    current['investigation_config'] = {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}
    current['investigation_tools'] = [{'name': name} for name in ['probe_text_log', 'probe_event_logs']]
    invalid = decision(next_check='inspect logs', next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'entry'}},
        discriminating_question='application or dependency failure?', expected_observation='logged exception')
    if error == 'unconfigured_events':
        invalid.next_tools = ['probe_event_logs']
        invalid.next_arguments = {'probe_event_logs': {'service': 'entry'}}
    valid = invalid.model_copy(deep=True)
    valid.next_tools = ['probe_text_log']
    valid.next_arguments = {'probe_text_log': {'service': 'entry', 'path': 'D:/allowed/app.log'}}
    invoke = AsyncMock(side_effect=[invalid, invalid if error == 'still_invalid' else valid])
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    before = deepcopy(current)
    result = await module.InvestigationStrategy().decide(current)
    assert current == before and invoke.await_count == 2
    correction = result['investigation_memory']['check_correction']
    assert correction['validation_error'] and correction['attempts'] == 1
    assert correction['missing_fields'] == []
    assert correction['rejected_model_suggestion'] == invalid.model_dump()
    assert bool(result['plan']) is (error != 'still_invalid')
    assert correction['status'] == ('rejected' if error == 'still_invalid' else 'continued')
    snapshot = behavior_snapshot({**current, **result}, datetime.now(timezone.utc).isoformat())
    assert snapshot['behavior_context']['check_correction'] == correction


@pytest.mark.asyncio
async def test_transient_model_failure_returns_incomplete_report_with_evidence(monkeypatch):
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(side_effect=httpx.ReadTimeout('mock timeout')))
    current = state()
    result = await module.InvestigationStrategy().decide(current)
    assert result['response'].startswith('未定位根因')
    assert '模型决策请求失败' in result['response']
    assert 'ReadTimeout' in result['response']
    assert '[e1.1]' in result['response']
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['plan'] == []


@pytest.mark.asyncio
async def test_permanent_model_failure_is_not_hidden(monkeypatch):
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(side_effect=ValueError('bad prompt')))
    with pytest.raises(ValueError, match='bad prompt'):
        await module.InvestigationStrategy().decide(state())


@pytest.mark.asyncio
async def test_decision_receives_tool_capabilities_and_execution_failures(monkeypatch):
    invoke = AsyncMock(return_value=decision(blocked_reason='no permitted checks'))
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    current = state()
    current['investigation_tools'] = [{'name': 'probe_port_snapshot', 'description': 'bounded snapshot', 'parameters': ['limit']}]
    current['target_resolution'] = {'status': 'resolved', 'allowed_services': ['entry', 'worker'],
                                    'allowed_dependencies': ['entry', 'db']}
    current['raw_evidence'].append(('unsupported service', json.dumps({
        'data_source': 'tool_execution', 'tool': 'probe_service_status',
        'arguments': {'service': 'sshd'}, 'status': 'unavailable', 'reason': 'service_not_configured'})))
    await module.InvestigationStrategy().decide(current)
    inputs = invoke.call_args.args[3]
    assert 'probe_port_snapshot' in inputs['capabilities']
    assert 'service_not_configured' in inputs['checks']
    assert 'sshd' in inputs['checks']
    assert 'progress' in inputs
    assert json.loads(inputs['target_resolution']) == current['target_resolution']
    assert '本次已解析业务范围' in module._PROMPT.format(**inputs)


@pytest.mark.asyncio
async def test_reference_guidance_reaches_decision_but_cannot_support_root_cause(monkeypatch):
    answer = decision(root_cause='dependency stopped',
        supporting_evidence=[module.Citation(evidence_id='e1.1', quote='handbook-only diagnosis')],
        alternatives=[module.Alternative(explanation='other cause', status='unavailable', limitation='not observable')])
    invoke = AsyncMock(return_value=answer)
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    current = state()
    current['investigation_reference_context'] = 'localapp downstream handbook-only diagnosis password=do-not-store'
    result = await module.InvestigationStrategy().decide(current)
    inputs = invoke.call_args.args[3]
    assert 'handbook-only diagnosis' in inputs['references']
    assert 'do-not-store' not in inputs['references']
    assert 'handbook-only diagnosis' not in inputs['evidence']
    assert result['response'].startswith('未定位根因')


@pytest.mark.asyncio
@pytest.mark.parametrize('corrected', [True, False])
async def test_rejected_health_claim_gets_one_feedback_attempt_without_bypassing_gate(monkeypatch, corrected):
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'orders', 'state': 'running'})
    citation = module.Citation(evidence_id='e1.1', quote='running')
    invalid = decision(outcome='healthy', conclusion_level='healthy_within_scope', scope='本次orders状态',
        supporting_evidence=[citation], alternatives=[module.Alternative(
            explanation='历史故障已排除', status='excluded', evidence=[citation])])
    valid = invalid.model_copy(deep=True)
    valid.alternatives = [module.Alternative(explanation='services/orders: state == "stopped"',
        status='excluded', claim_type='observed_condition', evidence=[citation],
        condition=module.ObservationCondition(operation='services', object_name='orders',
            field='state', expected='stopped'))]
    invoke = AsyncMock(side_effect=[invalid, valid if corrected else invalid])
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    result = await module.InvestigationStrategy().decide(state(raw))
    assert invoke.await_count == 2
    feedback = json.loads(invoke.call_args.args[3]['health_feedback'])
    assert feedback['validation_issues'] and feedback['rejected_model_suggestion'] == invalid.model_dump()
    assert result['diagnosis']['kind'] == ('healthy_within_scope' if corrected else 'unlocated')
    assert result['investigation_memory']['health_correction']['attempts'] == 1
    assert result['investigation_memory']['health_correction']['status'] == result['diagnosis']['kind']


@pytest.mark.asyncio
async def test_health_feedback_does_not_expose_unsaved_candidate_id(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'orders', 'state': 'running'})
    citation = module.Citation(evidence_id='e1.1', quote='running')
    invalid = decision(outcome='healthy', conclusion_level='healthy_within_scope', scope='本次orders状态',
        supporting_evidence=[citation], alternatives=[module.Alternative(
            explanation='services/orders: state == "running"', status='supported',
            claim_type='observed_condition', evidence=[citation],
            condition=module.ObservationCondition(operation='services', object_name='orders',
                field='state', expected='running'))])
    current = state(raw)
    rejected = module.decide_from_evidence(current, invalid, module.evidence_index(current),
        require_concrete_checks=True)
    assert rejected['diagnosis']['kind'] == 'unlocated'
    assert rejected['diagnosis']['alternatives'][0]['hypothesis_id']
    invoke = AsyncMock(side_effect=[invalid, invalid])
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    result = await module.InvestigationStrategy().decide(current)
    assert invoke.await_count == 2
    feedback = json.loads(invoke.call_args.args[3]['health_feedback'])
    assert feedback['validated_alternatives'][0]['hypothesis_id'] == ''
    assert result['diagnosis']['kind'] == 'unlocated'
    assert 'investigation_memory' not in current


@pytest.mark.asyncio
async def test_healthy_decision_binds_missing_citations_from_complete_probe_records(monkeypatch):
    from src.probe.protocol import evidence
    target = 'windows-local-01'
    current = state()
    current['target_resolution'] = {
        'status': 'resolved', 'target_id': target,
        'allowed_services': ['localapp', 'downstream'],
        'allowed_dependencies': ['localapp', 'downstream'],
        'services': {
            'localapp': {'kind': 'process', 'process_names': ['python.exe']},
            'downstream': {'kind': 'process', 'process_names': ['python.exe']},
        },
    }
    records = [
        evidence(target_id=target, operation='inventory', payload={
            'configured_services': {
                'localapp': {'kind': 'process', 'process_names': ['python.exe']},
                'downstream': {'kind': 'process', 'process_names': ['python.exe']},
            }}),
        evidence(target_id=target, operation='dependency_probe', payload={
            'dependency': 'localapp', 'tcp': 'ok', 'http': {'status': 200}}),
        evidence(target_id=target, operation='dependency_probe', payload={
            'dependency': 'downstream', 'tcp': 'ok', 'http': {'status': 200}}),
        evidence(target_id=target, operation='processes', payload={
            'service': 'localapp', 'processes': [{'pid': 1}],
            'matched_count': 1, 'skipped_count': 0}),
        evidence(target_id=target, operation='processes', payload={
            'service': 'downstream', 'processes': [{'pid': 2}],
            'matched_count': 1, 'skipped_count': 0}),
    ]
    current['raw_evidence'].extend((f'probe-{i}', item) for i, item in enumerate(records))
    healthy = decision(outcome='healthy', conclusion_level='healthy_within_scope',
        scope='当前窗口内核查 localapp、downstream、进程与入口')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(side_effect=[healthy, healthy]))

    result = await module.InvestigationStrategy().decide(current)

    assert result['diagnosis']['kind'] == 'healthy_within_scope'
    assert result['plan'] == []
    assert result['diagnosis']['evidence']
    assert result['diagnosis']['alternatives']


@pytest.mark.asyncio
async def test_healthy_decision_does_not_reuse_success_superseded_by_newer_failed_probe(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from src.probe.protocol import evidence
    target = 'windows-local-01'
    now = datetime.now(timezone.utc)
    current = state()
    current['target_resolution'] = {
        'status': 'resolved', 'target_id': target,
        'allowed_services': ['app'], 'allowed_dependencies': ['db'],
        'services': {'app': {'kind': 'process', 'process_names': ['app.exe']}},
    }
    inventory = evidence(target_id=target, operation='inventory', payload={
        'configured_services': {'app': {'kind': 'process', 'process_names': ['app.exe']}}})
    old_success = evidence(target_id=target, operation='dependency_probe', payload={
        'dependency': 'db', 'tcp': 'ok', 'http': {'status': 200}},
        collected_at=(now - timedelta(seconds=10)).isoformat())
    latest_failure = evidence(target_id=target, operation='dependency_probe', payload={
        'dependency': 'db', 'tcp': 'unknown', 'http': {'error': 'ReadTimeout'},
        'error': 'ReadTimeout'}, collected_at=now.isoformat())
    app_process = evidence(target_id=target, operation='processes', payload={
        'service': 'app', 'processes': [{'pid': 10, 'name': 'app.exe'}],
        'matched_count': 1, 'skipped_count': 0})
    current['raw_evidence'].extend((f'probe-{i}', item) for i, item in enumerate(
        [inventory, old_success, latest_failure, app_process]))
    healthy = decision(outcome='healthy', conclusion_level='healthy_within_scope',
        scope='当前窗口内核查 app 与 db')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(side_effect=[healthy, healthy]))

    result = await module.InvestigationStrategy().decide(current)

    assert result['diagnosis']['kind'] == 'unlocated'
    assert 'db' in result['diagnosis']['conclusion'] or 'db' in result['response']


@pytest.mark.asyncio
async def test_plan_exhaustion_selects_a_new_check(monkeypatch):
    invoke = AsyncMock(return_value=decision(next_check="核实依赖监听端口"))
    monkeypatch.setattr(module, "ainvoke_structured", invoke)
    result = await module.InvestigationStrategy().decide(state())
    assert result["plan"] == ["核实依赖监听端口"]
    assert "response" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['purpose', 'outcome', 'tools', 'unknown_tool'])
async def test_followup_with_catalog_requires_an_executable_discriminating_check(monkeypatch, missing):
    kwargs = dict(next_check='再看一次内存', next_tools=['probe_resource_snapshot'],
                  discriminating_question='瞬时峰值还是仍然升高',
                  expected_observation='可用内存恢复会削弱持续耗尽解释')
    if missing == 'purpose': kwargs['discriminating_question'] = ' '
    if missing == 'outcome': kwargs['expected_observation'] = ''
    if missing == 'tools': kwargs['next_tools'] = []
    if missing == 'unknown_tool': kwargs['next_tools'] = ['probe_exec']
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=decision(**kwargs)))
    current = state()
    current['investigation_tools'] = [{'name': 'probe_resource_snapshot'}]
    result = await module.InvestigationStrategy().decide(current)
    assert result['plan'] == []
    assert result['response'].startswith('未定位根因')
    assert '检查' in result['response']
    assert '[e1.1]' in result['response']


@pytest.mark.asyncio
async def test_discriminating_resample_remains_executable_with_catalog(monkeypatch):
    answer = decision(next_check='复核内存回落', next_tools=['probe_resource_snapshot'],
        next_arguments={'probe_resource_snapshot': {}},
        discriminating_question='是否为瞬时占用', expected_observation='可用内存回升削弱持续耗尽解释')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    current = state()
    current['past_steps'] = [('采样', 'high memory')] * 40
    current['investigation_tools'] = [{'name': 'probe_resource_snapshot'}]
    result = await module.InvestigationStrategy().decide(current)
    assert result['plan'] == ['复核内存回落']
    assert result['investigation_memory']['next_tools'] == ['probe_resource_snapshot']
    assert 'response' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("source,quote", [("mock", "connection refused"),
                                           ("tool_execution", "connection refused"),
                                           ("unavailable", "connection refused"),
                                           ("diagnostic_target", "fabricated quote")])
async def test_unsupported_root_cause_cannot_finish_as_found(monkeypatch, source, quote):
    answer = decision(root_cause="dependency down",
        supporting_evidence=[module.Citation(evidence_id="e1.1", quote=quote)],
        alternatives=[module.Alternative(explanation="worker failed", status="unavailable",
                                        limitation="permission missing")])
    monkeypatch.setattr(module, "ainvoke_structured", AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(state({"data_source": source,
                                                             "content": "connection refused"}))
    assert result["response"].startswith("未定位根因")


@pytest.mark.asyncio
async def test_cited_evidence_and_checked_alternative_produce_traceable_report(monkeypatch):
    answer = decision(root_cause="dependency down",
        conclusion_level='confirmed_cause', scope='configured dependency',
        supporting_evidence=[module.Citation(evidence_id="e1.1", quote="connection refused")],
        alternatives=[module.Alternative(explanation="worker failed", status="excluded",
            evidence=[module.Citation(evidence_id="e1.1", quote="worker healthy")])])
    monkeypatch.setattr(module, "ainvoke_structured", AsyncMock(return_value=answer))
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs',
        payload={'lines': ['connection refused; worker healthy']})
    result = await module.InvestigationStrategy().decide(state(raw))
    assert result["response"].startswith("未定位根因")
    assert "[e1.1] connection refused" in result["response"]


@pytest.mark.asyncio
async def test_investigation_report_keeps_knowledge_references(monkeypatch):
    answer = decision(root_cause="dependency down",
        supporting_evidence=[module.Citation(evidence_id="e1.1", quote="connection refused")],
        alternatives=[module.Alternative(explanation="worker failed", status="excluded",
            evidence=[module.Citation(evidence_id="e1.1", quote="worker healthy")])])
    monkeypatch.setattr(module, "ainvoke_structured", AsyncMock(return_value=answer))
    current = state()
    current["raw_evidence"].append(("查知识库", json.dumps({
        "data_source": "knowledge_base", "source": "db-connectivity.md",
        "page": 2, "chunk_id": "chunk-db-2", "content": "检查数据库连接被拒绝"})))
    result = await module.InvestigationStrategy().decide(current)
    assert "## 参考知识库" in result["response"]
    assert "db-connectivity.md" in result["response"]
    assert "chunk-db-2" in result["response"]


@pytest.mark.asyncio
async def test_mid_investigation_knowledge_reaches_decision_without_becoming_live_evidence(monkeypatch):
    answer = decision(root_cause='handbook diagnosis',
        supporting_evidence=[module.Citation(evidence_id='e2.1', quote='check downstream independently')],
        alternatives=[module.Alternative(explanation='other cause', status='unavailable', limitation='not observable')])
    invoke = AsyncMock(return_value=answer)
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    current = state()
    current['raw_evidence'].append(('查知识库', json.dumps({'data_source': 'knowledge_base',
        'kb_id': 14, 'results': [{'source': 'localapp.md', 'page': 2, 'chunk_id': 'kb-late',
        'content': 'check downstream independently password=do-not-forward'}]})))
    result = await module.InvestigationStrategy().decide(current)
    knowledge = json.loads(invoke.call_args.args[3]['knowledge'])
    assert knowledge[0]['chunk_id'] == 'kb-late'
    assert 'check downstream independently' in knowledge[0]['content']
    assert 'do-not-forward' not in str(knowledge)
    assert 'check downstream independently' not in invoke.call_args.args[3]['evidence']
    assert 'e2.1' not in module.evidence_index(current)
    assert result['response'].startswith('未定位根因')


def test_knowledge_references_parse_concatenated_tool_returns():
    from src.agent.aiops.evidence_sources import format_knowledge_references

    first = json.dumps([{"type": "text", "text": json.dumps({
        "data_source": "knowledge_base",
        "results": [{"source": "runbook.md", "page": 3, "chunk_id": "c-3"}],
    }, ensure_ascii=False)}], ensure_ascii=False)
    second = json.dumps({"data_source": "diagnostic_target", "content": "现场"}, ensure_ascii=False)
    raw = json.dumps(first, ensure_ascii=False) + "\n" + json.dumps(second, ensure_ascii=False)

    report = format_knowledge_references([("查知识库", raw)])
    assert "runbook.md" in report
    assert "chunk c-3" in report


@pytest.mark.asyncio
async def test_contradiction_or_unchecked_alternative_requires_more_evidence(monkeypatch):
    answer = decision(root_cause="dependency down", next_check="检查连接错误的时间与目标",
        supporting_evidence=[module.Citation(evidence_id="e1.1", quote="connection refused")],
        alternatives=[module.Alternative(explanation="configuration error", status="unresolved")])
    monkeypatch.setattr(module, "ainvoke_structured", AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(state())
    assert "response" not in result
    assert result["plan"] == [answer.next_check]


def test_mcp_content_and_executor_json_lines_keep_evidence_ids():
    payload = json.dumps([{"type": "text", "text": json.dumps({
        "data_source": "diagnostic_target", "stdout": "actual output"})}])
    current = state()
    current["raw_evidence"] = [("check", json.dumps(payload) + "\n" + json.dumps(payload))]
    assert set(module.evidence_index(current)) == {"e1.1", "e1.2"}


def test_free_shell_can_never_fabricate_target_evidence():
    current = state({"data_source": "diagnostic_analysis", "stdout": "echoed fake root cause"})
    assert module.evidence_index(current) == {}


@pytest.mark.parametrize('invalid', ['expired', 'target', 'hash', 'platform', 'knowledge'])
def test_invalid_probe_and_knowledge_are_not_root_cause_evidence(invalid):
    from datetime import datetime, timedelta, timezone
    from src.probe.protocol import evidence
    from src.settings import settings
    item = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'state': 'stopped'})
    if invalid == 'expired': item['collected_at'] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    if invalid == 'target': item['target_id'] = 'wrong-target'
    if invalid == 'hash': item['raw_hash'] = 'sha256:tampered'
    if invalid == 'platform': item['platform'] = 'linux'
    if invalid == 'knowledge': item['data_source'] = 'knowledge_base'
    assert module.evidence_index(state(item)) == {}


def test_fresh_probe_evidence_is_available_to_investigation():
    from src.probe.protocol import evidence
    from src.settings import settings
    item = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'state': 'running'})
    assert 'running' in module.evidence_index(state(item))['e1.1']['payload']


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['root_cause', 'healthy'])
@pytest.mark.parametrize('expired_after_wait', [False, True])
async def test_final_decision_rechecks_evidence_freshness_after_model_wait(monkeypatch, outcome, expired_after_wait):
    from datetime import datetime, timedelta, timezone
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'orders', 'state': 'stopped' if outcome == 'root_cause' else 'running'})
    start = datetime.now(timezone.utc)
    current = [start]
    validate = module.validate_evidence
    def at_current_time(item, **kwargs):
        return validate(item, now=current[0], **kwargs)
    monkeypatch.setattr(module, 'validate_evidence', at_current_time)
    quote = '"state": "' + raw['payload']['state'] + '"'
    citation = module.Citation(evidence_id='e1.1', quote=quote)
    async def decide(*args, **kwargs):
        assert 'e1.1' in json.loads(args[3]['evidence'])
        if expired_after_wait:
            current[0] = start + timedelta(seconds=181)
        return decision(outcome=outcome, root_cause='service stopped' if outcome == 'root_cause' else '',
            conclusion_level='localized_fault' if outcome == 'root_cause' else 'healthy_within_scope',
            localized_fault='service stopped' if outcome == 'root_cause' else '', scope='queried service',
            supporting_evidence=[citation],
            alternatives=[module.Alternative(explanation='services/orders: state == "stopped"', status='excluded', evidence=[citation],
                claim_type='observed_condition',
                condition=module.ObservationCondition(operation='services', object_name='orders', field='state', expected='stopped'))])
    monkeypatch.setattr(module, 'ainvoke_structured', decide)
    result = await module.InvestigationStrategy().decide(state(raw))
    if expired_after_wait:
        assert result['response'].startswith('未定位根因')
        assert '等待模型后现场证据未通过重新校验：e1.1' in result['response']
        assert '已核查替代解释' not in result['response']
        assert result['investigation_memory']['alternatives'][0]['status'] == 'unresolved'
    else:
        assert result['response'].startswith('已定位故障层：' if outcome == 'root_cause' else '当前检查范围内未发现故障')


@pytest.mark.asyncio
async def test_blocked_report_keeps_verified_provenance_and_unresolved_explanations(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={'cpu_percent': 42})
    answer = decision(blocked_reason='coverage limited',
        supporting_evidence=[module.Citation(evidence_id='e1.1', quote='"cpu_percent": 42'),
                             module.Citation(evidence_id='e1.1', quote='fabricated')],
        alternatives=[module.Alternative(explanation='long term load', status='unresolved', limitation='short sample')],
        contradictions=['needs another time window'])
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(state(raw))
    report = result['response']
    assert report.startswith('未定位根因')
    assert '[e1.1]' in report and '"cpu_percent": 42' in report
    for field in ('target_id', 'collected_at', 'data_source', 'raw_hash'):
        assert str(raw[field]) in report
    assert 'fabricated' not in report
    assert 'long term load' in report and 'short sample' in report
    assert 'needs another time window' in report


@pytest.mark.asyncio
async def test_localized_stop_does_not_claim_available_checks_are_exhausted(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989,
        'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    answer = decision(blocked_reason='当前没有新的可执行检查')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    current = state()
    current['raw_evidence'] = [('downstream probe', json.dumps(raw))]
    current['investigation_tools'] = [{'name': 'probe_port_snapshot'}]

    result = await module.InvestigationStrategy().decide(current)

    assert result['diagnosis']['kind'] == 'localized_fault'
    assert '模型停止建议（检查覆盖未独立核验）' in result['diagnosis']['stop_reason']
    assert '系统未独立验证当前可用检查是否已穷尽' in result['response'] or '未独立核验' in result['response']


@pytest.mark.asyncio
async def test_localized_report_highlights_current_log_observations_without_confirming_cause(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    current = state()
    current['raw_evidence'] = [(name, json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload)))
        for name, operation, payload in [
            ('入口', 'dependency_probe', {'dependency': 'localapp', 'tcp': 'ok', 'http': {'status': 503}}),
            ('下游', 'dependency_probe', {'dependency': 'downstream', 'tcp': 'ok', 'http': {'status': 200}}),
            ('旧日志', 'text_logs', {'service': 'localapp', 'path': 'C:/demo/app.log', 'lines': ['old failure']}),
            ('当前日志', 'text_logs', {'service': 'localapp', 'path': 'C:/demo/app.log',
                'lines': ['ValueError: invalid max_attempts configuration']}),
            ('范围外日志', 'text_logs', {'service': 'other', 'path': 'C:/demo/other.log', 'lines': ['outside failure']}),
            ('失败查询', 'text_logs', {'service': 'localapp', 'path': 'C:/demo/denied.log',
                'error': 'denied', 'lines': ['unavailable failure']})]]
    current['target_resolution'] = {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_dependencies': ['localapp', 'downstream'], 'allowed_services': ['localapp']}
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=decision(blocked_reason='no new check')))

    result = await module.InvestigationStrategy().decide(current)
    notes = result['diagnosis']['observation_notes']
    log_note = next(note for note in notes if '现场日志观察' in note)
    assert 'localapp' in log_note and '[e4.1]' in log_note
    assert 'ValueError: invalid max_attempts configuration' in log_note
    assert log_note in result['response']
    assert result['response'].index(log_note) < result['response'].index('停止原因：')
    assert all(text not in '\n'.join(notes) for text in ['old failure', 'outside failure', 'unavailable failure'])
    assert '不作为因果确认' in log_note
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert '更深原因尚未确认' in result['response']


@pytest.mark.asyncio
async def test_failed_allowlisted_loopback_dependency_forces_exact_listener_check(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989,
        'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = state()
    current.update({'raw_evidence': [('downstream probe', json.dumps(raw))],
        'target_resolution': {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
            'allowed_dependencies': ['downstream'], 'allowed_services': [], 'services': {}},
        'investigation_tools': [{'name': 'probe_port_snapshot'}],
        'investigation_config': {'hypothesis_protection': False, 'contradiction_trigger': False}})
    answer = decision(blocked_reason='nothing else to inspect')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))

    result = await module.InvestigationStrategy().decide(current)
    memory = result['investigation_memory']
    assert result['plan'] == [memory['next_check']]
    assert memory['next_tools'] == ['probe_port_snapshot']
    assert '6989' in memory['next_check']
    assert memory['policy_selected_check']['arguments'] == {'local_port': 6989, 'listening_only': True}
    assert memory['model_suggestion']['blocked_reason'] == 'nothing else to inspect'
    assert not any(event['kind'] in {'protection_check_selected', 'contradiction_triggered'}
                   for event in memory['hypothesis_tracking']['events'])


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_stop_runs_current_unresolved_check_without_claiming_a_mechanism(protection, trigger):
    current = state()
    current.update(investigation_tools=[{'name': 'probe_text_log'}],
        investigation_config={'hypothesis_protection': protection, 'contradiction_trigger': trigger})
    check = module.CandidateCheck(next_check='核对入口配置解析错误的日志', next_tools=['probe_text_log'],
        discriminating_question='503是否伴随入口配置解析异常', expected_observation='本次请求对应的配置解析错误行')
    answer = decision(blocked_reason='故障层已定位', alternatives=[module.Alternative(
        explanation='入口配置解析异常', status='unresolved', check=check)])

    result = module.decide_from_evidence(current, answer, module.evidence_index(current))

    assert result['plan'] == [check.next_check]
    assert 'response' not in result
    assert result['investigation_memory']['model_suggestion']['next_check'] == ''
    assert result['investigation_memory']['next_tools'] == ['probe_text_log']
    assert not any(e['kind'] in {'protection_check_selected', 'contradiction_triggered'}
                   for e in result['investigation_memory']['hypothesis_tracking']['events'])


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('observed_path', ['C:/demo/downstream.log',
    r'C:\demo\downstream.log', r'c:\DEMO\.\downstream.log'])
def test_failed_dependency_checks_mapped_process_then_log_before_stopping(protection, trigger, observed_path):
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = [evidence(target_id=settings.PROBE_TARGET_ID, operation=op, payload=body) for op, body in [
        ('inventory', {'configured_services': {'worker': {'process_names': ['python.exe'],
            'process_identity_configured': True, 'text_logs_available': True,
            'text_logs': ['C:/demo/downstream.log'], 'event_logs_available': False}}}),
        ('dependency_probe', {'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'}),
        ('ports', {'local_port': 6989, 'listening_only': True, 'ports': []})]]
    current = {'input': 'localapp unavailable', 'past_steps': [],
        'raw_evidence': [(str(i), json.dumps(row)) for i, row in enumerate(raw)],
        'target_resolution': {'status': 'resolved', 'allowed_dependencies': ['downstream'],
            'allowed_services': ['worker'], 'dependency_services': {'downstream': 'worker'}, 'services': {}},
        'investigation_config': {'hypothesis_protection': protection, 'contradiction_trigger': trigger},
        'investigation_tools': [{'name': name} for name in ['probe_process_snapshot', 'probe_text_log']]}
    for operation, tool, args, body in [
        ('processes', 'probe_process_snapshot', {'service': 'worker'},
         {'service': 'worker', 'processes': [], 'skipped_count': 0}),
        ('text_logs', 'probe_text_log', {'service': 'worker', 'path': 'C:/demo/downstream.log', 'lines': 100},
         {'service': 'worker', 'path': observed_path, 'lines': []})]:
        result = module.decide_from_evidence(current, decision(blocked_reason='done'), module.evidence_index(current))
        assert result['plan'], result
        memory = result['investigation_memory']
        assert memory['next_tools'] == [tool]
        assert memory['policy_selected_check']['arguments'] == args
        assert memory['model_suggestion']['next_check'] == ''
        assert not any(e['kind'] in {'protection_check_selected', 'contradiction_triggered'}
                       for e in memory['hypothesis_tracking']['events'])
        current.update(result)
        current['past_steps'].append((result['plan'][0], 'observed'))
        current['raw_evidence'].append((tool, json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation=operation, payload=body))))
    assert module._mapped_dependency_check(current, module.evidence_index(current)) is None
    result = module.decide_from_evidence(current, decision(blocked_reason='done'), module.evidence_index(current))
    assert result['plan'] == []
    assert '日志为空' in result['response'] and '事件通道未配置' in result['response']
    assert '当前调查未获得该依赖对应' not in result['response']


@pytest.mark.parametrize('observed_service,observed_path', [
    ('worker', r'C:\demo\other.log'), ('other', r'C:\demo\downstream.log'),
    ('worker', None), ('worker', 42)])
def test_windows_log_comparison_preserves_distinct_files_and_services(observed_service, observed_path):
    from src.probe.protocol import evidence
    from src.settings import settings

    values = [('inventory', {'configured_services': {'worker': {
        'text_logs_available': True, 'text_logs': ['C:/demo/downstream.log']}}}),
        ('dependency_probe', {'dependency': 'db', 'host': '127.0.0.1', 'tcp': 'failed'}),
        ('text_logs', {'service': observed_service, 'path': observed_path, 'lines': []})]
    current = {'target_resolution': {'status': 'resolved', 'allowed_dependencies': ['db'],
        'allowed_services': ['worker'], 'dependency_services': {'db': 'worker'}},
        'investigation_tools': [{'name': 'probe_text_log'}],
        'raw_evidence': [(op, json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation=op, payload=body))) for op, body in values]}

    selected = module._mapped_dependency_check(current, module.evidence_index(current))
    assert selected[1] == {'service': 'worker', 'path': 'C:/demo/downstream.log', 'lines': 100}


@pytest.mark.parametrize('contradictions', [[], ['缺少退出原因，不能确认根因']])
@pytest.mark.parametrize('blocked_reason', ['', '没有其他检查'])
def test_completed_next_check_is_not_reported_as_missing_model_proposal(contradictions, blocked_reason):
    from src.probe.protocol import evidence
    from src.settings import settings

    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'})
    current = state(raw)
    result = module.decide_from_evidence(current, decision(next_check='查日志',
        blocked_reason=blocked_reason, contradictions=contradictions), module.evidence_index(current))

    assert result['plan'] == []
    reason = result['diagnosis']['stop_reason']
    assert '计划检查已执行' in reason
    assert '未独立验证' in reason
    assert '模型未提出' not in result['response']
    assert result['investigation_memory']['blocked_reason'] == reason


@pytest.mark.parametrize('boundary', ['remote', 'no_mapping', 'not_allowed', 'no_inventory', 'missing_tool', 'failed'])
def test_mapped_checks_do_not_expand_permissions_or_retry_failed_parameters(boundary):
    from src.probe.protocol import evidence
    from src.settings import settings
    values = [('inventory', {'configured_services': {'worker': {'process_names': ['python.exe']}}}),
              ('dependency_probe', {'dependency': 'db', 'host': '127.0.0.1', 'tcp': 'failed'})]
    current = {'target_resolution': {'status': 'resolved', 'allowed_dependencies': ['db'],
        'allowed_services': ['worker'], 'dependency_services': {'db': 'worker'}},
        'investigation_tools': [{'name': 'probe_process_snapshot'}]}
    if boundary == 'remote': values[1][1]['host'] = '192.0.2.1'
    if boundary == 'no_mapping': current['target_resolution']['dependency_services'] = {}
    if boundary == 'not_allowed': current['target_resolution']['allowed_services'] = []
    if boundary == 'no_inventory': values.pop(0)
    if boundary == 'missing_tool': current['investigation_tools'] = []
    current['raw_evidence'] = [(op, json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation=op, payload=body))) for op, body in values]
    if boundary == 'failed':
        current['raw_evidence'].append(('process', json.dumps({'data_source': 'tool_execution',
            'tool': 'probe_process_snapshot', 'arguments': {'service': 'worker'},
            'status': 'failed', 'reason': 'timeout'})))
    assert module._mapped_dependency_check(current, module.evidence_index(current)) is None


def test_stop_explains_missing_listener_tool_and_unmapped_downstream_process():
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'})
    current = state(raw)
    current.update(target_resolution={'status': 'resolved', 'allowed_dependencies': ['downstream'],
        'allowed_services': ['localapp'], 'services': {}}, investigation_tools=[])

    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))

    assert 'probe_port_snapshot' in result['response'] and '未加载' in result['response']
    assert 'downstream' in result['response'] and '进程' in result['response'] and '映射' in result['response']
    assert any('probe_port_snapshot' in reason for reason in result['diagnosis']['limitations'])


def test_failed_exact_listener_attempt_stops_with_failure_reason_instead_of_rescheduling():
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'})
    current = state(raw)
    current.update(target_resolution={'status': 'resolved', 'allowed_dependencies': ['downstream'],
        'allowed_services': [], 'services': {}}, investigation_tools=[{'name': 'probe_port_snapshot'}])
    current['raw_evidence'].append(('核查6989监听', json.dumps({'data_source': 'tool_execution',
        'tool': 'probe_port_snapshot', 'arguments': {'local_port': 6989, 'listening_only': True},
        'status': 'failed', 'reason': 'timeout'})))
    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))
    assert result['plan'] == []
    assert 'timeout' in result['response'] and '采集失败' in result['response']


def test_unverified_causal_display_preserves_the_specific_data_limit():
    alternative = module.Alternative(explanation='下游崩溃', status='unresolved',
        verification='causal_claim_unverified', limitation='Windows事件通道未配置，退出历史不可查')
    public = module._public_alternative(alternative)
    assert '事件通道未配置' in public['limitation']
    assert public['explanation'] != alternative.explanation


@pytest.mark.parametrize('boundary', ['completed', 'missing_tool', 'outside_scope', 'failed'])
def test_stop_does_not_reschedule_unavailable_or_completed_candidate_checks(boundary):
    check = module.CandidateCheck(next_check='核查database连接', next_tools=['probe_dependency_probe'],
        discriminating_question='database是否可连接', expected_observation='连接状态')
    alternative = module.Alternative(explanation='database连接异常', status='unresolved', check=check,
        condition=module.ObservationCondition(operation='dependency_probe', object_name='database',
                                             field='tcp', expected='failed'))
    current = state()
    current.update(investigation_tools=[{'name': 'probe_dependency_probe'}],
        target_resolution={'status': 'resolved', 'allowed_dependencies': ['database']})
    if boundary == 'completed':
        current['past_steps'].append((check.next_check, 'result'))
    elif boundary == 'missing_tool':
        current['investigation_tools'] = []
    elif boundary == 'outside_scope':
        current['target_resolution']['allowed_dependencies'] = []
    else:
        current['raw_evidence'].append((check.next_check, json.dumps({'data_source': 'tool_execution',
            'tool': 'probe_dependency_probe', 'status': 'failed', 'reason': 'timeout'})))
    result = module.decide_from_evidence(current, decision(alternatives=[alternative]), module.evidence_index(current))
    assert result['plan'] == []
    expected = {'completed': '已执行', 'missing_tool': '未加载', 'outside_scope': '允许对象', 'failed': 'timeout'}
    assert expected[boundary] in result['response']


def test_stop_does_not_call_an_unchecked_candidate_unavailable_without_a_plan():
    current = state()
    current['investigation_tools'] = [{'name': 'probe_text_log'}]
    result = module.decide_from_evidence(current, decision(alternatives=[module.Alternative(
        explanation='入口配置错误', status='unresolved')]), module.evidence_index(current))
    assert '模型未提供该问题的鉴别检查' in result['response']
    assert '声称无检查可做' in result['diagnosis']['limitations'][0]


def test_missing_dependency_address_is_not_reported_as_a_remote_target():
    from src.probe.protocol import evidence
    from src.settings import settings
    current = state(evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'tcp': 'failed'}))
    gaps = module.investigation_gaps(current, decision(), module.evidence_index(current))
    assert '未返回目标地址' in gaps[0]['limitation']
    assert '依赖在远端' not in gaps[0]['limitation']


def _configuration_error_evidence(*, event_logs_available=False, matching_hash=True):
    from src.probe.protocol import evidence
    from src.settings import settings

    path = 'D:/runtime/app.mode'
    source_hash = 'sha256:config-source'
    log_event = {'at': '2026-11-03T00:00:00Z', 'pid': 1234, 'status': 503,
        'error_type': 'ValueError', 'detail': 'invalid max_attempts configuration',
        'configuration': {'source': path, 'field': 'max_attempts', 'value': 'invalid',
            'expected': 'integer-convertible',
            'source_sha256': source_hash if matching_hash else 'sha256:other-source'}}
    raw = [
        ('inventory', evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={
            'configured_services': {'app': {'kind': 'process', 'process_names': ['app.exe'],
                'event_logs_available': event_logs_available, 'configuration_available': True,
                'text_logs_available': True}}, 'configured_dependencies': []})),
        ('log', evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
            'service': 'app', 'path': 'D:/runtime/app.log', 'lines': [json.dumps(log_event)]})),
        ('config', evidence(target_id=settings.PROBE_TARGET_ID, operation='configuration', payload={
            'service': 'app', 'path': path, 'source_sha256': source_hash,
            'values': {'max_attempts': 'invalid'}, 'missing_keys': []})),
    ]
    current = state()
    current.update(raw_evidence=[(step, json.dumps(payload)) for step, payload in raw],
        target_resolution={'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
            'allowed_services': ['app'], 'allowed_dependencies': [],
            'dependency_services': {}, 'services': {'app': {'probe_service': 'app'}}},
        investigation_tools=[{'name': 'probe_event_log'}])
    return current


def test_config_error_finding_requires_log_and_snapshot_to_match_exact_source():
    current = _configuration_error_evidence()
    records = module.evidence_index(current)
    findings = module._localized_findings(records, current)

    finding = next(row for row in findings if row['code'] == 'configuration_error_log_matches_snapshot')
    assert finding['causal'] is False
    assert len(finding['related_evidence']) == 1
    assert module._valid_citations([
        module.Citation(evidence_id=finding['evidence_id'], quote=finding['quote']),
        *[module.Citation(**ref) for ref in finding['related_evidence']],
    ], records)

    mismatched = _configuration_error_evidence(matching_hash=False)
    assert not module._configuration_error_findings(module.evidence_index(mismatched), mismatched)


def test_config_history_check_runs_only_when_event_channel_is_configured():
    current = _configuration_error_evidence(event_logs_available=True)
    check = module._configuration_history_check(current, module.evidence_index(current))
    assert check[0]['next_tools'] == ['probe_event_log']
    assert check[0]['next_arguments']['probe_event_log'] == {
        'service': 'app', 'since_minutes': 1440, 'limit': 200}

    current = _configuration_error_evidence(event_logs_available=False)
    assert module._configuration_history_check(current, module.evidence_index(current)) is None
    gaps = module.investigation_gaps(current, decision(), module.evidence_index(current))
    assert any('inventory 未配置可用事件通道' in row['limitation'] for row in gaps)


def test_config_report_is_actionable_and_keeps_details_out_of_main_text():
    current = _configuration_error_evidence()
    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))
    report, diagnosis = result['response'], result['diagnosis']
    advice = next(row for row in diagnosis['recommendations']
                  if row['finding_code'] == 'configuration_error_log_matches_snapshot')
    assert 'max_attempts' in advice['action'] and 'invalid' in advice['action']
    assert '整数' in advice['action']
    assert 'ValueError' in report and 'max_attempts' in report
    assert report.index('人工处理建议') < report.index('停止原因：')
    assert 'source_sha256' not in report
    assert 'sha256:config-source' not in report
    assert any(row['id'].startswith('gap-config-history-') for row in diagnosis['unresolved_questions'])
    assert '已复核' in diagnosis['stop_reason']
    assert '未核验' in diagnosis['stop_reason']
    assert all(ref['quote'] for ref in advice['evidence'])


def test_config_hash_mismatch_does_not_produce_config_repair_advice():
    current = _configuration_error_evidence(matching_hash=False)
    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))
    assert not result['diagnosis']['recommendations']


def test_config_report_explains_observed_failure_and_separates_history_gap():
    from src.probe.protocol import evidence
    current = _configuration_error_evidence()
    step, raw = current['raw_evidence'][1]
    observed = json.loads(raw)
    observed['payload']['lines'] *= 2
    current['raw_evidence'][1] = (step, json.dumps(evidence(target_id=observed['target_id'],
        operation='text_logs', payload=observed['payload'])))
    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))
    report = result['response']
    assert "配置字段 max_attempts='invalid'" in report
    assert '应用日志记录 ValueError' in report and 'HTTP 503' in report
    assert '优先支持配置解析失败这一解释' in report
    assert '日志陈述与独立快照的交叉支持，尚未独立复现因果' in report
    assert '更深原因尚未确认，不据此推断服务停止' not in report
    assert report.count('未查清：app 的配置错误由谁在何时引入？') == 1
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert all(row['causal'] is False for row in result['diagnosis']['observed_findings'])


def test_downstream_stop_log_is_reported_as_source_statement_with_unknown_actor():
    from src.probe.protocol import evidence
    from src.settings import settings
    current = state()
    current['raw_evidence'] = [(name, json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation=operation, payload=payload))) for name, operation, payload in [
        ('dependency', 'dependency_probe', {'dependency': 'downstream', 'host': '127.0.0.1',
            'port': 9100, 'tcp': 'failed'}),
        ('listener', 'ports', {'local_port': 9100, 'listening_only': True, 'ports': []}),
        ('process', 'processes', {'service': 'downstream', 'selection': 'top_accessible_processes',
            'inspected_count': 10, 'matched_count': 0, 'skipped_count': 0, 'processes': []}),
        ('log', 'text_logs', {'service': 'downstream', 'path': 'D:/test/downstream.log',
            'lines': [json.dumps({'event': 'shutdown_requested', 'reason': 'controlled_stop',
                'stop_request': {'channel': 'file_presence', 'initiator': 'unknown'}})]})]]
    current['investigation_tools'] = []
    result = module.decide_from_evidence(current, decision(), module.evidence_index(current))
    report = result['response']
    assert not result['plan']
    assert 'shutdown_requested' in report and 'controlled_stop' in report and 'unknown' in report
    assert '日志为应用自身记录' in report and '不作为因果确认' in report
    assert 'TCP=failed' in report and '返回范围内无监听' in report and '匹配0' in report
    assert '进程崩溃' not in report


def test_blocked_general_policy_does_not_hide_next_existing_legal_policy():
    from src.probe.protocol import evidence
    from src.settings import settings
    current = state()
    current['raw_evidence'] = [(name, json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation=operation, payload=payload))) for name, operation, payload in [
        ('inventory', 'inventory', {'configured_services': {'downstream': {
            'kind': 'process', 'process_names': ['worker.exe']}}}),
        ('dependency', 'dependency_probe', {'dependency': 'downstream', 'host': '127.0.0.1',
            'port': 9100, 'tcp': 'failed'})]]
    current['target_resolution'] = {'status': 'resolved', 'allowed_dependencies': ['downstream'],
        'allowed_services': ['downstream'], 'dependency_services': {'downstream': 'downstream'}}
    current['investigation_tools'] = [{'name': 'probe_port_snapshot'}, {'name': 'probe_process_snapshot'}]
    records = module.evidence_index(current)
    first = module._unverified_loopback_dependency_check(current, records)
    current['past_steps'].append((first[0]['next_check'], 'already attempted'))
    followup = module.dependency_followup_policy(current, records)
    assert followup['check']['next_tools'] == ['probe_process_snapshot']


@pytest.mark.parametrize(('resolution', 'host', 'include_tool', 'prior_snapshot', 'expected'), [
    ({'status': 'unmatched', 'allowed_dependencies': ['downstream']}, '127.0.0.1', True, False, False),
    ({'status': 'resolved', 'allowed_dependencies': []}, '127.0.0.1', True, False, False),
    ({'status': 'resolved', 'allowed_dependencies': ['downstream']}, '10.0.0.2', True, False, False),
    ({'status': 'resolved', 'allowed_dependencies': ['downstream']}, '127.0.0.1', False, False, False),
    ({'status': 'resolved', 'allowed_dependencies': ['downstream']}, '127.0.0.1', True, True, False),
])
def test_listener_check_requires_resolved_allowlisted_loopback_and_missing_snapshot(
        resolution, host, include_tool, prior_snapshot, expected):
    from src.probe.protocol import evidence
    from src.settings import settings

    dependency = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': host, 'port': 6989, 'tcp': 'failed'})
    raw = [('dependency', json.dumps(dependency))]
    if prior_snapshot:
        snapshot = evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
            'local_port': 6989, 'listening_only': True, 'ports': []})
        raw.append(('ports', json.dumps(snapshot)))
    records = module.evidence_index({'raw_evidence': raw})
    current = {'target_resolution': resolution,
        'investigation_tools': [{'name': 'probe_port_snapshot'}] if include_tool else []}
    selected = module._unverified_loopback_dependency_check(current, records)
    assert bool(selected) is expected


def test_loopback_dependency_port_snapshot_is_accepted_as_business_scoped_evidence():
    from src.probe.protocol import evidence
    from src.settings import settings

    dependency = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'})
    snapshot = evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
        'local_port': 6989, 'listening_only': True, 'ports': []})
    state = {'raw_evidence': [('dependency', json.dumps(dependency)), ('ports', json.dumps(snapshot))]}
    records = module.evidence_index(state)
    current = module.current_probe_records(records)
    scope = {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_dependencies': ['downstream'], 'services': {}}
    port_value = json.loads(current['e2.1']['payload'])
    assert module.in_business_scope(port_value, scope, current)
    assert not module.in_business_scope(port_value, {**scope, 'allowed_dependencies': []}, current)


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_quote', ['', 'invented observation'])
async def test_uncited_exclusion_stays_unresolved_in_report_and_memory(monkeypatch, invalid_quote):
    evidence = [module.Citation(evidence_id='e1.1', quote=invalid_quote)] if invalid_quote else []
    answer = decision(blocked_reason='no more permitted checks',
        alternatives=[module.Alternative(explanation='process exited', status='excluded', evidence=evidence)])
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(state())
    assert result['response'].startswith('未定位根因')
    assert '替代解释（excluded）：process exited' not in result['response']
    assert '替代解释（unresolved）：process exited' in result['response']
    alternative = result['investigation_memory']['alternatives'][0]
    assert alternative['status'] == 'unresolved'
    assert '引用' in alternative['limitation']


@pytest.mark.asyncio
async def test_unverified_causal_alternative_is_sanitized_from_user_output(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989, 'tcp': 'failed'})
    claim = '下游进程崩溃导致入口服务拒绝请求'
    answer = decision(blocked_reason='no permitted checks', alternatives=[module.Alternative(
        explanation=claim, status='excluded', claim_type='causal_explanation',
        condition=module.ObservationCondition(operation='dependency_probe', object_name='downstream',
            field='tcp', expected='ok'),
        evidence=[module.Citation(evidence_id='e1.1', quote='failed')])])
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))

    result = await module.InvestigationStrategy().decide(state(raw))

    public = json.dumps(result['diagnosis'], ensure_ascii=False) + result['response']
    assert claim not in public
    assert '该因果解释尚无可验证的现场条件' in public
    assert '该因果解释是否有独立现场证据支持？' in public
    assert '当前现场检查不能确认该因果解释' in public
    assert result['investigation_memory']['model_suggestion']['alternatives'][0]['explanation'] == claim
    assert result['investigation_memory']['alternatives'][0]['explanation'] == claim
    assert result['diagnosis']['alternatives'][0]['verification'] == 'causal_claim_unverified'


@pytest.mark.asyncio
async def test_supported_causal_claim_without_condition_or_citation_stays_unresolved(monkeypatch):
    claim = 'controlled_stop 导致 downstream 进程退出'
    answer = decision(alternatives=[module.Alternative(
        explanation=claim, status='supported', claim_type='causal_explanation')])
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))

    result = await module.InvestigationStrategy().decide(state())

    alternative = result['diagnosis']['alternatives'][0]
    assert alternative['status'] == 'unresolved'
    assert alternative['verification'] == 'unverified'
    assert alternative['evidence'] == []
    assert result['investigation_memory'].get('root_cause', '') == ''
    saved = next(candidate for candidate in
                 result['investigation_memory']['hypothesis_tracking']['candidates']
                 if candidate['source_explanation'] == claim)
    assert saved['status'] == 'active'
    assert saved['proposal']['original_status'] == 'supported'


@pytest.mark.parametrize('completed,failed', [(False, False), (True, False), (True, True)])
def test_followup_question_explains_execution_without_claiming_answer(completed, failed):
    check = '读取下游允许日志'
    answer = decision(next_check=check, next_tools=['probe_text_log'],
        discriminating_question='下游为何不可用', expected_observation='本轮退出或启动失败日志')
    current = {'past_steps': [(check, 'summary')] if completed else [], 'raw_evidence': []}
    if failed:
        current['raw_evidence'] = [(check, json.dumps({'data_source': 'tool_execution',
            'tool': 'probe_text_log', 'status': 'failed', 'reason': 'AccessDenied'}))]
    question = module.unresolved_questions(answer, current, {})[0]
    assert question['expected_observation'] == answer.expected_observation
    if failed:
        assert 'AccessDenied' in question['limitation']
        assert '尚未取得有效结果' in question['limitation']
    elif completed:
        assert '检查已执行' in question['limitation']
        assert '不代表问题已查清' in question['limitation']
    else:
        assert '尚未执行' in question['limitation']
    assert answer.next_check == check


def test_public_unresolved_questions_preserve_distinct_stable_candidate_ids():
    claims = ['根因确认是数据库崩溃', '已排除应用逻辑故障']
    answer = decision(alternatives=[module.Alternative(
        explanation=claim, hypothesis_id=f'h-{index}', status='unresolved',
        verification='causal_claim_unverified') for index, claim in enumerate(claims)])
    original = answer.model_dump()

    questions = module.unresolved_questions(answer)
    reordered = module.unresolved_questions(answer.model_copy(update={'alternatives': list(reversed(answer.alternatives))}))

    assert len({question['id'] for question in questions}) == 2
    assert {q['id'] for q in questions} == {q['id'] for q in reordered}
    assert all(claim not in str(questions) for claim in claims)
    assert answer.model_dump() == original


@pytest.mark.asyncio
async def test_unlocated_report_exposes_resource_facts_despite_bad_model_quote(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={
        'cpu_percent': 15.2, 'memory': {'percent': 71.3, 'available': 100},
        'disks': [{'mountpoint': 'C:', 'percent': 84.6, 'free': 33108013056}]})
    answer = module.InvestigationDecision(hypothesis='memory fell because a process exited',
        blocked_reason='cannot inspect all processes',
        supporting_evidence=[module.Citation(evidence_id='e1.1', quote='memory=20%')])
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(state(raw))
    report = result['response']
    assert '引用未通过原文校验：e1.1' in report
    assert 'memory=20%' not in report
    assert '现场资源原文字段' in report
    assert '"cpu_percent": 15.2' in report
    assert '"percent": 71.3' in report
    assert '33108013056' in report
    assert raw['raw_hash'] in report and raw['collected_at'] in report
    assert '模型推断（未验证，不作为现场事实）' in report


@pytest.mark.asyncio
@pytest.mark.parametrize('needs_resample', [False, True])
async def test_wait_expiry_preserves_fresh_conclusions_and_executable_resampling(monkeypatch, needs_resample):
    from datetime import datetime, timedelta, timezone
    from src.probe.protocol import evidence
    from src.settings import settings
    now = datetime.now(timezone.utc)
    current = [now]
    validate = module.validate_evidence
    monkeypatch.setattr(module, 'validate_evidence', lambda item, **kwargs: validate(item, now=current[0], **kwargs))
    old = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'orders', 'state': 'stopped'},
        collected_at=(now - timedelta(seconds=175)).isoformat())
    fresh = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'orders', 'state': 'running'},
        collected_at=now.isoformat())
    current_state = state(old)
    current_state['raw_evidence'].append(('check again', json.dumps(fresh)))
    current_state['investigation_tools'] = [{'name': 'probe_service_status'}]
    async def answer(*args, **kwargs):
        current[0] = now + timedelta(seconds=10)
        if needs_resample:
            return decision(next_check='重新核实服务当前状态', next_tools=['probe_service_status'],
                next_arguments={'probe_service_status': {'service': 'orders'}},
                repeat_reason='旧停止证据过期，复核当前运行状态', repeat_evidence_ids=['e2.1'],
                discriminating_question='旧停止状态是否仍然存在', expected_observation='新鲜状态确认停止或恢复',
                supporting_evidence=[module.Citation(evidence_id='e1.1', quote='stopped')])
        citation = module.Citation(evidence_id='e2.1', quote='running')
        return decision(outcome='healthy', supporting_evidence=[citation],
            conclusion_level='healthy_within_scope', scope='queried service',
            alternatives=[module.Alternative(explanation='services/orders: state == "stopped"', status='excluded', evidence=[citation],
                claim_type='observed_condition',
                condition=module.ObservationCondition(operation='services', object_name='orders', field='state', expected='stopped'))])
    monkeypatch.setattr(module, 'ainvoke_structured', answer)
    result = await module.InvestigationStrategy().decide(current_state)
    if needs_resample:
        assert result['plan'] == ['重新核实服务当前状态'] and 'response' not in result
        assert 'e1.1' in result['investigation_memory']['contradictions'][0]
    else:
        assert result['response'].startswith('当前检查范围内未发现故障')
        assert result['investigation_memory']['contradictions'] == []


def test_investigation_context_preserves_limits_and_gateway_clues_without_trusting_summary():
    from src.probe.protocol import evidence
    from src.settings import settings
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes',
        payload={'processes': [{'name': 'large' * 600}], 'cpu_percent_basis': '100_per_logical_core',
                 'cpu_sample_interval_seconds': 0.1}, truncated=True)
    current = state(raw)
    current['raw_evidence'].append(('baseline', json.dumps({'data_source': 'gateway_summary',
        'target_id': settings.PROBE_TARGET_ID, 'baseline_history': [{'cpu_percent': 12, 'historical': True}]})))
    records = module.evidence_index(current)
    assert len(records) == 1
    context = module.investigation_context(current, records)
    assert context['e1.1']['truncated'] is True
    assert context['e1.1']['cpu_percent_basis'] == '100_per_logical_core'
    assert context['e1.1']['target_id'] == raw['target_id']
    clues = module.gateway_clues(current)
    assert clues[0]['baseline_history'][0]['cpu_percent'] == 12


def test_old_mcp_python_repr_checkpoint_is_readable():
    current = state()
    current["raw_evidence"] = [("old check", str([{"type": "text", "text": json.dumps({
        "data_source": "diagnostic_target", "content": "actual output"})}]))]
    assert "actual output" in module.evidence_index(current)["e1.1"]["payload"]


def test_decision_memory_prompt_projection_omits_duplicate_history_without_mutating_checkpoint():
    from copy import deepcopy
    memory = {
        'model_suggestion': {'hypothesis': 'duplicate original proposal'},
        'check_progress': [{'check': 'duplicate execution status'}],
        'hypothesis_tracking': {'leading_id': 'h-1', 'candidates': [
            {'id': 'h-1', 'condition': {'operation': 'ports', 'object_name': '8080',
                'field': 'listening', 'expected': False}, 'status': 'active'}]},
        'unresolved_questions': [{'id': 'q-1', 'question': 'why is the listener absent?'}],
        'candidate_check_progress': {'h-1': [{'status': 'not_run'}]},
        'evidence_summaries': [{'evidence_id': 'e1.1', 'summary': 'listener probe failed'}],
        'identity_correction': {'attempts': 1, 'status': 'identity_rejected'},
    }
    before = deepcopy(memory)

    projection = module._decision_memory_context(memory)

    assert 'model_suggestion' not in projection
    assert 'check_progress' not in projection
    assert projection['hypothesis_tracking']['candidates'][0]['id'] == 'h-1'
    assert projection['unresolved_questions'] == memory['unresolved_questions']
    assert projection['candidate_check_progress'] == memory['candidate_check_progress']
    assert projection['evidence_summaries'] == memory['evidence_summaries']
    assert projection['identity_correction'] == memory['identity_correction']
    assert memory == before


@pytest.mark.asyncio
async def test_observation_progress_compares_payloads_and_keeps_sampling_times(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from src.probe.protocol import evidence
    from src.settings import settings
    current = state()
    current['raw_evidence'] = []
    now = datetime.now(timezone.utc)
    for index, (operation, payload) in enumerate([
        ('event_logs', {'service': 'orders', 'events': []}),
        ('event_logs', {'service': 'orders', 'events': []}),
        ('resources', {'cpu_percent': 25, 'memory': {'percent': 93}}),
        ('resources', {'cpu_percent': 30, 'memory': {'percent': 92}}),
    ]):
        raw = evidence(target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload,
                       collected_at=(now - timedelta(seconds=20-index)).isoformat())
        current['raw_evidence'].append(('check', json.dumps(raw)))
    progress = module.observation_progress(module.evidence_index(current))
    events, resources = progress
    assert events['operation'] == 'event_logs'
    assert events['payload_unchanged'] is True
    assert events['previous_evidence_id'] == 'e1.1'
    assert events['latest_evidence_id'] == 'e2.1'
    assert events['previous_collected_at'] != events['latest_collected_at']
    assert resources['payload_unchanged'] is False
    assert resources['previous_resource_values']['memory_percent'] == 93
    assert resources['latest_resource_values']['memory_percent'] == 92
    current['raw_evidence'].append(('fake', json.dumps({'data_source': 'mock', 'operation': 'resources'})))
    assert module.observation_progress(module.evidence_index(current)) == progress
    invoke = AsyncMock(return_value=decision(next_check='核对另一时点内存变化'))
    monkeypatch.setattr(module, 'ainvoke_structured', invoke)
    result = await module.InvestigationStrategy().decide(current)
    assert json.loads(invoke.call_args.args[3]['progress']) == progress
    assert result['plan'] == ['核对另一时点内存变化']


@pytest.mark.asyncio
async def test_identical_probe_observation_is_not_treated_as_new_progress(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                   payload={'dependency': 'database', 'host': '127.0.0.1', 'port': 15432,
                            'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = state()
    current['raw_evidence'] = [('第一次探测', json.dumps(raw)), ('再次探测', json.dumps(raw))]
    current['investigation_tools'] = [{'name': 'probe_dependency_probe'}]
    answer = decision(next_check='再次检查数据库连通性',
                      next_tools=['probe_dependency_probe'],
                      next_arguments={'probe_dependency_probe': {'dependency': 'database'}},
                      discriminating_question='数据库是否恢复可达',
                      expected_observation='TCP 成功才会削弱依赖不可达解释')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(current)
    assert result['plan'] == []
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert result['diagnosis']['stop_reason'].startswith('下一项检查只会重复')
    assert 'raw_hash 未变化' in result['response']
    assert result['investigation_memory']['blocked_reason'].startswith('下一项检查只会重复')


@pytest.mark.asyncio
async def test_changed_probe_observation_remains_an_executable_followup(monkeypatch):
    from src.probe.protocol import evidence
    from src.settings import settings

    first = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                     payload={'dependency': 'database', 'host': '127.0.0.1', 'port': 15432,
                              'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    second = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                      payload={'dependency': 'database', 'host': '127.0.0.1', 'port': 15432,
                               'tcp': 'ok'})
    current = state()
    current['raw_evidence'] = [('第一次探测', json.dumps(first)), ('再次探测', json.dumps(second))]
    current['investigation_tools'] = [{'name': 'probe_dependency_probe'}]
    answer = decision(next_check='再次核对数据库连通性',
                      next_tools=['probe_dependency_probe'],
                      next_arguments={'probe_dependency_probe': {'dependency': 'database'}},
                      repeat_reason='核实状态变化后是否仍可达', repeat_evidence_ids=['e2.1'],
                      discriminating_question='数据库是否仍然可达',
                      expected_observation='TCP 失败才支持依赖不可达解释持续存在')
    monkeypatch.setattr(module, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await module.InvestigationStrategy().decide(current)
    assert result['plan'] == ['再次核对数据库连通性']
    assert 'response' not in result


def test_repeated_guard_does_not_guess_between_multiple_probe_scopes():
    from src.probe.protocol import evidence
    from src.settings import settings

    first = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                     payload={'dependency': 'database', 'host': '127.0.0.1', 'port': 15432,
                              'tcp': 'failed'})
    second = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                      payload={'dependency': 'cache', 'host': '127.0.0.1', 'port': 16379,
                               'tcp': 'failed'})
    records = module.evidence_index({'raw_evidence': [
        ('database', json.dumps(first)), ('cache', json.dumps(second))]})
    decision = module.InvestigationDecision(
        hypothesis='dependency unavailable', next_check='核对配置中的另一个依赖',
        next_tools=['probe_dependency_probe'], discriminating_question='哪个依赖不可达',
        expected_observation='不同依赖返回不同状态')
    assert module._repeated_probe_check_error(decision, records) == ''


def test_repeated_guard_stops_when_all_known_scopes_return_old_hashes():
    from src.probe.protocol import evidence
    from src.settings import settings

    database = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': 'database', 'host': '127.0.0.1', 'port': 15432,
                                 'tcp': 'failed'})
    cache = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                     payload={'dependency': 'cache', 'host': '127.0.0.1', 'port': 16379,
                              'tcp': 'failed'})
    records = module.evidence_index({'raw_evidence': [
        ('database-1', json.dumps(database)), ('cache-1', json.dumps(cache)),
        ('database-2', json.dumps(database)), ('cache-2', json.dumps(cache))]})
    decision = module.InvestigationDecision(
        hypothesis='dependencies unavailable', next_check='再次核对依赖连通性',
        next_tools=['probe_dependency_probe'], discriminating_question='是否出现新状态',
        expected_observation='新的TCP状态才会改变判断')
    reason = module._repeated_probe_check_error(decision, records)
    assert 'probe_dependency_probe' in reason
    assert 'e1.1->e3.1' in reason
    assert 'e2.1->e4.1' in reason


def test_repeated_guard_keeps_investigating_after_hash_changes_back():
    from src.probe.protocol import evidence
    from src.settings import settings

    def item(status):
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                         payload={'dependency': 'database', 'host': '127.0.0.1',
                                  'port': 15432, 'tcp': status})

    records = module.evidence_index({'raw_evidence': [
        ('e1', json.dumps(item('failed'))),
        ('e2', json.dumps(item('ok'))),
        ('e3', json.dumps(item('failed'))),
        ('e4', json.dumps(item('ok'))),
    ]})
    decision = module.InvestigationDecision(
        hypothesis='dependency status changed', next_check='再次核对依赖连通性',
        next_tools=['probe_dependency_probe'], discriminating_question='当前是否仍可达',
        expected_observation='最新状态支持当前判断')
    assert module._repeated_probe_check_error(decision, records) == ''


def test_repeated_guard_stops_only_on_latest_consecutive_duplicate():
    from src.probe.protocol import evidence
    from src.settings import settings

    def item(status):
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                         payload={'dependency': 'database', 'host': '127.0.0.1',
                                  'port': 15432, 'tcp': status})

    records = module.evidence_index({'raw_evidence': [
        ('e1', json.dumps(item('failed'))),
        ('e2', json.dumps(item('ok'))),
        ('e3', json.dumps(item('failed'))),
        ('e4', json.dumps(item('failed'))),
    ]})
    decision = module.InvestigationDecision(
        hypothesis='dependency remains unavailable', next_check='再次核对依赖连通性',
        next_tools=['probe_dependency_probe'], discriminating_question='当前是否仍不可达',
        expected_observation='连续相同状态才表示没有新信息')
    reason = module._repeated_probe_check_error(decision, records)
    assert 'probe_dependency_probe' in reason
    assert 'e3.1->e4.1' in reason


def test_repeated_guard_handles_event_log_channel_lists():
    from src.probe.protocol import evidence
    from src.settings import settings

    payload = {'service': 'eventlog', 'channels': ['System'], 'events': []}
    item = evidence(target_id=settings.PROBE_TARGET_ID, operation='event_logs', payload=payload)
    records = module.evidence_index({'raw_evidence': [
        ('event-1', json.dumps(item)), ('event-2', json.dumps(item))]})
    decision = module.InvestigationDecision(
        hypothesis='no new events', next_check='再次读取事件',
        next_tools=['probe_event_log'], discriminating_question='是否有新事件',
        expected_observation='新增错误事件才会改变判断')
    reason = module._repeated_probe_check_error(decision, records)
    assert 'probe_event_log' in reason and 'raw_hash 未变化' in reason


@pytest.mark.asyncio
async def test_autonomous_probe_tools_do_not_bypass_dependency_allowlist(monkeypatch):
    from types import SimpleNamespace
    from src.agent.aiops import tools
    monkeypatch.setattr(tools.settings, "TERMCP_ENABLED", True)
    monkeypatch.setattr(tools.settings, "DIAGNOSTIC_ENABLED", False)
    monkeypatch.setattr(tools, "load_mcp_tools_safe", AsyncMock(return_value=(
        [SimpleNamespace(name="check_api_endpoint"), SimpleNamespace(name="search_log")], None)))
    monkeypatch.setattr(tools, "load_tools_for_config", AsyncMock(return_value=([], None)))
    ordinary, _ = await tools.load_agent_tools()
    autonomous, _ = await tools.load_agent_tools(True)
    assert {t.name for t in ordinary} == {"check_api_endpoint", "search_log"}
    assert {t.name for t in autonomous} == {"search_log"}
