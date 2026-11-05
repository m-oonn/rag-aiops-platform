import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.probe.protocol import evidence
from src.settings import settings


@pytest.mark.asyncio
async def test_followup_scope_survives_sqlite_reopen_and_preserves_unlocated_evidence(tmp_path, engine, monkeypatch):
    from langchain_core.messages import AIMessage
    graph_module = importlib.import_module('src.agent.aiops.graph')
    ex = importlib.import_module('src.agent.aiops.executor')
    inv = importlib.import_module('src.agent.aiops.strategies.investigation')
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(tmp_path / 'followup.sqlite'))
    monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    sample = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources', payload={'memory_percent': 93})
    allowed = SimpleNamespace(name='probe_resource_snapshot', description='resources', ainvoke=AsyncMock(return_value=sample))
    denied = SimpleNamespace(name='probe_event_log', description='events', ainvoke=AsyncMock())
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([allowed, denied], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kwargs: SimpleNamespace(bind_tools=lambda _: object()))
    call = {'id': 'resource', 'name': allowed.name, 'args': {}}
    invoke = AsyncMock(side_effect=[AIMessage(content='', tool_calls=[call]), AIMessage(content='high memory'),
        AIMessage(content='', tool_calls=[{'id': 'unplanned', 'name': denied.name, 'args': {}}, call]),
        AIMessage(content='still high')])
    monkeypatch.setattr(ex, 'ainvoke_with_retry', invoke)
    async def planner(state):
        return {'plan': ['initial sample'],
            'investigation_reference_context': 'reference-marker localapp downstream; not live evidence'}
    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    followup = inv.InvestigationDecision(hypothesis='persistent memory pressure',
        next_check='check memory recovery', next_tools=[allowed.name],
        next_arguments={allowed.name: {}}, repeat_reason='复核瞬时峰值是否回落', repeat_evidence_ids=['e1.1'],
        discriminating_question='transient or persistent pressure', expected_observation='memory recovery weakens persistence')
    stop = inv.InvestigationDecision(hypothesis='persistent memory pressure', blocked_reason='no permitted discriminator',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='93')],
        alternatives=[inv.Alternative(explanation='private memory leak', status='unavailable', limitation='RSS cannot prove a leak')])
    decide = AsyncMock(side_effect=[followup, stop])
    monkeypatch.setattr(inv, 'ainvoke_structured', decide)
    tid = 'followup-reopen'
    config = {'configurable': {'thread_id': tid}}
    run_store.create_run(tid, 17, 'memory symptom')
    service = graph_module.AIOpsService()
    try:
        graph = await service._persistent_graph(service._create_run_strategy())
        await graph.ainvoke({'input': 'memory symptom', 'autonomous_investigation': True,
            'thread_id': tid, 'user_id': 17, 'plan': [], 'past_steps': [], 'raw_evidence': [], 'response': ''},
            config, interrupt_after=['replanner'])
        paused = await graph.aget_state(config)
        assert paused.next == ('executor',)
        assert {k: paused.values['investigation_memory'][k] for k in followup.model_dump()
                if k not in {'next_question_id', 'hypothesis_id', 'repeat_evidence_ids'}} == {
                    k: v for k, v in followup.model_dump().items() if k not in {'next_question_id', 'hypothesis_id', 'repeat_evidence_ids'}}
        assert paused.values['investigation_memory']['repeat_evidence_ids'] == [run_store.list_evidence(tid, 17)[0]['evidence_id']]
        assigned_id = paused.values['investigation_memory']['hypothesis_id']
        assert assigned_id == paused.values['investigation_memory']['hypothesis_tracking']['leading_id']
        assert assigned_id.startswith('h-')
        assert paused.values['investigation_memory']['next_question_id'].startswith('q-')
        assert paused.values['investigation_memory']['unresolved_questions']
        assert paused.values['investigation_memory']['model_suggestion']['next_check'] == followup.next_check
        assert 'reference-marker' in paused.values['investigation_reference_context']
        assert len(run_store.list_evidence(tid, 17)) == 1
    finally:
        await service.close()
    reopened = graph_module.AIOpsService()
    try:
        graph = await reopened._persistent_graph(reopened._create_run_strategy())
        restored = await graph.aget_state(config)
        assert restored.values['investigation_memory'] == paused.values['investigation_memory']
        assert restored.values['investigation_reference_context'] == paused.values['investigation_reference_context']
        final = await graph.ainvoke(None, config)
        assert final['diagnosis']['hypothesis_id'] == assigned_id
        denied.ainvoke.assert_not_awaited()
        assert allowed.ainvoke.await_count == 2
        assert decide.await_count == 2
        assert all('reference-marker' in call.args[3]['references'] for call in decide.call_args_list)
        assert invoke.await_count == 2  # Only the legacy initial step needs executor model turns.
        assert 'reference-marker' not in str(final['raw_evidence'])
        assert len(final['past_steps']) == 2
        assert 'planned_arguments' in final['raw_evidence'][1][1]
        assert final['response'].startswith('未定位根因')
        assert settings.PROBE_TARGET_ID in final['response']
        assert sample['collected_at'] in final['response']
        assert sample['raw_hash'] in final['response']
        assert 'RSS cannot prove a leak' in final['response']
        assert len(run_store.list_evidence(tid, 17)) == 2
        assert (await graph.aget_state(config)).next == ()
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_output', [False, True, 'timeout'])
@pytest.mark.parametrize('hitl', [False, True])
async def test_probe_only_run_uses_persistent_investigation_and_survives_reopen(tmp_path, engine, monkeypatch, invalid_output, hitl):
    graph_module = importlib.import_module('src.agent.aiops.graph')
    investigation = importlib.import_module('src.agent.aiops.strategies.investigation')
    from src.agent.aiops.executor import _record_probe_evidence
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'TERMCP_ENABLED', False)
    monkeypatch.setattr(settings, 'ENABLE_HITL', hitl)
    monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(tmp_path / 'checkpoints.sqlite'))
    monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
                   payload={'state': 'stopped', 'process': 'absent'})
    async def planner(state):
        assert state['autonomous_investigation'] is True
        assert state['terminal_enabled'] is False
        return {'plan': ['check service']}
    async def executor(state):
        text = json.dumps(raw)
        return {'plan': [], 'past_steps': [('check service', 'stopped')],
                'raw_evidence': [('check service', text)],
                'evidence_events': _record_probe_evidence(state, text, 'services')}
    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    monkeypatch.setattr(investigation, 'create_agent_llm', lambda **kwargs: object())
    decision = investigation.InvestigationDecision(hypothesis='service down', root_cause='service stopped',
        conclusion_level='localized_fault', scope='queried service', localized_fault='service stopped',
        supporting_evidence=[investigation.Citation(evidence_id='e1.1', quote='stopped')],
        alternatives=[investigation.Alternative(explanation='process still serving', status='excluded',
            evidence=[investigation.Citation(evidence_id='e1.1', quote='absent')])])
    from src.agent.aiops.structured import StructuredOutputError
    import httpx
    failure = httpx.ReadTimeout('private-provider-detail') if invalid_output == 'timeout' else StructuredOutputError('invalid')
    invoke = AsyncMock(side_effect=failure if invalid_output else None, return_value=decision)
    monkeypatch.setattr(investigation, 'ainvoke_structured', invoke)
    service = graph_module.AIOpsService()
    try:
        events = [e async for e in service.execute('service unavailable', user_id=17)]
        if hitl and not invalid_output:
            pending = next(e for e in events if e['type'] == 'pending_review')
            events.extend([e async for e in service.resume(pending['thread_id'], {'action': 'approve'})])
        final = next(e for e in events if e['type'] == ('error' if invalid_output else 'complete'))
        if invalid_output:
            assert not any(e['type'] in {'complete', 'pending_review', 'draft'} for e in events)
            assert final['stage'] == 'investigation_failed'
            assert final['investigation_failure']['code'] == ('model_request_failed' if invalid_output == 'timeout' else 'invalid_model_decision')
            assert 'private-provider-detail' not in json.dumps(events)
        assert final['response'].startswith('未定位根因' if invalid_output else '已定位故障层：配置服务当前未运行')
        assert final['diagnosis']['kind'] == ('unlocated' if invalid_output else 'localized_fault')
        if not invalid_output:
            assert final['diagnosis']['evidence'][0]['evidence_id'].startswith('ev-')
        if invalid_output:
            assert 'stopped' in final['response']
            assert ('ReadTimeout' if invalid_output == 'timeout' else '结构化') in final['response']
        tid = final['thread_id']
        assert run_store.get_run(tid).user_id == 17
        assert run_store.get_run(tid).status == ('failed' if invalid_output else 'completed')
        assert run_store.get_run(tid).report == final['response']
        assert len(run_store.list_evidence(tid, 17)) == 1
        assert len([e for e in events if e['type'] == 'evidence']) == 1
        assert invoke.await_count == 1
    finally:
        await service.close()
    reopened = graph_module.AIOpsService()
    try:
        graph = await reopened._persistent_graph(reopened._create_run_strategy())
        checkpoint = await graph.aget_state({'configurable': {'thread_id': tid}})
        assert checkpoint.values['autonomous_investigation'] is True
        assert checkpoint.values['response'] == final['response']
        assert await reopened.run_diagnosis(tid) == final['diagnosis']
        details = await reopened.run_details(tid)
        assert details.get('investigation_failure') == final.get('investigation_failure')
        assert details['investigation'] == final.get('investigation')
        if not invalid_output:
            replanned = next(e for e in events if e.get('investigation'))
            assert replanned['investigation'] == final['investigation']
            assert details['investigation']['candidates']
        assert checkpoint.next == ()
        from scripts.evaluate_windows_probe import save_mechanism_audit
        audit = await save_mechanism_audit(reopened, tid, checkpoint.values['investigation_config'], tmp_path)
        assert audit['passed'] is (not invalid_output), audit
        saved_trace = json.loads((tmp_path / 'mechanism_trace.json').read_text(encoding='utf-8'))
        assert len(saved_trace['decisions']) == (0 if invalid_output else 1)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_planner_persists_initial_inventory_without_enabling_terminal(monkeypatch):
    planner = importlib.import_module('src.agent.aiops.planner')
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={'hostname': 'test'})
    tool = SimpleNamespace(name='probe_inventory', args={}, description='inventory',
                           ainvoke=AsyncMock(return_value=[{'type': 'text', 'text': json.dumps(raw)}]))
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'TERMCP_ENABLED', True)
    monkeypatch.setattr(planner, '_retrieve_experience', lambda _: 'handbook-marker password=hidden-guidance')
    monkeypatch.setattr(settings, 'DIAGNOSTIC_TARGET_CATALOG', 'localapp downstream token=hidden-config')
    monkeypatch.setattr(planner, 'load_agent_tools', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(planner, 'create_agent_llm', MagicMock())
    monkeypatch.setattr(planner, 'ainvoke_structured', AsyncMock(return_value=planner.Plan(steps=['check service'])))
    writes = MagicMock(return_value=[{'evidence_id': 'ev-test'}])
    monkeypatch.setattr(planner, '_record_probe_evidence', writes)
    result = await planner.planner({'input': 'symptom', 'thread_id': 'probe-plan', 'terminal_enabled': False})
    assert result['terminal_enabled'] is False
    assert result['autonomous_investigation'] is True
    assert result['evidence_events'] == [{'evidence_id': 'ev-test'}]
    assert json.loads(result['raw_evidence'][0][1]) == raw
    writes.assert_called_once()
    references = result['investigation_reference_context']
    assert 'localapp downstream' in references and 'handbook-marker' in references
    assert 'hidden-guidance' not in references and 'hidden-config' not in references
    assert 'handbook-marker' not in str(result['raw_evidence'])


@pytest.mark.asyncio
@pytest.mark.parametrize(('symptom', 'expected_status'), [
    ('edge 的 /api/availability 业务请求失败', 'resolved'),
    ('unregistered-service 的业务请求失败', 'unmatched'),
])
async def test_planner_uses_registered_business_entry_before_model(monkeypatch, tmp_path, symptom, expected_status):
    from scripts.evaluate_windows_probe import business_catalog
    from src.probe.windows.config import ProbeConfig, ServiceConfig, DependencyConfig

    planner_module = importlib.import_module('src.agent.aiops.planner')
    target = settings.PROBE_TARGET_ID
    cfg = ProbeConfig(target, 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'token',
        services={name: ServiceConfig(name, text_logs=(f'C:/logs/{name}.log',))
            for name in ('edge', 'localapp', 'downstream')},
        dependencies={name: DependencyConfig('127.0.0.1', 18080 + index, 'http', '/api/availability')
            for index, name in enumerate(('edge', 'localapp', 'downstream'))})
    inventory = evidence(target_id=target, operation='inventory', payload={
        'configured_services': {name: {'text_logs_available': True}
            for name in ('edge', 'localapp', 'downstream')},
        'configured_dependencies': ['edge', 'localapp', 'downstream']})
    tool = SimpleNamespace(name='probe_inventory', args={}, description='inventory',
        ainvoke=AsyncMock(return_value=[{'type': 'text', 'text': json.dumps(inventory)}]))
    invoke = AsyncMock(return_value=planner_module.Plan(steps=['inspect edge']))
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'DIAGNOSTIC_TARGET_CATALOG', business_catalog(cfg))
    monkeypatch.setattr(settings, 'SERVICE_ALIASES', '{}')
    monkeypatch.setattr(planner_module, 'load_agent_tools', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(planner_module, 'create_agent_llm', MagicMock())
    monkeypatch.setattr(planner_module, 'ainvoke_structured', invoke)

    result = await planner_module.planner({'input': symptom})

    assert result['target_resolution']['status'] == expected_status
    if expected_status == 'resolved':
        assert result['target_resolution']['service'] == 'edge'
        assert invoke.await_count == 1
    else:
        assert result['diagnosis']['kind'] == 'unlocated'
        assert invoke.await_count == 0


@pytest.mark.asyncio
async def test_executor_receives_reference_context_without_turning_it_into_evidence(monkeypatch):
    from langchain_core.messages import AIMessage
    executor = importlib.import_module('src.agent.aiops.executor')
    monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=([], None)))
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kwargs: object())
    invoke = AsyncMock(return_value=AIMessage(content='no live observation'))
    monkeypatch.setattr(executor, 'ainvoke_with_retry', invoke)
    result, raw = await executor._run_step('check configured dependency', {
        'investigation_reference_context': 'localapp downstream password=hidden-reference',
        'raw_evidence': [('late knowledge', json.dumps({'data_source': 'knowledge_base',
            'results': [{'source': 'localapp.md', 'chunk_id': 'kb-late',
                'content': 'later-lookup-guidance password=hidden-late'}]}))]})
    messages = invoke.call_args.args[1]
    assert 'localapp downstream' in messages[0].content
    assert 'hidden-reference' not in messages[0].content
    assert 'later-lookup-guidance' in messages[0].content and 'kb-late' in messages[0].content
    assert 'hidden-late' not in messages[0].content
    assert raw == '' and result == 'no live observation'


