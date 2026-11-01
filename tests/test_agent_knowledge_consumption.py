"""真实 PDF/SQL 检索到正式调查图；模型决策固定，不调用在线服务。"""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import sessionmaker

from src.database.models import KnowledgeBase, KnowledgeDocument
from src.settings import settings

planner = importlib.import_module('src.agent.aiops.planner')


@pytest.fixture
def runbooks(db, engine, monkeypatch):
    import src.database.sql_session as sql
    import src.worker.tasks as worker
    import src.retrieval.hybrid_retriever as hybrid
    import src.retrieval.reranker as rerank
    import mcp_servers.rag_server as rag
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sql, 'SessionLocal', factory)
    monkeypatch.setattr(worker, 'SessionLocal', factory)
    forbidden = Mock(side_effect=AssertionError('online/vector path forbidden'))
    for module, name in [(worker, 'get_embedding_service'), (worker, 'MilvusClient'),
                         (hybrid, 'HybridRetriever'), (rerank, 'DashScopeReranker'),
                         (rag, '_get_retriever'), (rag, '_get_reranker')]:
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setenv('ENABLE_EXPERIENCE_CONTEXT', 'true')
    monkeypatch.setattr(settings, 'EXPERIENCE_KB_IDS', '901')
    db.add(KnowledgeBase(id=901, kb_uid='agent-local', owner_id=1, name='Runbooks',
        chunking_config={'retrieval_mode': 'bm25', 'chunk_size': 1000, 'chunk_overlap': 100}))
    db.add(KnowledgeBase(id=902, kb_uid='other-local', owner_id=1, name='Other',
        chunking_config={'retrieval_mode': 'bm25'}))
    db.commit()
    sources = Path(__file__).resolve().parents[1] / 'docs/fixtures/ops-runbooks'
    for index, pdf in enumerate(sorted(sources.glob('*.pdf')), 910):
        db.add(KnowledgeDocument(id=index, doc_uid=f'agent-{index}', kb_id=901,
            filename=pdf.name, file_path=str(pdf), file_type='pdf', status=0,
            source_url='https://www.rfc-editor.org/rfc/rfc9110.html'))
        db.commit()
        assert worker.process_document(index) == 'Success (BM25 only)'
    assert index == 912
    return forbidden


def test_planning_uses_real_pdf_and_preserves_source(runbooks):
    payload = json.loads(planner._retrieve_experience('应用内部异常'))
    row = payload['results'][0]
    assert payload['data_source'] == 'knowledge_base'
    assert row['source'] == '02-application-errors.pdf' and row['page'] == 2
    assert row['kb_id'] == 901 and row['doc_id'] == 911
    assert row['chunk_id'] and '应用内部异常' in row['content']
    assert row['source_url'].startswith('https://')
    runbooks.assert_not_called()


