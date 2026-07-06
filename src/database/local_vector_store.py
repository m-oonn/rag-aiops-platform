"""本地内存向量存储——Milvus 不可用时的降级方案。

当 Milvus 未运行时，文档处理流程中 embed 出的向量不会丢失，
而是缓存到本模块的进程级内存字典中。检索时用 numpy 余弦相似度
返回 top-k 结果。

设计约束：
- 纯 Python + numpy，无外部依赖；
- 进程级单例，与 MilvusClient 单例对齐；
- 数据量不大时（< 10000 条）性能足够 demo 使用；
- 重启后丢失（生产环境应上 Milvus）。
"""

from typing import Dict, List, Optional, Any
import math
import threading

import numpy as np

from src.models.vector import SearchResult, VectorRecord
from src.utils.logger import logger


class LocalVectorStore:
    """进程级内存向量存储，线程安全。"""

    _instance: Optional["LocalVectorStore"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "LocalVectorStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._store: List[Dict[str, Any]] = []
                cls._instance._store_lock = threading.Lock()
                logger.info("[LocalVectorStore] 初始化本地内存向量存储（Milvus 降级方案）")
        return cls._instance

    # ── 插入 ──────────────────────────────────────────
    def insert(self, records: List[VectorRecord]) -> int:
        """插入向量记录。返回实际插入条数。"""
        if not records:
            return 0
        with self._store_lock:
            for r in records:
                entry = {
                    "id": r.id,
                    "embedding": np.array(r.values, dtype=np.float32),
                    "text": r.metadata.get("text", ""),
                    "metadata": r.metadata,
                    "kb_id": int(r.metadata.get("kb_id", 0)),
                }
                self._store.append(entry)
            count = len(records)
        logger.info(f"[LocalVectorStore] 插入 {count} 条，总量 {len(self._store)}")
        return count

    # ── 检索 ──────────────────────────────────────────
    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """余弦相似度检索，支持 kb_id 过滤。

        expr 格式: "kb_id in [1, 2]" 或 "kb_id == 3"
        """
        if not self._store:
            return []

        q = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm

        # 解析 expr 获取 kb_id 过滤条件
        allowed_kb_ids = self._parse_kb_filter(expr)

        with self._store_lock:
            scores = []
            for entry in self._store:
                # kb_id 过滤
                if allowed_kb_ids is not None and entry["kb_id"] not in allowed_kb_ids:
                    continue
                emb = entry["embedding"]
                emb_norm = np.linalg.norm(emb)
                if emb_norm == 0:
                    continue
                sim = float(np.dot(q, emb / emb_norm))
                scores.append((sim, entry))

            # 按相似度降序
            scores.sort(key=lambda x: x[0], reverse=True)
            top = scores[:top_k]

        results = []
        for sim, entry in top:
            results.append(SearchResult(
                id=entry["id"],
                score=sim,  # 余弦相似度，越高越相关
                text=entry["text"],
                metadata=entry["metadata"],
            ))

        if results:
            logger.info(f"[LocalVectorStore] 检索返回 {len(results)} 条（总量 {len(self._store)}）")
        return results

    # ── 删除 ──────────────────────────────────────────
    def delete_by_kb_id(self, kb_id: int) -> int:
        """删除指定 KB 的所有向量。返回删除条数。"""
        with self._store_lock:
            before = len(self._store)
            self._store = [e for e in self._store if e["kb_id"] != kb_id]
            deleted = before - len(self._store)
        if deleted:
            logger.info(f"[LocalVectorStore] 删除 KB {kb_id} 的 {deleted} 条向量")
        return deleted

    # ── 全量导出（供 HybridRetriever 建 BM25 索引）──
    def get_all_chunks(self) -> List[tuple[str, str, dict]]:
        """返回全部 chunk: [(id, text, metadata), ...]。

        用于 HybridRetriever 首次检索时懒加载建 BM25 索引。
        """
        with self._store_lock:
            return [
                (entry["id"], entry["text"], entry["metadata"])
                for entry in self._store
            ]

    @property
    def size(self) -> int:
        return len(self._store)

    # ── 内部 ──────────────────────────────────────────
    @staticmethod
    def _parse_kb_filter(expr: Optional[str]) -> Optional[set]:
        """从 Milvus expr 字符串中提取 kb_id 过滤集合。

        支持格式:
          "kb_id == 3"        -> {3}
          "kb_id in [1, 2]"   -> {1, 2}
          "kb_id in (1, 2)"   -> {1, 2}
          None / 其他          -> None (不过滤)
        """
        if not expr:
            return None
        expr = expr.strip()
        # "kb_id == N"
        if "==" in expr:
            try:
                val = int(expr.split("==")[-1].strip())
                return {val}
            except (ValueError, IndexError):
                return None
        # "kb_id in [1, 2]" or "kb_id in (1, 2)"
        if " in " in expr.lower():
            try:
                bracket_part = expr.split("in", 1)[-1].strip().strip("[]() ")
                ids = {int(x.strip()) for x in bracket_part.split(",")}
                return ids
            except (ValueError, IndexError):
                return None
        return None
