"""Fixed model responses + real LangGraph/Probe: workflow checks, not AI grading."""
import importlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def create_local_knowledge_server(directory: Path):
    """Disposable local-only BM25 service; no production corpus or paid clients."""
    from fastmcp import FastMCP
    from src.retrieval.bm25_retriever import BM25Retriever
    from src.settings import settings
    import mcp_servers.rag_server as rag_server
    retriever = BM25Retriever()
    from scripts.knowledge_conditions import fixture_chunks
    retriever.index_chunks(fixture_chunks(directory))
    rag_server._get_retriever = lambda: retriever
    rag_server._get_reranker = lambda: None
    settings.RAG_MIN_SCORE = 0.1
    server = FastMCP('LocalKnowledgeVerification')
    server.add_tool(rag_server.search_knowledge_base)
    return server


async def verify_graph(tools, output: Path, log: Path, scenario: str, knowledge_tool):
    from langchain_core.messages import AIMessage, ToolMessage
    from src.settings import settings
    from src.agent.aiops import run_store
    from src.probe.evidence import validate_evidence
    from src.probe.protocol import redact
    from scripts.evaluate_windows_probe import local_runbook_retrieval, business_catalog
    from src.probe.windows.config import load_config
    graph_module = importlib.import_module('src.agent.aiops.graph')
    planner = importlib.import_module('src.agent.aiops.planner')
    executor = importlib.import_module('src.agent.aiops.executor')
    investigation = importlib.import_module('src.agent.aiops.strategies.investigation')
    calls = {'executor': 0, 'decisions': 0, 'planner': 0, 'paid': 0}
    assert knowledge_tool.name == 'search_knowledge_base'

    async def load(*args, **kwargs):
        return [*tools.values(), knowledge_tool], None

    async def plan(*args, **kwargs):
        calls['planner'] += 1
        inputs = args[3]
        assert 'localapp' in inputs['experience_context']
        assert '手册不是现场事实' in inputs['experience_context']
        (output / ('planner-context-' + scenario + '.txt')).write_text(
            inputs['experience_context'], encoding='utf-8')
        return planner.Plan(steps=['检查测试应用入口'])

    async def react(llm, messages, **kwargs):
        assert '手册不是现场事实' in messages[0].content
        assert 'localapp' in messages[0].content and 'downstream' in messages[0].content
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content='替代模型流程摘要；现场结论以原始证据为准。')
        calls['executor'] += 1
        selected = [('probe_dependency_probe', {'dependency': 'localapp'}),
                    ('search_knowledge_base', {'query': 'localapp availability', 'kb_id': 14})]
        if calls['executor'] == 2:
            assert 'localapp-guide' in messages[0].content
            selected = [('probe_dependency_probe', {'dependency': 'downstream'}),
                        ('probe_text_log', {'service': 'localapp', 'path': str(log), 'lines': 20})]
        if calls['executor'] > 2:
            prefix = '此项检查由确定性策略选定，必须调用指定工具并原样使用这些参数：'
            policy = next((line.split(prefix, 1)[1] for line in messages[0].content.splitlines()
                           if prefix in line), None)
            assert policy is not None, 'unexpected extra executor step without a policy check'
            check = json.loads(policy)
            selected = [(check['tool'], check['arguments'])]
        assert calls['executor'] <= 5, 'unexpected extra executor step'
        return AIMessage(content='', tool_calls=[{'id': str(index), 'name': name, 'args': args}
            for index, (name, args) in enumerate(selected)])

    async def decide(llm, schema, prompt, inputs, **kwargs):
        assert '手册不是现场事实' in inputs['references']
        assert 'downstream' in inputs['references']
        calls['decisions'] += 1
        knowledge = json.loads(inputs['knowledge'])
        assert knowledge and knowledge[0]['chunk_id'] == 'localapp-guide'
        assert '手册不是现场事实' in knowledge[0]['content']
        assert 'localapp-guide' not in inputs['evidence']
        if calls['decisions'] == 1:
            return investigation.InvestigationDecision(hypothesis='入口与依赖需交叉核实',
                next_check='核对模拟下游和应用日志',
                next_tools=['probe_dependency_probe', 'probe_text_log'],
                next_arguments={'probe_dependency_probe': {'dependency': 'downstream'},
                    'probe_text_log': {'service': 'localapp', 'path': str(log), 'lines': 20}},
                discriminating_question='入口异常是否同时伴随下游连接异常',
                expected_observation='下游连接状态和应用日志能补充入口检查的范围')
        context = json.loads(inputs['evidence'])
        citations = [investigation.Citation(evidence_id=key, quote=value['excerpt'][:100])
            for key, value in context.items() if value.get('excerpt')]
        return investigation.InvestigationDecision(hypothesis='本次为替代模型流程验收，未进行自主归因',
            supporting_evidence=citations,
            blocked_reason='替代模型不评价故障根因；真实自主调查尚未运行',
            alternatives=[investigation.Alternative(explanation='其他应用或依赖内部原因',
                status='unavailable', limitation='本流程测试没有自主检查这些解释')])

    factory = lambda **kwargs: SimpleNamespace(bind_tools=lambda tools: object())
    service = None
    with ExitStack() as stack:
        for key, value in {'PROBE_ENABLED': True, 'TERMCP_ENABLED': False, 'ENABLE_HITL': False,
                           'AIOPS_CHECKPOINT_DB_PATH': str(output / 'graph-checkpoints.sqlite')}.items():
            stack.enter_context(patch.object(settings, key, value))
        for module in (planner, executor):
            stack.enter_context(patch.object(module, 'load_agent_tools', load))
            stack.enter_context(patch.object(module, 'create_agent_llm', factory))
        retrieve = stack.enter_context(local_runbook_retrieval(output / 'runbooks', output))
        stack.enter_context(patch.object(planner, '_retrieve_experience', retrieve))
        stack.enter_context(patch.object(settings, 'DIAGNOSTIC_TARGET_CATALOG',
            business_catalog(load_config(output / 'config.toml'))))
        stack.enter_context(patch.object(planner, 'ainvoke_structured', plan))
        stack.enter_context(patch.object(executor, '_get_tools_for_state', load))
        stack.enter_context(patch.object(executor, 'ainvoke_with_retry', react))
        stack.enter_context(patch.object(investigation, 'create_agent_llm', factory))
        stack.enter_context(patch.object(investigation, 'ainvoke_structured', decide))
        import httpx
        original_transport = httpx.AsyncHTTPTransport.handle_async_request
        async def local_only(transport, request):
            if request.url.host not in {'127.0.0.1', '::1'}:
                raise AssertionError('external HTTP forbidden in free graph verification')
            return await original_transport(transport, request)
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', local_only))
        service = graph_module.AIOpsService()
        try:
            events = [event async for event in service.execute('检查本机 localapp 测试应用的可用性',
                session_id='fixed-' + scenario, user_id=1, terminal_enabled=False)]
            assert not any(event['type'] == 'error' for event in events)
            complete = next(event for event in events if event['type'] == 'complete')
            thread_id, report = complete['thread_id'], complete['response']
            (output / ('graph-' + scenario + '-events.json')).write_text(
                json.dumps(redact(events), ensure_ascii=False, indent=2), encoding='utf-8')
            expected_kind = 'localized_fault' if scenario == 'downstream_unreachable' else 'unlocated'
            assert complete['diagnosis']['kind'] == expected_kind
            assert complete['diagnosis']['unresolved_questions']
            assert 'localapp-guide' in report and '参考知识库' in report
            ledger = run_store.list_evidence(thread_id, 1)
            expected_steps = 5 if scenario == 'downstream_unreachable' else 2
            expected_evidence = 7 if scenario == 'downstream_unreachable' else 4
            assert len(ledger) == expected_evidence
            assert len([event for event in events if event['type'] == 'evidence']) == expected_evidence
            assert run_store.get_run(thread_id).status == 'completed'
            # Only the initial executor step uses the model stub; followups execute concrete arguments.
            assert calls['planner'] == calls['executor'] == 1 and calls['decisions'] == expected_steps
            for item in ledger:
                saved = run_store.get_evidence(thread_id, item['evidence_id'], 1, include_raw=True)
                validate_evidence(saved['raw'], target_id=settings.PROBE_TARGET_ID)
                raw_time = saved['raw']['collected_at']
                assert datetime.fromisoformat(item['collected_at'].replace('Z', '+00:00')) == datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                assert saved['raw']['raw_hash'] == item['raw_hash']
            refs = complete['diagnosis']['evidence']
            assert refs and all(ref['evidence_id'] in {item['evidence_id'] for item in ledger} for ref in refs)
            assert all(ref['quote'] in json.dumps(run_store.get_evidence(thread_id, ref['evidence_id'], 1, include_raw=True)['raw'], ensure_ascii=False) for ref in refs)
            await service.close()
            service = graph_module.AIOpsService()
            graph = await service._persistent_graph(service._create_run_strategy())
            state = await graph.aget_state({'configurable': {'thread_id': thread_id}})
            assert not state.next and not state.values['plan']
            assert state.values['response'] == report and len(state.values['past_steps']) == expected_steps
            assert state.values['autonomous_investigation'] and not state.values['terminal_enabled']
            assert state.values['target_resolution']['status'] == 'resolved'
            assert state.values['target_resolution']['allowed_dependencies'] == ['downstream', 'localapp']
            from src.agent.aiops.evidence_reader import evidence_read_tool
            first = ledger[0]
            read = await executor._run_single_tool({'id': 'read-existing', 'name': 'read_run_evidence',
                'args': {'evidence_id': first['evidence_id'], 'limit': 100}},
                {'read_run_evidence': evidence_read_tool(thread_id, 1)})
            assert read.artifact['status'] == 'success' and read.artifact['action'] == 'evidence_read'
            assert json.loads(read.content)['new_observation'] is False
            assert executor._record_probe_evidence(state.values, read.content, 'inventory') == []
            assert len(run_store.list_evidence(thread_id, 1)) == expected_evidence
            assert '手册不是现场事实' in state.values['investigation_reference_context']
            assert 'downstream' in state.values['investigation_reference_context']
            from src.agent.aiops.evidence_sources import knowledge_context
            assert knowledge_context(state.values['raw_evidence'])[0]['chunk_id'] == 'localapp-guide'
            assert len(investigation.evidence_index(state.values)) == expected_evidence
            (output / ('graph-' + scenario + '.json')).write_text(json.dumps(redact({
                'events': events, 'report': report, 'ledger': ledger}), ensure_ascii=False, indent=2), encoding='utf-8')
            return {'case': 'fixed_model_graph_' + scenario, 'status': 'passed', 'thread_id': thread_id,
                    'evidence_count': len(ledger), 'checkpoint_reopened': True, 'model_calls': 0,
                    'autonomous_model_investigation': False, 'fixed_decisions': calls,
                    'local_runbook_context_verified': True, 'mid_investigation_bm25_verified': True,
                    'knowledge_transport': 'streamable_http_loopback', 'vector_rag_evaluated': False}
        finally:
            if service:
                await service.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Disposable loopback knowledge MCP; no paid model calls')
    parser.add_argument('--serve-knowledge', type=int, required=True)
    parser.add_argument('--runbooks', type=Path, required=True)
    args = parser.parse_args()
    create_local_knowledge_server(args.runbooks).run(transport='streamable-http',
        host='127.0.0.1', port=args.serve_knowledge, path='/mcp', show_banner=False)
