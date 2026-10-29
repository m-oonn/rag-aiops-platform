"""Fixed decisions with live, read-only Probe/MCP tools; no effectiveness claim."""
import hashlib
import importlib
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch


async def verify_mechanism_groups(tools, output, log, knowledge_tool, knowledge_url):
    import httpx
    from langchain_core.messages import AIMessage, ToolMessage
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.database.sql_session import Base
    from src.settings import settings
    from src.agent.aiops import run_store
    from src.agent.aiops.evidence_sources import knowledge_context
    from src.probe.evidence import validate_evidence
    from scripts.evaluate_windows_probe import (MECHANISM_GROUPS, configure_mechanisms,
        save_mechanism_audit, local_runbook_retrieval, business_catalog)
    from scripts.knowledge_conditions import check_knowledge_conditions
    from src.probe.windows.config import load_config
    graphs = importlib.import_module('src.agent.aiops.graph')
    planner = importlib.import_module('src.agent.aiops.planner')
    executor = importlib.import_module('src.agent.aiops.executor')
    inv = importlib.import_module('src.agent.aiops.strategies.investigation')
    summaries = []
    endpoint = knowledge_url
    for case in ('protection', 'contradiction', 'no_live_refutation'):
        for group, (protection, trigger) in MECHANISM_GROUPS.items():
            directory = output / ('mechanisms-' + case + '-' + group)
            directory.mkdir()
            check_knowledge_conditions(output / 'knowledge-manifest.json', output / 'runbooks',
                directory, endpoint, 'before')
            engine = create_engine('sqlite:///' + (directory / 'ledger.sqlite').as_posix())
            Base.metadata.create_all(engine)
            calls, decisions, planning = [], [], []
            wrapped = []
            for tool in [*tools.values(), knowledge_tool]:
                async def invoke(args, original=tool):
                    result = await original.ainvoke(args)
                    calls.append({'tool': original.name, 'args': args})
                    return result
                wrapped.append(SimpleNamespace(name=tool.name, description=tool.description,
                    args=tool.args, ainvoke=invoke))
            async def load(*args, **kwargs):
                return wrapped, None
            async def plan(llm, schema, prompt, inputs, **kwargs):
                planning.append(inputs['experience_context'])
                (directory / 'planner-context.txt').write_text(inputs['experience_context'], encoding='utf-8')
                return planner.Plan(steps=['查运维手册'])
            async def react(llm, messages, **kwargs):
                if isinstance(messages[-1], ToolMessage):
                    return AIMessage(content='固定决策检查结束')
                task = messages[1].content.rsplit('请执行以下诊断步骤: ', 1)[-1]
                if '查运维手册' in task:
                    name, args = 'search_knowledge_base', {'query': 'localapp availability', 'kb_id': 14}
                elif '核查入口' in task:
                    name, args = 'probe_dependency_probe', {'dependency': 'localapp'}
                elif '核查日志' in task:
                    name, args = 'probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 20}
                else:
                    name, args = 'probe_dependency_probe', {'dependency': 'downstream'}
                return AIMessage(content='', tool_calls=[{'id': 'fixed', 'name': name, 'args': args}])
            async def decide(llm, schema, prompt, inputs, **kwargs):
                decisions.append(json.loads(inputs['knowledge']))
                assert decisions[-1] and 'localapp-guide' not in inputs['evidence']
                if len(decisions) == 3:
                    return inv.InvestigationDecision(hypothesis='未查清', blocked_reason='固定决策结束，不评价自主归因')
                decision = inv.InvestigationDecision(hypothesis='下游 TCP 不可达',
                    hypothesis_condition=inv.ObservationCondition(operation='dependency_probe',
                        object_name='downstream', field='tcp', expected='failed'),
                    next_check='核查下游' if case == 'contradiction' else '核查日志',
                    next_tools=['probe_dependency_probe' if case == 'contradiction' else 'probe_text_log'],
                    discriminating_question='下游连接是否失败', expected_observation='TCP ok 反驳 failed 预期',
                    alternatives=[inv.Alternative(explanation='入口 TCP 不可达', status='unresolved',
                        condition=inv.ObservationCondition(operation='dependency_probe',
                            object_name='localapp', field='tcp', expected='failed'),
                        check=inv.CandidateCheck(next_check='核查入口', next_tools=['probe_dependency_probe'],
                            discriminating_question='入口是否可连接', expected_observation='TCP ok 反驳入口不可达'))]
                        if not (len(decisions) == 2 and case == 'protection') else [])
                if len(decisions) == 2:
                    decision.next_check, decision.next_tools = '再次核查下游', ['probe_dependency_probe']
                return decision
            service = None
            try:
                with ExitStack() as stack:
                    for key, value in {'PROBE_ENABLED': True, 'TERMCP_ENABLED': False, 'ENABLE_HITL': False,
                            'ENABLE_DYNAMIC_CLASSIFICATION': False, 'INVESTIGATION_PROTECTION_STEPS': 2,
                            'INVESTIGATION_HYPOTHESIS_PROTECTION': protection,
                            'INVESTIGATION_CONTRADICTION_TRIGGER': trigger,
                            'PROBE_EVIDENCE_DIR': str(directory / 'evidence'),
                            'AIOPS_CHECKPOINT_DB_PATH': str(directory / 'checkpoints.sqlite'),
                            'DIAGNOSTIC_TARGET_CATALOG': business_catalog(load_config(output / 'config.toml'))}.items():
                        stack.enter_context(patch.object(settings, key, value))
                    stack.enter_context(patch.object(run_store, 'SessionLocal', sessionmaker(bind=engine)))
                    factory = lambda **kw: SimpleNamespace(bind_tools=lambda _: object())
                    for module in (planner, executor, inv):
                        stack.enter_context(patch.object(module, 'create_agent_llm', factory))
                    retrieve = stack.enter_context(local_runbook_retrieval(output / 'runbooks', directory))
                    stack.enter_context(patch.object(planner, '_retrieve_experience', retrieve))
                    stack.enter_context(patch.object(planner, 'load_agent_tools', load))
                    stack.enter_context(patch.object(planner, 'ainvoke_structured', plan))
                    stack.enter_context(patch.object(executor, '_get_tools_for_state', load))
                    stack.enter_context(patch.object(executor, 'ainvoke_with_retry', react))
                    stack.enter_context(patch.object(inv, 'ainvoke_structured', decide))
                    transport = httpx.AsyncHTTPTransport.handle_async_request
                    async def local_only(client, request):
                        assert request.url.host in {'127.0.0.1', '::1'}, 'external HTTP forbidden'
                        return await transport(client, request)
                    stack.enter_context(patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', local_only))
                    expected = configure_mechanisms(group)
                    service = graphs.AIOpsService()
                    events = [event async for event in service.execute('检查 localapp 可用性', user_id=1, terminal_enabled=False)]
                    (directory / 'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')
                    assert not any(e['type'] == 'error' for e in events)
                    complete = next(e for e in events if e['type'] == 'complete')
                    tid = complete['thread_id']
                    audit = await save_mechanism_audit(service, tid, expected, directory)
                    assert audit['passed'], audit
                    assert audit['behavior']['status'] == 'passed', audit['behavior']
                    graph = await service._persistent_graph(service._create_run_strategy())
                    final = (await graph.aget_state({'configurable': {'thread_id': tid}})).values
                    changed = protection if case == 'protection' else trigger if case == 'contradiction' else False
                    selected = 'localapp' if changed else 'downstream'
                    planning_tools = ['probe_inventory'] + (['probe_list_evidence'] if 'probe_list_evidence' in tools else [])
                    assert [c['tool'] for c in calls[:len(planning_tools)]] == planning_tools
                    checks = calls[len(planning_tools):]
                    assert checks == [{'tool': 'search_knowledge_base', 'args': {'query': 'localapp availability', 'kb_id': 14}},
                        {'tool': 'probe_dependency_probe', 'args': {'dependency': 'downstream'}}
                        if case == 'contradiction' else {'tool': 'probe_text_log', 'args': {'service': 'localapp', 'path': str(log), 'lines': 20}},
                        {'tool': 'probe_dependency_probe', 'args': {'dependency': selected}}], checks
                    ledger = run_store.list_evidence(tid, 1)
                    records = inv.evidence_index(final)
                    assert len(ledger) == len(records) == 3
                    for item in ledger:
                        saved = run_store.get_evidence(tid, item['evidence_id'], 1, include_raw=True)
                        validate_evidence(saved['raw'], target_id=settings.PROBE_TARGET_ID)
                        if saved['raw']['operation'] == 'dependency_probe':
                            assert saved['raw']['payload']['tcp'] == 'ok', 'expected healthy TCP observation'
                        assert run_store.get_evidence(tid, item['evidence_id'], 2) is None
                    mechanism_events = final['diagnosis']['mechanisms']['events']
                    kind = 'protection_check_selected' if case == 'protection' else 'contradiction_triggered'
                    assert any(e['kind'] == kind for e in mechanism_events) is changed
                    if case == 'no_live_refutation':
                        assert not any(e['kind'] == 'contradiction_triggered' for e in mechanism_events)
                        assert not any(e['kind'] in {'contradiction_triggered', 'contradiction_blocked'}
                            and e['step'] <= 2 for e in mechanism_events)
                    for event in mechanism_events:
                        assert set(event.get('evidence_ids', [])) <= set(records)
                        if event['kind'] == 'contradiction_triggered':
                            assert event['evidence_ids']
                            assert event['condition']['object_name'] == 'downstream'
                            for eid in event['evidence_ids']:
                                observed = json.loads(records[eid]['payload'])
                                assert observed['operation'] == 'dependency_probe'
                                assert observed['payload']['dependency'] == 'downstream'
                                assert observed['payload']['tcp'] == 'ok'
                    assert [e['investigation'] for e in events if e.get('investigation')][-1]['events'] == mechanism_events
                    assert complete['diagnosis']['kind'] == 'unlocated'
                    assert knowledge_context(final['raw_evidence']) == decisions[0]
                    await service.close()
                    service = graphs.AIOpsService()
                    restored_graph = await service._persistent_graph(service._create_run_strategy())
                    restored = await restored_graph.aget_state({'configurable': {'thread_id': tid}})
                    assert restored.values['investigation_memory'] == final['investigation_memory']
                    assert restored.values['raw_evidence'] == final['raw_evidence']
                    fingerprint = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    assert len(decisions) == 3 and len({fingerprint(d) for d in decisions}) == 1
                    summaries.append({'case': case, 'group': group, 'thread_id': tid, 'calls': calls,
                        'config': expected,
                        'knowledge_sha256': fingerprint(decisions[0]),
                        'planning_knowledge_sha256': fingerprint(json.loads((directory / 'knowledge_trace.json').read_text(encoding='utf-8'))['queries'][0]['context']),
                        'evidence_ids': list(records), 'events': mechanism_events, 'audit_passed': True,
                        'behavior': audit['behavior']})
            finally:
                if service:
                    await service.close()
                engine.dispose()
                (directory / 'calls.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf-8')
            check_knowledge_conditions(output / 'knowledge-manifest.json', output / 'runbooks', directory, endpoint, 'after')
        rows = summaries[-4:]
        assert len({row['knowledge_sha256'] for row in rows}) == len({row['planning_knowledge_sha256'] for row in rows}) == 1
    assert len({eid for row in summaries for eid in row['evidence_ids']}) == 36
    (output / 'live-mechanism-groups.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'case': 'live_probe_fixed_decision_mechanism_groups', 'status': 'passed',
        'investigations': len(summaries), 'evidence_count': 36, 'model_calls': 0,
        'autonomous_model_investigation': False, 'mechanism_effectiveness_verified': False}
