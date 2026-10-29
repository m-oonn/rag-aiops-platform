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
    current['raw_evidence'].append(('unsupported service', json.dumps({
        'data_source': 'tool_execution', 'tool': 'probe_service_status',
        'arguments': {'service': 'sshd'}, 'status': 'unavailable', 'reason': 'service_not_configured'})))
    await module.InvestigationStrategy().decide(current)
    inputs = invoke.call_args.args[3]
    assert 'probe_port_snapshot' in inputs['capabilities']
    assert 'service_not_configured' in inputs['checks']
    assert 'sshd' in inputs['checks']
    assert 'progress' in inputs


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
        payload={'state': 'stopped' if outcome == 'root_cause' else 'running'})
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
            alternatives=[module.Alternative(explanation='different observed state', status='excluded', evidence=[citation],
                claim_type='observed_condition',
                condition=module.ObservationCondition(operation='services', object_name='', field='state', expected='stopped'))])
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
    old = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'state': 'stopped'},
        collected_at=(now - timedelta(seconds=175)).isoformat())
    fresh = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'state': 'running'},
        collected_at=now.isoformat())
    current_state = state(old)
    current_state['raw_evidence'].append(('check again', json.dumps(fresh)))
    current_state['investigation_tools'] = [{'name': 'probe_service_status'}]
    async def answer(*args, **kwargs):
        current[0] = now + timedelta(seconds=10)
        if needs_resample:
            return decision(next_check='重新核实服务当前状态', next_tools=['probe_service_status'],
                discriminating_question='旧停止状态是否仍然存在', expected_observation='新鲜状态确认停止或恢复',
                supporting_evidence=[module.Citation(evidence_id='e1.1', quote='stopped')])
        citation = module.Citation(evidence_id='e2.1', quote='running')
        return decision(outcome='healthy', supporting_evidence=[citation],
            conclusion_level='healthy_within_scope', scope='queried service',
            alternatives=[module.Alternative(explanation='service stopped', status='excluded', evidence=[citation],
                claim_type='observed_condition',
                condition=module.ObservationCondition(operation='services', object_name='', field='state', expected='stopped'))])
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
