"""轻量 BM25 关键词检索器，内存倒排索引。

基于 rank_bm25 库（纯 Python，无外部依赖）。中文按字符 unigram 分词，
英文按空格/split 分词。作为向量检索的补充，在关键词精确匹配场景下兜底。

用法：
    retriever = BM25Retriever()
    retriever.index_chunks([("id1", "text1", {"kb_id": 1}), ...])
    results = retriever.retrieve("query", top_k=5, kb_ids=[1])
"""

import re
from typing import Any, Optional
from rank_bm25 import BM25Okapi

from src.retrieval.base_retriever import BaseRetriever
from src.models.vector import SearchResult


def _tokenize(text: str) -> list[str]:
    """中英混合分词：中文按字切，英文按空格/标点切。

    这是简化版 BM25 分词，不依赖 jieba/pkuseg 等分词库。
    """
    text = text.lower()
    # 分离中文和非中文
    chinese = re.findall(r"[一-鿿]", text)
    # 非中文部分按非字母数字切分
    non_chinese = re.sub(r"[^a-z0-9]", " ", text).split()
    non_chinese = [w for w in non_chinese if len(w) > 1]
    return chinese + non_chinese


class BM25Retriever(BaseRetriever):
    """记忆型 BM25 关键词检索器。

    需要先调用 index_chunks() 建立索引。增删文档后需重新建索引。
    查询时按 BM25 得分降序返回 SearchResult 列表，得分归一化到 0-1。
    """

    def __init__(self):
        self._chunks: list[tuple[str, str, dict]] = []  # (id, text, metadata)
        self._bm25: Optional[BM25Okapi] = None

    def index_chunks(self, chunks: list[tuple[str, str, dict]]) -> None:
        """全量建索引。

        Args:
            chunks: [(id, text, metadata), ...]
        """
        self._chunks = list(chunks)
        tokenized = [_tokenize(text) for _, text, _ in self._chunks]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    @property
    def is_indexed(self) -> bool:
        return self._bm25 is not None

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        kb_ids: Optional[list[int]] = None,
        **kwargs,
    ) -> list[SearchResult]:
        """BM25 检索。

        Args:
            query: 查询文本
            top_k: 返回条数
            kb_ids: 可选，过滤知识库 ID

        Returns:
            按 BM25 得分降序排列的 SearchResult 列表（score 归一化到 0-1）
        """
        if not query or not self._bm25:
            return []

        tokenized_query = _tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)

        # 组装结果，可选按 kb_id 过滤
        results: list[tuple[str, float, str, dict]] = []
        for i, score in enumerate(scores):
            if score <= 0:
                continue
            chunk_id, text, metadata = self._chunks[i]

            if kb_ids is not None:
                chunk_kb_id = metadata.get("kb_id")
                if chunk_kb_id is not None and chunk_kb_id not in kb_ids:
                    continue

            results.append((chunk_id, score, text, metadata))

        # 按得分降序排列
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]

        # 归一化得分到 0-1
        if results:
            max_score = max(r[1] for r in results)
            if max_score > 0:
                results = [
                    (rid, s / max_score, t, m) for rid, s, t, m in results
                ]

        return [
            SearchResult(id=rid, score=s, text=t, metadata=m)
            for rid, s, t, m in results
        ]
