"""向量 + BM25 混合检索，RRF 融合。

用 Reciprocal Rank Fusion 合并两种检索结果：
  1. 向量检索（语义匹配）
  2. BM25 检索（关键词精确匹配）

RRF 得分 = Σ 1 / (k + rank_i)，k 默认 60（标准值）。
两边都命中的 chunk 会被提升排序。
"""

from typing import Any, Optional

from src.retrieval.base_retriever import BaseRetriever
from src.retrieval.vector_retriever import VectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.database.vector_db import MilvusClient
from src.embedding import get_embedding_service
from src.models.vector import SearchResult
from src.utils.logger import logger


_RRF_K = 60  # RRF 融合常数


def _rrf_fusion(
    vector_results: list[SearchResult],
    bm25_results: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion 融合两组检索结果。"""
    # 用 id 做 key 聚合得分
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for rank, r in enumerate(vector_results, 1):
        scores[r.id] = scores.get(r.id, 0) + 1.0 / (_RRF_K + rank)
        # 向量检索的 text 和 metadata 更完整，优先保留
        if r.id not in meta:
            meta[r.id] = {"text": r.text, "metadata": r.metadata, "score": r.score}

    for rank, r in enumerate(bm25_results, 1):
        scores[r.id] = scores.get(r.id, 0) + 1.0 / (_RRF_K + rank)
        if r.id not in meta:
            meta[r.id] = {"text": r.text, "metadata": r.metadata, "score": r.score}
        # 如果向量也有，保留向量得分用于参考
        elif meta[r.id]["score"] is None or meta[r.id]["score"] == 0:
            meta[r.id]["score"] = r.score

    # 按 RRF 得分降序
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ranked = ranked[:top_k]

    return [
        SearchResult(
            id=rid,
            score=meta[rid]["score"],
            text=meta[rid].get("text", ""),
            metadata=meta[rid].get("metadata", {}),
        )
        for rid, _ in ranked
    ]


class HybridRetriever(BaseRetriever):
    """向量 + BM25 混合检索，RRF 融合。

    初始化时可选传 vector_retriever 和 bm25_retriever，不传则新建默认实例。
    """

    def __init__(
        self,
        vector_retriever: Optional[VectorRetriever] = None,
        bm25_retriever: Optional[BM25Retriever] = None,
    ):
        self.vector = vector_retriever or VectorRetriever()
        self.bm25 = bm25_retriever or BM25Retriever()
        self._bm25_populated = False

    def _ensure_bm25_indexed(self, kb_ids: Any = None) -> None:
        """懒加载 BM25 索引：首次检索时从向量库全量拉取 chunks。

        临时方案——只有首次调用 retrieve 时建一次索引。
        增量更新在有新文档上传后调用 index_chunks 触发。
        """
        if self._bm25_populated or self.bm25.is_indexed:
            return
        try:
            # 从 Milvus/本地存储全量拉取
            from src.database.vector_db import MilvusClient
            from src.database.local_vector_store import LocalVectorStore

            milvus = MilvusClient()
            local = LocalVectorStore()
            # 本地存储持有所有 chunk 副本
            chunks = local.get_all_chunks()
            if not chunks:
                logger.info("[hybrid_retriever] 无 chunks 可建 BM25 索引")
                self._bm25_populated = True
                return

            indexed = []
            for cid, text, metadata in chunks:
                if text:
                    indexed.append((str(cid), str(text), metadata))

            if indexed:
                self.bm25.index_chunks(indexed)
                logger.info("[hybrid_retriever] BM25 索引完成: %d chunks", len(indexed))
            self._bm25_populated = True
        except Exception as e:
            logger.warning("[hybrid_retriever] BM25 索引懒加载失败: %s", e)
            self._bm25_populated = True  # 避免反复尝试

    def index_bm25_chunks(self, chunks: list[tuple[str, str, dict]]) -> None:
        """外部调用：文档处理完成后调用此方法同步 BM25 索引。

        Args:
            chunks: [(id, text, metadata), ...]
        """
        if chunks:
            self.bm25.index_chunks(chunks)
            logger.info("[hybrid_retriever] BM25 增量索引: %d chunks", len(chunks))

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        kb_ids: Optional[list[int]] = None,
        **kwargs,
    ) -> list[SearchResult]:
        """混合检索：向量 + BM25 → RRF 融合。

        向量和 BM25 各自检索 top_k * 2，RRF 融合后取 top_k。
        这样两边都命中的 chunk 获得更高的融合排名。
        """
        if not query:
            return []

        # 懒加载 BM25 索引
        self._ensure_bm25_indexed(kb_ids)

        # 并行执行向量和 BM25 检索
        vector_results = self.vector.retrieve(query, top_k=top_k * 2, kb_ids=kb_ids, **kwargs)
        bm25_results = self.bm25.retrieve(query, top_k=top_k * 2, kb_ids=kb_ids)

        if not bm25_results:
            # BM25 无结果或未就绪，降级为纯向量检索
            return vector_results[:top_k]

        if not vector_results:
            # 向量无结果但 BM25 有（罕见，文档已索引但向量库空）
            return bm25_results[:top_k]

        return _rrf_fusion(vector_results, bm25_results, top_k)