@pytest.mark.asyncio
async def test_followup_executor_only_advertises_selected_tools_and_evidence_reader(monkeypatch):
    from langchain_core.messages import AIMessage
    executor = importlib.import_module('src.agent.aiops.executor')
    tools = [SimpleNamespace(name=name, description=name, args={}) for name in
             ('probe_port_snapshot', 'probe_process_snapshot', 'read_run_evidence')]
    monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
    llm = MagicMock()
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kwargs: llm)
    invoke = AsyncMock(return_value=AIMessage(content='done'))
    monkeypatch.setattr(executor, 'ainvoke_with_retry', invoke)
    state = {'autonomous_investigation': True, 'investigation_tools': [],
        'investigation_memory': {'next_check': 'check listener', 'next_tools': ['probe_port_snapshot'],
            'discriminating_question': 'is entry listening?', 'expected_observation': 'listener or absence'}}
    await executor._run_step('check listener', state)
    assert [t.name for t in llm.bind_tools.call_args.args[0]] == ['probe_port_snapshot', 'read_run_evidence']
    assert executor._probe_request_limit({'name': 'probe_process_snapshot'}, state)


def test_policy_selected_listener_check_rejects_model_changed_arguments():
    from src.agent.aiops.executor import _probe_request_limit
    state = {'autonomous_investigation': True,
        'investigation_memory': {'next_tools': ['probe_port_snapshot'],
            'policy_selected_check': {'arguments': {'local_port': 6989, 'listening_only': True}}}}
    assert _probe_request_limit({'name': 'probe_port_snapshot', 'args': {'local_port': 6990,
        'listening_only': True}}, state) == 'policy_selected_check_arguments_mismatch'
    assert not _probe_request_limit({'name': 'probe_port_snapshot', 'args': {'local_port': 6989,
        'listening_only': True}}, state)


