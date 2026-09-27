"""reranker.py 的功能测试。

目标：验证重排序逻辑正确处理空输入、ENABLE_RERANK 关闭时的降级、
API 成功时的分数更新、以及 API 异常时的安全降级。
"""

import pytest
from unittest.mock import patch, MagicMock
from http import HTTPStatus

from src.models.vector import SearchResult


class TestDashScopeReranker:
    """DashScopeReranker.rerank() 的行为验证。"""

    def _make_docs(self, n=3):
        """构造 n 个 SearchResult 文档。"""
        return [
            SearchResult(id=str(i), score=0.1 * i, text=f"doc_{i}", metadata={})
            for i in range(n)
        ]

    def _make_reranker(self, enable_rerank=True):
        """构造一个 mock 了 settings 的 DashScopeReranker。"""
        with patch("src.retrieval.reranker.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = "fake-key"
            mock_settings.RERANK_MODEL = "fake-model"
            mock_settings.RERANK_TOP_N = 5
            mock_settings.ENABLE_RERANK = enable_rerank
            from src.retrieval.reranker import DashScopeReranker
            reranker = DashScopeReranker()
            return reranker

    def test_empty_documents_returns_empty(self):
        """空文档列表应直接返回空列表。"""
        reranker = self._make_reranker()
        result = reranker.rerank("query", [])
        assert result == []

    def test_rerank_disabled_returns_top_n(self):
        """ENABLE_RERANK=False 时应返回前 top_n 个原始文档。"""
        reranker = self._make_reranker(enable_rerank=False)
        docs = self._make_docs(10)

        result = reranker.rerank("query", docs)

        assert len(result) == 5  # top_n=5
        # 分数不应被修改
        for i, doc in enumerate(result):
            assert doc.score == 0.1 * i

    @patch("dashscope.TextReRank")
    def test_successful_rerank_updates_scores(self, mock_textreRank):
        """API 成功时应按 rerank 分数重新排序并更新分数。"""
        mock_resp = MagicMock()
        mock_resp.status_code = HTTPStatus.OK
        mock_resp.output.results = [
            MagicMock(index=2, relevance_score=0.99),
            MagicMock(index=0, relevance_score=0.80),
            MagicMock(index=1, relevance_score=0.50),
        ]
        mock_textreRank.call.return_value = mock_resp

        reranker = self._make_reranker(enable_rerank=True)
        docs = self._make_docs(3)

        result = reranker.rerank("query", docs)

        assert len(result) == 3
        # 重排序后第一个应是原 index=2 的文档
        assert result[0].id == "2"
        assert result[0].score == 0.99
        assert result[1].id == "0"
        assert result[1].score == 0.80

    @patch("dashscope.TextReRank")
    def test_api_error_falls_back_to_original(self, mock_textreRank):
        """API 返回错误状态码时应降级返回前 top_n 个原始文档。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.code = "internal_error"
        mock_resp.message = "server error"
        mock_textreRank.call.return_value = mock_resp

        reranker = self._make_reranker(enable_rerank=True)
        docs = self._make_docs(3)

        result = reranker.rerank("query", docs)

        assert len(result) == 3
        # 降级返回原始顺序
        assert result[0].id == "0"

    @patch("dashscope.TextReRank")
    def test_exception_falls_back_to_original(self, mock_textreRank):
        """API 抛异常时应安全降级返回前 top_n 个原始文档。"""
        mock_textreRank.call.side_effect = RuntimeError("network error")

        reranker = self._make_reranker(enable_rerank=True)
        docs = self._make_docs(3)

        result = reranker.rerank("query", docs)

        assert len(result) == 3
        assert result[0].id == "0"
