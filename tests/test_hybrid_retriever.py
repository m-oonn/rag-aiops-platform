"""混合检索器测试：RRF 融合逻辑。"""

from unittest.mock import MagicMock, patch

import pytest

from src.models.vector import SearchResult
from src.retrieval.hybrid_retriever import HybridRetriever, _rrf_fusion


def _make_result(id_: str, score: float, text: str = "") -> SearchResult:
    return SearchResult(id=id_, score=score, text=text, metadata={})


class TestRRFFusion:
    """RRF 融合单元测试。"""

    def test_both_empty_returns_empty(self):
        assert _rrf_fusion([], [], 10) == []

    def test_only_vector_results(self):
        v = [_make_result("a", 0.9), _make_result("b", 0.8)]
        result = _rrf_fusion(v, [], 10)
        assert len(result) == 2
        assert result[0].id == "a"

    def test_only_bm25_results(self):
        b = [_make_result("c", 0.7)]
        result = _rrf_fusion([], b, 10)
        assert len(result) == 1
        assert result[0].id == "c"

    def test_intersection_boosted(self):
        """两边都命中的 doc 应排在前面。"""
        v = [_make_result("a", 0.9), _make_result("b", 0.2)]
        b = [_make_result("b", 0.6), _make_result("c", 0.5)]
        result = _rrf_fusion(v, b, 10)
        # b 两边都在，RRF 得分高
        assert result[0].id == "b"

    def test_top_k_respected(self):
        v = [_make_result(str(i), 0.9) for i in range(10)]
        b = [_make_result(str(i + 10), 0.9) for i in range(10)]
        result = _rrf_fusion(v, b, 5)
        assert len(result) == 5


class TestHybridRetriever:
    def test_retrieve_empty_query_returns_empty(self):
        hr = HybridRetriever(vector_retriever=MagicMock(), bm25_retriever=MagicMock())
        assert hr.retrieve("") == []

    def test_retrieve_delegates_to_both_and_fuses(self):
        """验证检索委托给两个子检索器并走 RRF 融合。"""
        vec_mock = MagicMock()
        bm25_mock = MagicMock()
        vec_mock.retrieve.return_value = [_make_result("a", 0.9)]
        bm25_mock.retrieve.return_value = [_make_result("b", 0.7)]

        hr = HybridRetriever(vector_retriever=vec_mock, bm25_retriever=bm25_mock)
        # 标记 BM25 已就绪，跳过懒加载
        hr._bm25_populated = True

        results = hr.retrieve("test query", top_k=5)
        assert len(results) == 2
        vec_mock.retrieve.assert_called_once()
        bm25_mock.retrieve.assert_called_once()

    def test_bm25_not_indexed_falls_back_to_vector(self):
        """BM25 未建索引时降级退回到纯向量检索。"""
        vec_mock = MagicMock()
        bm25_mock = MagicMock()
        bm25_mock.is_indexed = False
        bm25_mock.retrieve.return_value = []

        hr = HybridRetriever(vector_retriever=vec_mock, bm25_retriever=bm25_mock)
        hr._bm25_populated = True  # 跳过懒加载尝试

        vec_mock.retrieve.return_value = [_make_result("a", 0.9)]
        results = hr.retrieve("test", top_k=5)
        assert len(results) == 1
        assert results[0].id == "a"

    def test_index_bm25_chunks(self):
        """index_bm25_chunks 应转发给 BM25 子检索器。"""
        bm25_mock = MagicMock()
        hr = HybridRetriever(vector_retriever=MagicMock(), bm25_retriever=bm25_mock)
        chunks = [("id1", "text", {"kb_id": 1})]
        hr.index_bm25_chunks(chunks)
        bm25_mock.index_chunks.assert_called_once_with(chunks)
