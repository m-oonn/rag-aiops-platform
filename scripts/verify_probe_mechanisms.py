"""Fixed decisions with live, read-only Probe/MCP tools; no effectiveness claim."""
import hashlib
import importlib
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch


def _configuration_fault_observed(saved_raw):
    """True when an error log names a field that the current snapshot contradicts.

    Mirrors the engine's own configuration cross-check so the harness follows the
    evidence actually collected instead of assuming one specific probe.
    """
    snapshots = {}
    for raw in saved_raw:
        body = raw.get('payload') or {}
        if raw.get('operation') != 'configuration' or body.get('error'):
            continue
        values = body.get('values')
        if isinstance(body.get('service'), str) and isinstance(values, dict):
            snapshots[(body['service'], body.get('source_sha256'))] = values
    for raw in saved_raw:
        body = raw.get('payload') or {}
        if raw.get('operation') != 'text_logs':
            continue
        for line in body.get('lines') or []:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            logged = event.get('configuration')
            if not isinstance(logged, dict) or not event.get('error_type'):
                continue
            if not isinstance(event.get('status'), int) or event['status'] < 400:
                continue
            values = snapshots.get((body.get('service'), logged.get('source_sha256')))
            if values is not None and values.get(logged.get('field')) == logged.get('value'):
                return True
    return False


