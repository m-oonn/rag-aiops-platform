from datetime import datetime, timedelta, timezone

import pytest

from src.probe.evidence import EvidenceValidationError, validate_evidence
from src.probe.protocol import evidence


def test_evidence_target_and_hash_are_verified():
    item = evidence(target_id="windows-local-01", operation="resources", payload={"cpu_percent": 1})
    assert validate_evidence(item, target_id="windows-local-01")["operation"] == "resources"
    with pytest.raises(EvidenceValidationError):
        validate_evidence(item, target_id="other")
    item["raw_hash"] = "sha256:bad"
    with pytest.raises(EvidenceValidationError):
        validate_evidence(item, target_id="windows-local-01")


def test_expired_evidence_is_rejected():
    collected = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    item = evidence(target_id="t", operation="inventory", payload={}, collected_at=collected)
    with pytest.raises(EvidenceValidationError):
        validate_evidence(item, target_id="t", max_age_seconds=60)


def test_executor_rejects_evidence_from_another_configured_target(monkeypatch):
    import json
    from src.agent.aiops.executor import _record_probe_evidence
    from src.settings import settings
    from src.agent.aiops import run_store
    monkeypatch.setattr(settings, 'PROBE_TARGET_ID', 'expected-host')
    writes = []
    monkeypatch.setattr(run_store, 'add_evidence', lambda *args, **kwargs: writes.append(args))
    wrong = evidence(target_id='different-host', operation='inventory', payload={})
    assert _record_probe_evidence({'thread_id': 'target-test'}, json.dumps(wrong), 'inventory') == []
    assert writes == []


def test_executor_event_summary_redacts_credentials(monkeypatch):
    import json
    from src.agent.aiops.executor import _record_probe_evidence
    from src.settings import settings
    from src.agent.aiops import run_store
    monkeypatch.setattr(run_store, 'add_evidence', lambda *args, **kwargs: 'ev-test')
    item = evidence(target_id=settings.PROBE_TARGET_ID, operation='event_logs',
                    payload={'password': 'never-expose-this', 'message': 'password=also-secret'})
    events = _record_probe_evidence({'thread_id': 'summary-test'}, json.dumps(item), 'event_logs')
    assert len(events) == 1
    assert 'never-expose-this' not in events[0]['summary']
    assert 'also-secret' not in events[0]['summary']
    assert '[REDACTED]' in events[0]['summary']


@pytest.mark.asyncio
async def test_tool_operation_mismatch_never_reaches_model_as_evidence():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.agent.aiops.executor import _run_single_tool
    from src.settings import settings
    item = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={'cpu_percent': 2})
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value=item))
    result = await _run_single_tool({'name': 'probe_inventory', 'args': {}, 'id': 'p1'}, {'probe_inventory': tool})
    assert 'probe_target' not in result.content
    assert 'EvidenceValidationError' in result.content