def test_local_mode_ignores_global_online_rerank_switch(runbooks, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_RERANK', True)
    assert json.loads(planner._retrieve_experience('应用内部异常'))['results']
    runbooks.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_search_reads_actual_pdf_and_rejects_other_library_without_online_path(runbooks):
    from langchain_core.tools import StructuredTool
    from src.agent.aiops.tools import scope_knowledge_tools
    import mcp_servers.rag_server as rag

    def search(query: str, kb_id: int):
        """Search actual in-memory SQL and local PDF chunks."""
        return rag.search_knowledge_base.fn(query, kb_id)

    tool = scope_knowledge_tools([
        StructuredTool.from_function(search, name='search_knowledge_base')], [901])[0]
    for kb_id in (0, 1, 902):
        with pytest.raises(PermissionError):
            await tool.ainvoke({'query': '应用内部异常', 'kb_id': kb_id})
    result = await tool.ainvoke({'query': '应用内部异常'})
    assert result['kb_id'] == 901 and result['results']
    assert result['results'][0]['source'] == '02-application-errors.pdf'
    assert result['results'][0]['page'] == 2
    runbooks.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_consumes_real_pdf_with_explicit_library(runbooks, monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from langchain_core.tools import StructuredTool
    from src.probe.protocol import evidence
    from scripts import evaluate_windows_probe as evaluation
    import mcp_servers.rag_server as rag
    def search(query: str, kb_id: int, top_k: int = 3):
        """Retrieve real PDF chunks from isolated SQL."""
        return rag.search_knowledge_base.fn(query, kb_id, top_k)
    async def inventory():
        """Fixed Probe inventory for free orchestration testing."""
        return evidence(target_id='test-target', operation='inventory', payload={'hostname': 'fixture'})
    @asynccontextmanager
    async def tools(cfg, url, knowledge_kb_id=14):
        yield [StructuredTool.from_function(search, name='search_knowledge_base'),
            StructuredTool.from_function(coroutine=inventory, name='probe_inventory')]
    monkeypatch.setattr(evaluation, 'load_evaluation_tools', tools)
    cfg = SimpleNamespace(target_id='test-target', services={}, dependencies={})
    await evaluation.preflight(cfg, tmp_path, 'http://127.0.0.1:8105/mcp', kb_id=901,
        query='应用内部异常', expected_source='02-application-errors.pdf')
    result = json.loads((tmp_path / 'preflight.json').read_text(encoding='utf-8'))
    assert result['ok'] and result['model_calls'] == 0 and result['evidence_count'] == 1
    assert result['knowledge_mcp']['passed']
    assert result['knowledge_mcp']['fragments'][0]['page'] == '2'
    trace = json.loads((tmp_path / 'tool_trace.json').read_text(encoding='utf-8'))
    assert [row['validated_live_evidence'] for row in trace] == [False, True]
    assert not (tmp_path / 'cost.json').exists()
    runbooks.assert_not_called()


@pytest.mark.parametrize('broken', [False, True])
def test_unspecified_scope_keeps_legacy_local_fallback(runbooks, monkeypatch, broken):
    import src.retrieval.hybrid_retriever as hybrid
    monkeypatch.setattr(settings, 'EXPERIENCE_KB_IDS', '')
    monkeypatch.setattr(settings, 'ENABLE_RERANK', False)
    retrieve = Mock(side_effect=RuntimeError('offline') if broken else None, return_value=[])
    monkeypatch.setattr(hybrid, 'HybridRetriever', lambda: SimpleNamespace(retrieve=retrieve))
    fallback = Mock(return_value='legacy local runbook')
    monkeypatch.setattr(planner, 'retrieve_local', fallback)
    assert planner._retrieve_experience('query') == 'legacy local runbook'
    assert retrieve.call_args.kwargs['kb_ids'] is None
    fallback.assert_called_once_with('query')


@pytest.mark.parametrize('ids,query', [([], '应用内部异常'), ([99999], '应用内部异常'),
    ([902], '应用内部异常'), ([901], 'quantum entanglement')])
def test_explicit_scope_never_falls_back_or_initializes_online(runbooks, monkeypatch, ids, query):
    fallback = Mock(side_effect=AssertionError('scope must not widen'))
    monkeypatch.setattr(planner, 'retrieve_local', fallback)
    assert planner._retrieve_experience(query, ids) == ''
    fallback.assert_not_called()
    runbooks.assert_not_called()


def test_disabled_and_invalid_configuration_do_not_call_online(runbooks, monkeypatch):
    monkeypatch.setenv('ENABLE_EXPERIENCE_CONTEXT', 'false')
    assert planner._retrieve_experience('应用内部异常') == ''
    monkeypatch.setenv('ENABLE_EXPERIENCE_CONTEXT', 'true')
    monkeypatch.setattr(settings, 'EXPERIENCE_KB_IDS', 'invalid')
    assert planner._retrieve_experience('应用内部异常') == ''
    runbooks.assert_not_called()


def test_hybrid_selection_keeps_existing_path_and_explicit_ids_win(db, runbooks, monkeypatch):
    import src.retrieval.hybrid_retriever as hybrid
    from src.models.vector import SearchResult
    db.add(KnowledgeBase(id=903, kb_uid='hybrid', owner_id=1, name='Legacy'))
    db.commit()
    retrieve = Mock(return_value=[SearchResult(id='legacy', score=.8, text='legacy reference',
        metadata={'kb_id': 903, 'filename': 'legacy.pdf', 'page': 3})])
    monkeypatch.setattr(hybrid, 'HybridRetriever', lambda: SimpleNamespace(retrieve=retrieve))
    monkeypatch.setattr(settings, 'ENABLE_RERANK', False)
    payload = json.loads(planner._retrieve_experience('query', [903]))
    assert payload['results'][0]['chunk_id'] == 'legacy'
    assert retrieve.call_args.kwargs['kb_ids'] == [903]
    assert planner._retrieve_experience('应用内部异常', [902]) == ''
    assert retrieve.call_count == 1


def test_explicit_hybrid_scope_keeps_reranking(db, runbooks, monkeypatch):
    import src.retrieval.hybrid_retriever as hybrid
    import src.retrieval.reranker as rerank
    from src.models.vector import SearchResult
    db.add(KnowledgeBase(id=903, kb_uid='hybrid', owner_id=1, name='Legacy'))
    db.commit()
    hits = [SearchResult(id='legacy', score=.8, text='legacy reference', metadata={'kb_id': 903})]
    retrieve = Mock(return_value=hits)
    reorder = Mock(return_value=hits)
    monkeypatch.setattr(hybrid, 'HybridRetriever', lambda: SimpleNamespace(retrieve=retrieve))
    monkeypatch.setattr(rerank, 'DashScopeReranker', lambda: SimpleNamespace(rerank=reorder))
    monkeypatch.setattr(settings, 'ENABLE_RERANK', True)
    assert json.loads(planner._retrieve_experience('query', [903]))['results'][0]['chunk_id'] == 'legacy'
    assert retrieve.call_args.kwargs['kb_ids'] == [903]
    reorder.assert_called_once_with('query', hits)


@pytest.mark.asyncio
@pytest.mark.parametrize('with_observation', [False, True])
async def test_real_retrieval_consumed_by_graph_but_never_proves_handbook_cause(runbooks, monkeypatch, tmp_path, with_observation):
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool
    from src.probe.protocol import evidence
    from src.agent.aiops.strategies import investigation as inv
    import mcp_servers.rag_server as rag
    executor = importlib.import_module('src.agent.aiops.executor')
    graph_module = importlib.import_module('src.agent.aiops.graph')
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'PROBE_ENABLED', True)
    monkeypatch.setattr(settings, 'TERMCP_ENABLED', False)
    monkeypatch.setattr(settings, 'DIAGNOSTIC_TARGET_CATALOG', '')
    def lookup(query: str, kb_id: int):
        """Read the real local knowledge chunks through the MCP tool function."""
        return rag.search_knowledge_base.fn(query, kb_id)
    tool = StructuredTool.from_function(lookup, name='search_knowledge_base')
    sample = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources',
        payload={'cpu_percent': 12, 'memory_percent': 55})
    observed = SimpleNamespace(name='probe_resource_snapshot', description='resources', args={},
        ainvoke=AsyncMock(return_value=sample))
    tools = [tool, observed]
    monkeypatch.setattr(planner, 'load_agent_tools', AsyncMock(return_value=(tools, None)))
    monkeypatch.setattr(planner, 'create_agent_llm', lambda **kw: object())
    planned = AsyncMock(return_value=planner.Plan(steps=['查运维手册']))
    monkeypatch.setattr(planner, 'ainvoke_structured', planned)
    monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    messages = [AIMessage(content='', tool_calls=[{'id': 'lookup', 'name': tool.name,
        'args': {'query': '应用内部异常', 'kb_id': 901}}]), AIMessage(content='找到参考手册')]
    if with_observation:
        messages.extend([AIMessage(content='', tool_calls=[{'id': 'sample', 'name': observed.name, 'args': {}}]),
                         AIMessage(content='资源采样完成')])
    execute = AsyncMock(side_effect=messages)
    monkeypatch.setattr(executor, 'ainvoke_with_retry', execute)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    followup = inv.InvestigationDecision(hypothesis='应用异常待核实',
        next_check='核对当前资源', next_tools=[observed.name],
        next_arguments={observed.name: {}},
        discriminating_question='当前是否存在资源压力', expected_observation='资源正常会削弱资源压力解释')
    unsupported = inv.InvestigationDecision(hypothesis='仅从手册推断应用异常', root_cause='应用内部异常',
        conclusion_level='confirmed_cause', scope='本轮请求',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='应用内部异常')],
        blocked_reason='固定输入结束，缺少应用现场日志')
    decide = AsyncMock(side_effect=[followup, unsupported] if with_observation else [unsupported])
    monkeypatch.setattr(inv, 'ainvoke_structured', decide)
    service = graph_module.AIOpsService()
    try:
        graph = service._build_graph(service.replan_strategy)
        final = await graph.ainvoke({'input': '应用内部异常', 'plan': [], 'past_steps': [],
            'raw_evidence': [], 'response': '', 'autonomous_investigation': True},
            {'configurable': {'thread_id': 'real-knowledge-' + str(with_observation)}})
    finally:
        await service.close()
    assert '02-application-errors.pdf' in planned.call_args.args[3]['experience_context']
    assert final['raw_evidence'][0][0] == '规划前知识检索'
    assert json.loads(decide.call_args_list[0].args[3]['knowledge'])[0]['kb_id'] == 901
    assert '应用内部异常' not in decide.call_args_list[0].args[3]['evidence']
    assert final['diagnosis']['kind'] == 'unlocated'
    assert '02-application-errors.pdf' in final['response'] and '第 2 页' in final['response']
    assert '## 参考知识库' in final['response']
    records = inv.evidence_index(final)
    assert all(r['provenance']['data_source'] != 'knowledge_base' for r in records.values())
    assert len(records) == int(with_observation)
    if with_observation:
        assert len(final['past_steps']) == 2
        assert execute.await_count == 2  # Knowledge remains in investigator context; no executor model for concrete Probe.
        observed.ainvoke.assert_awaited_once()
    runbooks.assert_not_called()
    (tmp_path / 'knowledge-investigation-trace.json').write_text(json.dumps({
        'mode': 'real PDF and SQL; fixed model decisions and Probe inputs',
        'with_observation': with_observation, 'online_constructors': runbooks.call_count,
        'planning_knowledge': json.loads(final['raw_evidence'][0][1]),
        'investigator_knowledge': json.loads(decide.call_args_list[0].args[3]['knowledge']),
        'live_evidence_ids': list(records), 'diagnosis': final['diagnosis'],
        'report': final['response']}, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['protection', 'contradiction', 'knowledge_only'])
async def test_four_groups_share_real_knowledge_but_execute_independent_mechanisms(
        runbooks, engine, monkeypatch, tmp_path, case):
    import hashlib
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import StructuredTool
    from src.agent.aiops import run_store
    from src.agent.aiops.strategies import investigation as inv
    from src.probe.protocol import evidence
    from scripts.evaluate_windows_probe import MECHANISM_GROUPS, configure_mechanisms, save_mechanism_audit
    import mcp_servers.rag_server as rag
    executor = importlib.import_module('src.agent.aiops.executor')
    graphs = importlib.import_module('src.agent.aiops.graph')
    for name, value in {'ENABLE_HITL': False, 'PROBE_ENABLED': True, 'TERMCP_ENABLED': False,
            'ENABLE_DYNAMIC_CLASSIFICATION': False, 'DIAGNOSTIC_TARGET_CATALOG': '',
            'INVESTIGATION_PROTECTION_STEPS': 2}.items():
        monkeypatch.setattr(settings, name, value)
    for name in ('INVESTIGATION_HYPOTHESIS_PROTECTION', 'INVESTIGATION_CONTRADICTION_TRIGGER'):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(planner, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    summaries = []
    for group, (protection, trigger) in MECHANISM_GROUPS.items():
        output = tmp_path / group
        output.mkdir()
        monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(output / 'checkpoints.sqlite'))
        monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(output / 'evidence'))
        expected = configure_mechanisms(group)
        calls = []
        def lookup(query: str, kb_id: int):
            """Read actual PDF chunks through the local MCP function."""
            calls.append('search_knowledge_base')
            return rag.search_knowledge_base.fn(query, kb_id)
        knowledge_tool = StructuredTool.from_function(lookup, name='search_knowledge_base')
        def observed(name, operation, payload):
            async def invoke(args):
                calls.append(name)
                return evidence(target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload)
            return SimpleNamespace(name=name, description=name, args={}, ainvoke=invoke)
        tools = [knowledge_tool,
            observed('probe_dependency_probe', 'dependency_probe', {'dependency': 'db', 'tcp': 'ok'}),
            observed('probe_service_status', 'services', {'service': 'entry', 'state': 'running'}),
            observed('probe_resource_snapshot', 'resources', {'cpu_percent': 12, 'memory_percent': 55})]
        monkeypatch.setattr(planner, 'load_agent_tools', AsyncMock(return_value=(tools, None)))
        monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
        planned = AsyncMock(return_value=planner.Plan(steps=['查运维手册']))
        monkeypatch.setattr(planner, 'ainvoke_structured', planned)
        # The model stub responds only to the scheduled task, never to the group label.
        async def fixed_executor(llm, messages, **kwargs):
            if isinstance(messages[-1], ToolMessage):
                return AIMessage(content='固定决策工具检查结束')
            task = messages[1].content.rsplit('请执行以下诊断步骤: ', 1)[-1]
            if '查运维手册' in task:
                name, args = knowledge_tool.name, {'query': '应用内部异常', 'kb_id': 901}
            elif '核查入口服务状态' in task:
                name, args = 'probe_service_status', {'service': 'entry'}
            elif '核查资源' in task:
                name, args = 'probe_resource_snapshot', {}
            else:
                name, args = 'probe_dependency_probe', {'dependency': 'db'}
            return AIMessage(content='', tool_calls=[{'id': 'fixed-check', 'name': name, 'args': args}])
        monkeypatch.setattr(executor, 'ainvoke_with_retry', fixed_executor)
        def proposal(include_alternative=True):
            return inv.InvestigationDecision(hypothesis='dependency_probe/db: tcp == "failed"',
                hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db',
                    field='tcp', expected='failed'), next_check='核查资源' if case != 'contradiction' else '核查下游',
                next_tools=['probe_resource_snapshot' if case != 'contradiction' else 'probe_dependency_probe'],
                next_arguments={'probe_resource_snapshot': {}} if case != 'contradiction' else {'probe_dependency_probe': {'dependency': 'db'}},
                discriminating_question='下游解释是否成立', expected_observation='TCP 成功会反驳不可达预期',
                    alternatives=[inv.Alternative(explanation='services/entry: state == "stopped"', status='unresolved',
                    condition=inv.ObservationCondition(operation='services', object_name='entry', field='state', expected='stopped'),
                    check=inv.CandidateCheck(next_check='核查入口服务状态', next_tools=['probe_service_status'],
                        next_arguments={'probe_service_status': {'service': 'entry'}},
                        discriminating_question='入口服务是否停止', expected_observation='running 反驳停止预期'))]
                    if include_alternative else [])
        second = proposal(include_alternative=case != 'protection')
        second.next_check = '再次核查下游'
        second.next_tools = ['probe_dependency_probe']
        second.next_arguments = {'probe_dependency_probe': {'dependency': 'db'}}
        second.repeat_reason, second.repeat_evidence_ids = '复核本轮连通变化', ['e1.1']
        answers = [proposal(), second, inv.InvestigationDecision(
            hypothesis='未查清', blocked_reason='固定决策检查结束，缺少根因证据')]
        async def fixed_decision(_llm, _schema, _prompt, context):
            answer = answers.pop(0)
            if answer.repeat_reason:
                answer.repeat_evidence_ids = list(json.loads(context['evidence']))[-1:]
            return answer
        decide = AsyncMock(side_effect=fixed_decision)
        monkeypatch.setattr(inv, 'ainvoke_structured', decide)
        service = graphs.AIOpsService()
        try:
            events = [event async for event in service.execute('应用内部异常', session_id=case, user_id=17)]
            complete = next(event for event in events if event['type'] == 'complete')
            tid = complete['thread_id']
            graph = await service._persistent_graph(service._create_strategy())
            final = (await graph.aget_state({'configurable': {'thread_id': tid}})).values
            audit = await save_mechanism_audit(service, tid, expected, output)
            assert audit['passed'], audit
            trace = json.loads((output / 'mechanism_trace.json').read_text(encoding='utf-8'))
            assert len(trace['decisions']) == 3
            assert all(row['knowledge'] and row['knowledge_sha256'] for row in trace['decisions'])
            assert len({row['knowledge_sha256'] for row in trace['decisions']}) == 1
            for row, call in zip(trace['decisions'], decide.call_args_list):
                assert row['knowledge'] == json.loads(call.args[3]['knowledge'])
                encoded = json.dumps(row['knowledge'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                assert row['knowledge_sha256'] == hashlib.sha256(encoded.encode()).hexdigest()
                assert '02-application-errors.pdf' not in call.args[3]['evidence']
            changed = protection if case == 'protection' else trigger if case == 'contradiction' else False
            selected = 'probe_service_status' if changed else 'probe_dependency_probe'
            assert calls == ['search_knowledge_base',
                'probe_dependency_probe' if case == 'contradiction' else 'probe_resource_snapshot', selected]
            assert trace['decisions'][1]['next_tools'] == [selected]
            assert trace['executed_steps'][-1] == ('核查入口服务状态' if changed else '再次核查下游')
            assert complete['diagnosis']['kind'] == 'unlocated'
            assert '02-application-errors.pdf' in complete['response']
            records = inv.evidence_index(final)
            assert len(records) == 2 and all(key.startswith('ev-') for key in records)
            ledger = run_store.list_evidence(tid, 17)
            assert len(ledger) == 2
            mechanism_events = final['diagnosis']['mechanisms']['events']
            streamed = [event['investigation'] for event in events if event.get('investigation')]
            assert streamed[-1]['events'] == mechanism_events
            assert any(row['next_check'] == trace['executed_steps'][-1] for row in streamed)
            if changed:
                kind = 'protection_check_selected' if case == 'protection' else 'contradiction_triggered'
                assert any(event['kind'] == kind for event in mechanism_events)
            if case == 'knowledge_only':
                assert not any(event['kind'] == 'contradiction_triggered' for event in mechanism_events)
            for event in mechanism_events:
                assert set(event.get('evidence_ids', [])) <= set(records)
            summaries.append({'group': group, 'thread_id': tid, 'config': expected,
                'knowledge_sha256': trace['decisions'][0]['knowledge_sha256'],
                'planning_sha256': hashlib.sha256(planned.call_args.args[3]['experience_context'].encode()).hexdigest(),
                'calls': calls.copy(), 'evidence_ids': list(records), 'audit_passed': audit['passed'],
                'events': mechanism_events, 'diagnosis': complete['diagnosis']['kind']})
        finally:
            await service.close()
        reopened = graphs.AIOpsService()
        try:
            graph = await reopened._persistent_graph(reopened._create_strategy())
            restored = await graph.aget_state({'configurable': {'thread_id': tid}})
            assert restored.values['investigation_memory'] == final['investigation_memory']
            assert restored.values['raw_evidence'] == final['raw_evidence']
        finally:
            await reopened.close()
    assert len({row['thread_id'] for row in summaries}) == 4
    assert len({row['knowledge_sha256'] for row in summaries}) == 1
    assert len({row['planning_sha256'] for row in summaries}) == 1
    assert len({eid for row in summaries for eid in row['evidence_ids']}) == 8
    runbooks.assert_not_called()
    (tmp_path / 'four-group-comparison.json').write_text(json.dumps({
        'mode': 'real PDF/SQL; fixed model decisions and Probe inputs; no effectiveness claim',
        'case': case, 'groups': summaries}, ensure_ascii=False, indent=2), encoding='utf-8')