async def verify_mechanism_groups(tools, output, log, knowledge_tool, knowledge_url, set_case=None):
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
        if set_case:
            await set_case('application_config_error' if case in {'protection', 'contradiction'} else 'normal')
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
                    initial = [{'id': 'knowledge', 'name': 'search_knowledge_base',
                        'args': {'query': 'localapp availability', 'kb_id': 14}}]
                    if case != 'no_live_refutation' and 'probe_config_snapshot' in tools:
                        initial.append({'id': 'configuration', 'name': 'probe_config_snapshot',
                            'args': {'service': 'localapp'}})
                    return AIMessage(content='', tool_calls=initial)
                elif '核查入口' in task:
                    name, args = 'probe_dependency_probe', {'dependency': 'localapp'}
                elif '核查日志' in task or '读取入口日志' in task:
                    name, args = 'probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 20}
                else:
                    name, args = 'probe_dependency_probe', {'dependency': 'downstream'}
                return AIMessage(content='', tool_calls=[{'id': 'fixed', 'name': name, 'args': args}])
            async def decide(llm, schema, prompt, inputs, **kwargs):
                decisions.append(json.loads(inputs['knowledge']))
                assert decisions[-1] and 'localapp-guide' not in inputs['evidence']
                # The scripted stop is sticky: a mechanism may pre-empt it once to
                # run a check it still has, and the same stop is then repeated.
                if len(decisions) >= 3:
                    return inv.InvestigationDecision(hypothesis='未查清', blocked_reason='固定决策结束，不评价自主归因')
                expected_downstream = 'ok' if case == 'no_live_refutation' else 'failed'
                hypothesis = f'dependency_probe/downstream: tcp == "{expected_downstream}"'
                decision = inv.InvestigationDecision(hypothesis=hypothesis,
                    hypothesis_condition=inv.ObservationCondition(operation='dependency_probe',
                        object_name='downstream', field='tcp', expected=expected_downstream),
                    next_check='核查下游' if case == 'contradiction' else '核查日志',
                    next_tools=['probe_dependency_probe' if case == 'contradiction' else 'probe_text_log'],
                    next_arguments=({'probe_dependency_probe': {'dependency': 'downstream'}} if case == 'contradiction'
                                    else {'probe_text_log': {'service': 'localapp', 'path': str(log), 'lines': 20}}),
                    discriminating_question='下游连接是否失败', expected_observation='TCP ok 反驳 failed 预期',
                    alternatives=[inv.Alternative(explanation='dependency_probe/localapp: http.status == 503', status='unresolved',
                        condition=inv.ObservationCondition(operation='dependency_probe',
                            object_name='localapp', field='http.status', expected=503),
                        check=inv.CandidateCheck(next_check='核查入口', next_tools=['probe_dependency_probe'],
                            next_arguments={'probe_dependency_probe': {'dependency': 'localapp'}},
                            discriminating_question='入口是否返回预期故障状态', expected_observation='HTTP 503 支持入口配置错误场景'))]
                        if case != 'no_live_refutation' and not (len(decisions) == 2 and case == 'protection') else [])
                if len(decisions) == 2:
                    if case == 'contradiction':
                        decision.next_check, decision.next_tools = '读取入口日志', ['probe_text_log']
                        decision.next_arguments = {'probe_text_log': {'service': 'localapp', 'path': str(log), 'lines': 20}}
                    else:
                        decision.next_check, decision.next_tools = '复核下游状态', ['probe_dependency_probe']
                        decision.next_arguments = {'probe_dependency_probe': {'dependency': 'downstream'}}
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
                    selected_tool = ('probe_dependency_probe'
                        if changed or case in {'protection', 'no_live_refutation'} else 'probe_text_log')
                    selected_args = ({'dependency': 'localapp'} if changed else
                                     {'dependency': 'downstream'} if case in {'protection', 'no_live_refutation'} else
                                     {'service': 'localapp', 'path': str(log), 'lines': 20})
                    planning_tools = ['probe_inventory'] + (['probe_list_evidence'] if 'probe_list_evidence' in tools else [])
                    assert [c['tool'] for c in calls[:len(planning_tools)]] == planning_tools
                    checks = calls[len(planning_tools):]
                    expected_checks = [{'tool': 'search_knowledge_base', 'args': {'query': 'localapp availability', 'kb_id': 14}}]
                    if case != 'no_live_refutation' and 'probe_config_snapshot' in tools:
                        expected_checks.append({'tool': 'probe_config_snapshot', 'args': {'service': 'localapp'}})
                    expected_checks.extend([
                        {'tool': 'probe_dependency_probe', 'args': {'dependency': 'downstream'}}
                        if case == 'contradiction' else {'tool': 'probe_text_log', 'args': {'service': 'localapp', 'path': str(log), 'lines': 20}},
                        {'tool': selected_tool, 'args': selected_args}])
                    # After the mechanism-selected check the engine may still spend
                    # one bounded round per in-scope object that has no live
                    # observation yet.  With the three-service topology that is more
                    # than one object, so the count follows the scope instead of a
                    # fixed limit; only allow-listed read-only probes are permitted
                    # and no object may be probed twice.
                    assert checks[:len(expected_checks)] == expected_checks, checks
                    extra = checks[len(expected_checks):]
                    assert all(item['tool'] in {'probe_dependency_probe', 'probe_process_snapshot'}
                        for item in extra), checks
                    extra_keys = [(item['tool'], json.dumps(item['args'], sort_keys=True)) for item in extra]
                    assert len(set(extra_keys)) == len(extra_keys), checks
                    ledger = run_store.list_evidence(tid, 1)
                    records = inv.evidence_index(final)
                    planned_evidence = (4 if case != 'no_live_refutation' and 'probe_config_snapshot' in tools else 3)
                    assert len(ledger) == len(records) == planned_evidence + len(extra)
                    for item in ledger:
                        saved = run_store.get_evidence(tid, item['evidence_id'], 1, include_raw=True)
                        validate_evidence(saved['raw'], target_id=settings.PROBE_TARGET_ID)
                        if saved['raw']['operation'] == 'dependency_probe':
                            payload = saved['raw']['payload']
                            assert payload['tcp'] == 'ok', 'expected healthy TCP observation'
                            if case in {'protection', 'contradiction'} and payload.get('dependency') == 'localapp':
                                assert payload.get('http', {}).get('status') == 503, 'expected live entry HTTP 503'
                            if case in {'protection', 'contradiction'} and payload.get('dependency') == 'downstream':
                                assert payload.get('http', {}).get('status') == 200, 'expected healthy downstream'
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
                            # With three services the engine may refute a saved
                            # prediction about any in-scope dependency or process,
                            # not only the downstream one.  Each refutation must
                            # still be carried by evidence of exactly the predicted
                            # operation and object that contradicts the prediction.
                            condition = event['condition']
                            for eid in event['evidence_ids']:
                                observed = json.loads(records[eid]['payload'])
                                assert observed['operation'] == condition['operation']
                                if condition['operation'] == 'dependency_probe':
                                    assert observed['payload']['dependency'] == condition['object_name']
                                    assert observed['payload']['tcp'] == 'ok'
                                else:
                                    assert condition['operation'] == 'processes'
                                    assert observed['payload']['service'] == condition['object_name']
                                    assert observed['payload']['processes']
                    assert [e['investigation'] for e in events if e.get('investigation')][-1]['events'] == mechanism_events
                    # Mechanism activation and baseline diagnosis are separate.
                    # A localized fault needs a live fault observation, and in the
                    # config-error scenario there are two independent sources: the
                    # entry dependency probe returning HTTP 503, and a configuration
                    # snapshot cross-checked against the application's own error
                    # log.  Either one suffices, so the expectation follows the
                    # observations actually collected rather than the group.
                    saved_raw = [run_store.get_evidence(tid, item['evidence_id'], 1, include_raw=True)['raw']
                                 for item in ledger]
                    entry_fault = any(
                        raw['operation'] == 'dependency_probe'
                        and raw['payload'].get('dependency') == 'localapp'
                        and (raw['payload'].get('http') or {}).get('status') == 503
                        for raw in saved_raw)
                    configuration_fault = _configuration_fault_observed(saved_raw)
                    expected_kind = ('localized_fault' if entry_fault or configuration_fault
                                     else 'unlocated')
                    assert complete['diagnosis']['kind'] == expected_kind, (case, group, entry_fault)
                    assert knowledge_context(final['raw_evidence']) == decisions[0]
                    await service.close()
                    service = graphs.AIOpsService()
                    restored_graph = await service._persistent_graph(service._create_run_strategy())
                    restored = await restored_graph.aget_state({'configurable': {'thread_id': tid}})
                    assert restored.values['investigation_memory'] == final['investigation_memory']
                    assert restored.values['raw_evidence'] == final['raw_evidence']
                    fingerprint = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    # The scripted stop can be pre-empted while a mechanism still
                    # has a check to run, and once more per in-scope object that has
                    # no live observation yet.  With the three-service topology that
                    # is more than one object, so the bound follows the resolved
                    # scope instead of a fixed limit.  Every round must still see
                    # the identical knowledge context.
                    resolution = final.get('target_resolution') or {}
                    in_scope = (len(resolution.get('allowed_dependencies') or [])
                        + len(resolution.get('allowed_services') or []))
                    fingerprints = [fingerprint(d) for d in decisions]
                    assert 3 <= len(decisions) <= 3 + in_scope and len(set(fingerprints)) == 1, (case, group, fingerprints)
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
    if set_case:
        await set_case('normal')
    # Evidence is stored per thread, so the union across groups must have no
    # duplicate ids; the exact total depends on which checks each group ran, so it
    # is derived rather than hard-coded.
    counts = [len(row['evidence_ids']) for row in summaries]
    union = {eid for row in summaries for eid in row['evidence_ids']}
    assert len(union) == sum(counts) and all(count >= 3 for count in counts), counts
    (output / 'live-mechanism-groups.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'case': 'live_probe_fixed_decision_mechanism_groups', 'status': 'passed',
        'investigations': len(summaries), 'evidence_count': len(union), 'model_calls': 0,
        'autonomous_model_investigation': False, 'mechanism_effectiveness_verified': False}
