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
        assert {k: paused.values['investigation_memory'][k] for k in followup.model_dump() if k != 'next_question_id'} == {k: v for k, v in followup.model_dump().items() if k != 'next_question_id'}
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
        denied.ainvoke.assert_not_awaited()
        assert allowed.ainvoke.await_count == 2
        assert decide.await_count == 2
        assert all('reference-marker' in call.args[3]['references'] for call in decide.call_args_list)
        assert 'reference-marker' in invoke.call_args_list[2].args[1][0].content
        assert 'reference-marker' not in str(final['raw_evidence'])
        assert len(final['past_steps']) == 2
        assert 'outside_investigation_check' in final['raw_evidence'][1][1]
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
@pytest.mark.parametrize('invalid_output', [False, True])
async def test_probe_only_run_uses_persistent_investigation_and_survives_reopen(tmp_path, engine, monkeypatch, invalid_output):
    graph_module = importlib.import_module('src.agent.aiops.graph')
    investigation = importlib.import_module('src.agent.aiops.strategies.investigation')
    from src.agent.aiops.executor import _record_probe_evidence
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'TERMCP_ENABLED', False)
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
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
    invoke = AsyncMock(side_effect=StructuredOutputError('invalid') if invalid_output else None, return_value=decision)
    monkeypatch.setattr(investigation, 'ainvoke_structured', invoke)
    service = graph_module.AIOpsService()
    try:
        events = [e async for e in service.execute('service unavailable', user_id=17)]
        final = next(e for e in events if e['type'] == 'complete')
        assert final['response'].startswith('未定位根因' if invalid_output else '已定位故障层：配置服务当前未运行')
        assert final['diagnosis']['kind'] == ('unlocated' if invalid_output else 'localized_fault')
        if not invalid_output:
            assert final['diagnosis']['evidence'][0]['evidence_id'].startswith('ev-')
        if invalid_output:
            assert 'stopped' in final['response']
            assert '结构化' in final['response']
        tid = final['thread_id']
        assert run_store.get_run(tid).user_id == 17
        assert run_store.get_run(tid).status == 'completed'
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
        assert checkpoint.next == ()
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
