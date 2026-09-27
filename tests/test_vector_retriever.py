"""vector_retriever.py 的功能测试。

目标：验证向量检索逻辑正确构建查询表达式、处理空结果和 kb_id 过滤。
mock MilvusClient 和 embedding service，测试真实 retrieve() 方法。
"""

import pytest
from unittest.mock import patch, MagicMock

from src.models.vector import SearchResult


class TestVectorRetrieverRetrieve:
    """VectorRetriever.retrieve() 的路由逻辑。"""

    def _make_retriever(self, mock_results=None):
        """构造一个 mock 了 Milvus 和 embedding 的 VectorRetriever。"""
        with patch("src.retrieval.vector_retriever.MilvusClient") as MockMilvus, \
             patch("src.retrieval.vector_retriever.get_embedding_service") as MockEmbed:
            mock_client = MagicMock()
            mock_client.search.return_value = mock_results or []
            MockMilvus.return_value = mock_client

            mock_embed = MagicMock()
            mock_embed.embed_query.return_value = [0.1, 0.2, 0.3]
            MockEmbed.return_value = mock_embed

            from src.retrieval.vector_retriever import VectorRetriever
            retriever = VectorRetriever()
            return retriever, mock_client, mock_embed

    def test_returns_search_results(self):
        """有匹配结果时应返回 SearchResult 列表。"""
        fake_results = [
            SearchResult(id="1", score=0.95, text="doc1", metadata={"kb_id": 1}),
            SearchResult(id="2", score=0.85, text="doc2", metadata={"kb_id": 1}),
        ]
        retriever, mock_client, _ = self._make_retriever(fake_results)

        results = retriever.retrieve("query text", top_k=5)

        assert len(results) == 2
        assert results[0].id == "1"
        assert results[0].score == 0.95

    def test_empty_query_vector_returns_empty(self):
        """embedding 返回空向量时应返回空列表。"""
        with patch("src.retrieval.vector_retriever.MilvusClient"), \
             patch("src.retrieval.vector_retriever.get_embedding_service") as MockEmbed:
            mock_embed = MagicMock()
            mock_embed.embed_query.return_value = []
            MockEmbed.return_value = mock_embed

            from src.retrieval.vector_retriever import VectorRetriever
            retriever = VectorRetriever()

            results = retriever.retrieve("query", top_k=5)
            assert results == []

    def test_kb_ids_filter_is_applied(self):
        """kb_ids 参数应生成正确的 Milvus 过滤表达式。"""
        retriever, mock_client, _ = self._make_retriever([])

        retriever.retrieve("query", top_k=5, kb_ids=[1, 2, 3])

        call_args = mock_client.search.call_args
        expr = call_args.kwargs.get("expr")
        assert expr is not None
        assert "kb_id" in expr
        assert "1" in expr and "2" in expr and "3" in expr

    def test_single_kb_id_filter_is_applied(self):
        """单个 kb_id 参数应生成 kb_id == N 过滤表达式。"""
        retriever, mock_client, _ = self._make_retriever([])

        retriever.retrieve("query", top_k=5, kb_id=42)

        call_args = mock_client.search.call_args
        expr = call_args.kwargs.get("expr")
        assert expr is not None
        assert "42" in expr

    def test_no_kb_filter_when_not_provided(self):
        """未提供 kb_id/kb_ids 时不应生成过滤表达式。"""
        retriever, mock_client, _ = self._make_retriever([])

        retriever.retrieve("query", top_k=5)

        call_args = mock_client.search.call_args
        expr = call_args.kwargs.get("expr")
        assert expr is None

    def test_top_k_is_passed_to_milvus(self):
        """top_k 参数应传递给 Milvus 搜索。"""
        retriever, mock_client, _ = self._make_retriever([])

        retriever.retrieve("query", top_k=15)

        call_args = mock_client.search.call_args
        assert call_args.kwargs.get("top_k") == 15

# 集成测试标记:依赖外部服务(PostgreSQL/Redis/Elasticsearch/Milvus/网络),默认不执行(见 pytest.ini)
pytestmark = pytest.mark.integration