@pytest.mark.asyncio
async def test_executor_rejects_unknown_alias_but_keeps_valid_sampling(monkeypatch):
    import importlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from langchain_core.messages import AIMessage
    from src.settings import settings
    ex = importlib.import_module('src.agent.aiops.executor')
    inventory = evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={
        'configured_services': {'eventlog': {'event_logs_available': True}}, 'configured_dependencies': []})
    sample = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={'cpu_percent': 12})
    denied = SimpleNamespace(name='probe_service_status', ainvoke=AsyncMock())
    allowed = SimpleNamespace(name='probe_resource_snapshot', ainvoke=AsyncMock(return_value=sample))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([denied, allowed], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kwargs: SimpleNamespace(bind_tools=lambda _: object()))
    calls = [
        {'id': 'deny', 'name': 'probe_service_status', 'args': {'service': 'sshd'}},
        {'id': 'sample', 'name': 'probe_resource_snapshot', 'args': {}}]
    invoke = AsyncMock(side_effect=[AIMessage(content='', tool_calls=calls), AIMessage(content='scope limited'),
                                   AIMessage(content='', tool_calls=[calls[1]]), AIMessage(content='resampled')])
    monkeypatch.setattr(ex, 'ainvoke_with_retry', invoke)
    current = {'autonomous_investigation': True, 'raw_evidence': [('inventory', json.dumps(inventory))]}
    result, raw = await ex._run_step('inspect host', current)
    denied.ainvoke.assert_not_awaited()
    assert 'service_not_configured' in raw
    assert 'tool_execution' in raw
    assert 'probe_target' in raw
    await ex._run_step('sample trend', {**current, 'raw_evidence': current['raw_evidence'] + [('sample', raw)]})
    assert allowed.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_executor_rejects_unplanned_tool_but_runs_selected_resample(monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    from src.settings import settings
    ex = importlib.import_module('src.agent.aiops.executor')
    sample = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={'cpu_percent': 12})
    denied = SimpleNamespace(name='probe_event_log', description='events', ainvoke=AsyncMock())
    allowed = SimpleNamespace(name='probe_resource_snapshot', description='resources', ainvoke=AsyncMock(return_value=sample))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([denied, allowed], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kwargs: SimpleNamespace(bind_tools=lambda _: object()))
    invoke = AsyncMock(side_effect=[AIMessage(content='', tool_calls=[
        {'id': 'deny', 'name': 'probe_event_log', 'args': {'service': 'eventlog'}},
        {'id': 'sample', 'name': 'probe_resource_snapshot', 'args': {}}]), AIMessage(content='resampled')])
    monkeypatch.setattr(ex, 'ainvoke_with_retry', invoke)
    current = {'autonomous_investigation': True,
        'investigation_tools': [{'name': 'probe_resource_snapshot'}, {'name': 'probe_event_log'}],
        'investigation_memory': {'next_check': '复核内存回落', 'next_tools': ['probe_resource_snapshot'],
            'discriminating_question': '是否为瞬时占用', 'expected_observation': '可用内存回升削弱持续耗尽解释'}}
    result, raw = await ex._run_step('复核内存回落', current)
    denied.ainvoke.assert_not_awaited()
    allowed.ainvoke.assert_awaited_once()
    assert 'outside_investigation_check' in raw
    assert 'probe_target' in raw


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['purpose', 'unloaded_tool'])
async def test_invalid_restored_check_stops_before_model_call(monkeypatch, missing):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    ex = importlib.import_module('src.agent.aiops.executor')
    tool = SimpleNamespace(name='probe_resource_snapshot', description='resources', ainvoke=AsyncMock())
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    factory = Mock()
    monkeypatch.setattr(ex, 'create_agent_llm', factory)
    memory = {'next_check': 'resample', 'next_tools': ['probe_resource_snapshot'],
              'discriminating_question': 'transient or persistent', 'expected_observation': 'memory recovers'}
    if missing == 'purpose':
        memory['discriminating_question'] = ''
    else:
        memory['next_tools'] = ['probe_event_log']
    result, raw = await ex._run_step('resample', {'autonomous_investigation': True,
        'investigation_tools': [{'name': 'probe_resource_snapshot'}, {'name': 'probe_event_log'}],
        'investigation_memory': memory})
    factory.assert_not_called()
    tool.ainvoke.assert_not_awaited()
    assert 'invalid_investigation_check' in raw
    assert 'probe_target' not in raw
    assert '停止' in result


@pytest.mark.asyncio
@pytest.mark.parametrize('selected', ['probe_resource_snapshot', 'search_log'])
async def test_forced_log_fallback_obeys_followup_scope(monkeypatch, selected):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    ex = importlib.import_module('src.agent.aiops.executor')
    tools = [SimpleNamespace(name=name, description=name) for name in ('probe_resource_snapshot', 'search_log')]
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kwargs: SimpleNamespace(bind_tools=lambda _: object()))
    monkeypatch.setattr(ex, 'ainvoke_with_retry', AsyncMock(return_value=AIMessage(content='')))
    fallback = AsyncMock(return_value='log output')
    monkeypatch.setattr(ex, '_forced_search_log', fallback)
    await ex._run_step('核对日志', {'autonomous_investigation': True,
        'investigation_tools': [{'name': tool.name} for tool in tools],
        'investigation_memory': {'next_check': '核对日志', 'next_tools': [selected],
            'discriminating_question': '是否有关联错误', 'expected_observation': '关联错误支持应用异常'}})
    assert fallback.await_count == (1 if selected == 'search_log' else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('names, expected_peak', [
    (['probe_resource_snapshot', 'probe_process_snapshot', 'probe_port_snapshot'], 1),
    (['shell_output', 'search_log'], 1),
    (['search_log', 'query_metrics'], 2),
])
async def test_tool_batch_respects_single_probe_capacity(monkeypatch, names, expected_peak):
    import asyncio
    import importlib
    from types import SimpleNamespace
    ex = importlib.import_module('src.agent.aiops.executor')
    active = peak = 0
    async def execute(tc, tool_map, real_ids):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return SimpleNamespace(tool_call_id=tc['id'])
        finally:
            active -= 1
    monkeypatch.setattr(ex, '_run_single_tool', execute)
    calls = [{'name': name, 'id': str(index)} for index, name in enumerate(names)]
    results = await ex._run_tool_calls(calls, {})
    assert peak == expected_peak
    assert [result.tool_call_id for result in results] == [tc['id'] for tc in calls]


@pytest.mark.asyncio
async def test_autonomous_investigation_does_not_parallelize_plan_steps(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock
    from src.settings import settings
    ex = importlib.import_module('src.agent.aiops.executor')
    monkeypatch.setattr(settings, 'ENABLE_PARALLEL_OBSERVATION', True)
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([], None)))
    step = AsyncMock(return_value=('sample', ''))
    monkeypatch.setattr(ex, '_run_step', step)
    plan = ['[并行] memory', '[并行] ports']
    result = await ex.executor({'autonomous_investigation': True, 'plan': plan})
    step.assert_awaited_once()
    assert result['plan'] == plan[1:]