def test_planner_rewrites_unavailable_config_file_read_to_allowed_log_check():
    from src.agent.aiops import planner as planner_module

    tools = [SimpleNamespace(name='probe_text_log')]
    result = planner_module._sanitize_plan_steps(
        ['打开配置文件，找到入口服务的重试参数', '检查入口日志'], tools)

    assert '应用日志' in result[0]
    assert result[1] == '检查入口日志'
    assert all('配置文件' not in step for step in result)


def test_planner_keeps_config_log_check_but_does_not_invent_file_read():
    from src.agent.aiops import planner as planner_module

    tools = [SimpleNamespace(name='probe_text_log')]
    result = planner_module._sanitize_plan_steps(
        ['检查入口日志中的配置解析错误'], tools)

    assert result == ['检查入口日志中的配置解析错误']


@pytest.mark.parametrize('step_text', [
    '打开配置文件，找到localapp这一项，看入口写的是什么',
    '读取 localapp 的配置文件内容',
    'Open the configuration file for localapp',
])
def test_unavailable_file_plan_does_not_invent_tools_when_no_logs(step_text):
    from src.agent.aiops.planner import _sanitize_plan_steps
    assert _sanitize_plan_steps([step_text, '核对入口进程'],
        [SimpleNamespace(name='probe_process_snapshot')]) == ['核对入口进程']


