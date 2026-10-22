"""RAG MCP 对外结果过滤回归测试。"""

from types import SimpleNamespace

from src.models.vector import SearchResult


def test_search_knowledge_base_drops_low_score_results(monkeypatch):
    import mcp_servers.rag_server as server

    class Retriever:
        def retrieve(self, query, top_k, kb_ids):
            return [SearchResult(id="low", text="无关内容", score=0.01, metadata={})]

    class Reranker:
        def rerank(self, query, documents):
            return documents

    monkeypatch.setattr(server, "_get_retriever", lambda: Retriever())
    monkeypatch.setattr(server, "_get_reranker", lambda: Reranker())
    monkeypatch.setattr(server, "settings", SimpleNamespace(RAG_MIN_SCORE=0.1))

    result = server.search_knowledge_base.fn("量子纠缠实验怎么做", 14, 3)

    assert result["results"] == []
    assert result["total"] == 0


def test_search_knowledge_base_keeps_traceable_relevant_result(monkeypatch):
    import mcp_servers.rag_server as server

    class Retriever:
        def retrieve(self, query, top_k, kb_ids):
            return [SearchResult(
                id="chunk-1", text="CPU 排查手册", score=0.9,
                metadata={"filename": "cpu.md", "page": 2},
            )]

    monkeypatch.setattr(server, "_get_retriever", lambda: Retriever())
    monkeypatch.setattr(server, "_get_reranker", lambda: None)
    monkeypatch.setattr(server, "settings", SimpleNamespace(RAG_MIN_SCORE=0.1))

    result = server.search_knowledge_base.fn("CPU 飙升", 14, 3)

    assert result["total"] == 1
    assert result["results"][0]["source"] == "cpu.md"
    assert result["results"][0]["page"] == 2


def test_real_local_bm25_through_rag_tool_keeps_guidance_separate_from_live_evidence(monkeypatch):
    import json
    import mcp_servers.rag_server as server
    from src.retrieval.bm25_retriever import BM25Retriever
    from src.agent.aiops.evidence_sources import knowledge_context
    from src.agent.aiops.strategies.investigation import evidence_index
    retriever = BM25Retriever()
    retriever.index_chunks([
        ('app-check', 'localapp availability inspect downstream connectivity and application logs',
            {'kb_id': 14, 'filename': 'localapp.md', 'page': 1}),
        ('other-kb', 'localapp availability private other library', {'kb_id': 15}),
        ('disk', 'disk capacity filesystem volumes remaining storage', {'kb_id': 14}),
        ('cpu', 'processor saturation resource sampling intervals', {'kb_id': 14}),
        ('auth', 'identity login certificate expiry authentication', {'kb_id': 14}),
    ])
    monkeypatch.setattr(server, '_get_retriever', lambda: retriever)
    monkeypatch.setattr(server, '_get_reranker', lambda: None)
    monkeypatch.setattr(server, 'settings', SimpleNamespace(RAG_MIN_SCORE=0.1))
    result = server.search_knowledge_base.fn('localapp availability', 14, 3)
    assert result['total'] == 1 and result['results'][0]['chunk_id'] == 'app-check'
    raw = [('retrieve', json.dumps(result))]
    assert knowledge_context(raw)[0]['source'] == 'localapp.md'
    assert 'downstream connectivity' in knowledge_context(raw)[0]['content']
    assert evidence_index({'raw_evidence': raw}) == {}