def test_existing_approved_terminal_path_is_not_disabled_by_file_plan_check():
    from src.agent.aiops.tools import config_file_read_unavailable
    assert not config_file_read_unavailable('读取配置文件',
        [SimpleNamespace(name=name) for name in ('shell_input', 'shell_key')])


@pytest.mark.asyncio
async def test_unsupported_file_step_cannot_be_executed_or_claimed_as_probe_evidence(monkeypatch):
    from src.agent.aiops import executor as executor_module
    tools = [SimpleNamespace(name='probe_text_log', ainvoke=AsyncMock())]
    monkeypatch.setattr(executor_module, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
    create = MagicMock(side_effect=AssertionError('unavailable step must not send a model request'))
    monkeypatch.setattr(executor_module, 'create_agent_llm', create)
    result, raw = await executor_module._run_step('读取 localapp 的配置文件', {})
    assert '尚未核实' in result
    assert json.loads(raw)['reason'] == 'unsupported_config_file_read'
    assert not executor_module._record_probe_evidence({'thread_id': 'no-observation'}, raw, 'file')
    create.assert_not_called()
    tools[0].ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_planner_replaces_real_failed_plan_and_retains_capability_limit(monkeypatch):
    from src.agent.aiops import planner as planner_module
    tools = [SimpleNamespace(name='probe_text_log', description='allowed logs', args={})]
    monkeypatch.setattr(settings, 'PROBE_ENABLED', False)
    monkeypatch.setattr(planner_module, '_retrieve_experience', lambda _: '')
    monkeypatch.setattr(planner_module, 'load_agent_tools', AsyncMock(return_value=(tools, None)))
    monkeypatch.setattr(planner_module, 'create_agent_llm', MagicMock())
    proposal = AsyncMock(return_value=planner_module.Plan(steps=[
        '打开配置文件，找到localapp这一项，看入口写的是什么', '核对入口进程']))
    monkeypatch.setattr(planner_module, 'ainvoke_structured', proposal)
    result = await planner_module.planner({'input': '入口503'})
    assert result['plan'][1] == '核对入口进程'
    assert '应用日志' in result['plan'][0]
    assert '原配置文件内容仍未核实' in result['investigation_reference_context']
    assert not result['raw_evidence']


@pytest.mark.asyncio
async def test_failed_loopback_dependency_listener_check_runs_and_pid_stays_observation(monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool
    executor = importlib.import_module('src.agent.aiops.executor')
    investigation = importlib.import_module('src.agent.aiops.strategies.investigation')

    dependency = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 6989,
        'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    async def port_snapshot(local_port: int, listening_only: bool = False):
        assert local_port == 6989 and listening_only is True
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
            'local_port': local_port, 'listening_only': listening_only, 'matched_count': 1,
            'ports': [{'local': {'host': '127.0.0.1', 'port': local_port},
                'remote': None, 'status': 'LISTEN', 'pid': 43210, 'process': 'test-worker'}]})
    schema_tool = StructuredTool.from_function(coroutine=port_snapshot, name='probe_port_snapshot',
                                               description='Read-only filtered listener snapshot')
    async def invoke_port_snapshot(args):
        return await port_snapshot(**args)
    tool = SimpleNamespace(name=schema_tool.name, description=schema_tool.description,
        args=schema_tool.args, ainvoke=AsyncMock(side_effect=invoke_port_snapshot))
    monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kwargs:
                        SimpleNamespace(bind_tools=lambda tools: object()))
    tool_call = {'id': 'ports-1', 'name': 'probe_port_snapshot',
        'args': {'local_port': 6989, 'listening_only': True}}
    monkeypatch.setattr(executor, 'ainvoke_with_retry', AsyncMock(side_effect=[
        AIMessage(content='', tool_calls=[tool_call]), AIMessage(content='监听进程 PID 为 43210。')]))

    initial = {'input': '入口返回503，下游连接失败', 'target_resolution': {
        'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'service': 'localapp', 'allowed_dependencies': ['downstream'],
        'allowed_services': ['localapp'], 'services': {'localapp': {'expected_ports': []}}},
        'investigation_config': {'hypothesis_protection': False, 'contradiction_trigger': False},
        'investigation_tools': [{'name': 'probe_port_snapshot', 'parameters': {
            'local_port': 'integer', 'listening_only': 'boolean'}}],
        'autonomous_investigation': True, 'plan': [], 'past_steps': [('探测下游', 'TCP failed')],
        'raw_evidence': [('探测下游', json.dumps(dependency))]}
    scheduled = investigation.decide_from_evidence(initial,
        investigation.InvestigationDecision(hypothesis='downstream is unavailable',
            blocked_reason='no more checks'), investigation.evidence_index(initial))
    assert scheduled['plan'] and scheduled['investigation_memory']['policy_selected_check']
    step_state = {**initial, **scheduled, 'plan': scheduled['plan']}

    executed = await executor.executor(step_state)
    tool.ainvoke.assert_awaited_once_with({'local_port': 6989, 'listening_only': True})
    assert executed['evidence_events'] == []  # no run/thread storage in this isolated test
    next_state = {**step_state, **executed,
        'raw_evidence': [*step_state['raw_evidence'], *executed['raw_evidence']],
        'past_steps': [*step_state['past_steps'], *executed['past_steps']]}
    records = investigation.evidence_index(next_state)
    port_id = next(key for key, value in records.items()
                   if json.loads(value['payload']).get('operation') == 'ports')
    port_payload = json.loads(records[port_id]['payload'])['payload']
    assert port_payload['ports'][0]['pid'] == 43210

    claimed_cause = investigation.InvestigationDecision(hypothesis='downstream is unavailable',
        outcome='root_cause', conclusion_level='confirmed_cause', root_cause='PID 43210 crashed',
        scope='downstream', supporting_evidence=[investigation.Citation(evidence_id=port_id, quote='43210')])
    report = investigation.decide_from_evidence(next_state, claimed_cause, records)
    assert report['diagnosis']['kind'] == 'localized_fault', report['response']
    assert '43210' in report['response']
    assert '更深原因尚未确认' in report['response']
    assert 'PID 43210 crashed' not in report['response']
