"""本地持久化向量存储——Milvus 不可用时的降级方案(持久化版)。

当 Milvus 未运行时，文档处理流程中 embed 出的向量不会丢失:
- 内存缓存 + 原子落盘到 data/vectors/ (vectors.npy + vectors_meta.json)
- 进程重启后从磁盘加载恢复(重启不丢);
- API 进程与 Celery worker 进程共享同一份磁盘数据——写入方原子替换,
  检索方按数据文件 mtime 检测增量重载,实现跨进程一致。

设计约束:
- 纯 Python + numpy，无外部依赖;
- 数据量不大时(< 10000 条)性能足够 demo 使用;
- 写操作串行(单 worker 顺序消费),原子 rename 保证读一致性。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from src.models.vector import SearchResult, VectorRecord
from src.settings import settings
from src.utils.logger import logger

# 持久化文件名
_VECTOR_FILE = "vectors.npy"
_META_FILE = "vectors_meta.json"


class LocalVectorStore:
    """本地持久化向量存储，线程安全，支持跨进程共享。"""

    _instance: Optional["LocalVectorStore"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "LocalVectorStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._store: List[Dict[str, Any]] = []
                cls._instance._store_lock = threading.Lock()
                cls._instance._data_dir = Path(settings.VECTOR_DIR)
                cls._instance._data_dir.mkdir(parents=True, exist_ok=True)
                # 磁盘数据指纹: (mtime_ns, size)，用于跨进程增量重载
                cls._instance._disk_stamp = (0, 0)
                cls._instance._load()
                logger.info("[LocalVectorStore] 初始化本地持久化向量存储（Milvus 降级方案）")
        return cls._instance

    # ── 磁盘持久化 ──────────────────────────────────────
    def _paths(self) -> tuple[Path, Path]:
        return self._data_dir / _VECTOR_FILE, self._data_dir / _META_FILE

    def _update_disk_stamp(self) -> None:
        _, meta_file = self._paths()
        try:
            st = meta_file.stat()
            self._disk_stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            self._disk_stamp = (0, 0)

    def _save(self) -> None:
        """原子落盘: tmp 文件 + rename, 避免读进程看到半写文件。"""
        vec_file, meta_file = self._paths()
        with self._store_lock:
            ids = [e["id"] for e in self._store]
            texts = [e["text"] for e in self._store]
            metas = [e["metadata"] for e in self._store]
            kb_ids = [e["kb_id"] for e in self._store]
            embeddings = (
                np.stack([e["embedding"] for e in self._store])
                if self._store
                else np.zeros((0, 0), dtype=np.float32)
            )
        meta = {"ids": ids, "texts": texts, "metadatas": metas, "kb_ids": kb_ids}
        # 临时文件需以 .npy/.json 结尾: np.save 会对不以 .npy 结尾的文件名自动追加 .npy,
        # 否则 tmp 名与目标名错位,os.replace 会因源不存在而失败。
        tmp_v = vec_file.parent / (vec_file.name + ".tmp.npy")
        tmp_m = meta_file.parent / (meta_file.name + ".tmp")
        np.save(tmp_v, embeddings)
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        os.replace(tmp_v, vec_file)
        os.replace(tmp_m, meta_file)
        self._update_disk_stamp()

    def _load(self) -> None:
        """从磁盘加载（启动恢复 / 跨进程检测到新数据）。"""
        vec_file, meta_file = self._paths()
        if not (vec_file.exists() and meta_file.exists()):
            return
        try:
            embeddings = np.load(vec_file, allow_pickle=True)
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            ids = meta.get("ids", [])
            texts = meta.get("texts", [])
            metadatas = meta.get("metadatas", [])
            kb_ids = meta.get("kb_ids", [])
            store: List[Dict[str, Any]] = []
            for i, eid in enumerate(ids):
                store.append({
                    "id": eid,
                    "embedding": np.asarray(embeddings[i], dtype=np.float32),
                    "text": texts[i] if i < len(texts) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "kb_id": int(kb_ids[i]) if i < len(kb_ids) else 0,
                })
            with self._store_lock:
                self._store = store
            self._update_disk_stamp()
            logger.info(f"[LocalVectorStore] 从磁盘加载 {len(store)} 条向量")
        except Exception as e:
            logger.warning(f"[LocalVectorStore] 磁盘加载失败(忽略,保持空): {e}")

    def _reload_if_changed(self) -> None:
        """跨进程一致性: 检测磁盘数据比内存新(其他进程写入)则重载。"""
        _, meta_file = self._paths()
        try:
            st = meta_file.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = (0, 0)
        if stamp != self._disk_stamp:
            self._load()

    # ── 插入 ────────────────────────────────────────────
    def insert(self, records: List[VectorRecord]) -> int:
        """插入向量记录并落盘。返回实际插入条数。"""
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
        self._save()
        logger.info(f"[LocalVectorStore] 插入 {count} 条，总量 {len(self._store)}")
        return count

    # ── 检索 ────────────────────────────────────────────
    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """余弦相似度检索，支持 kb_id 过滤。

        expr 格式: "kb_id in [1, 2]" 或 "kb_id == 3"
        """
        self._reload_if_changed()
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

    # ── 删除 ────────────────────────────────────────────
    def delete_by_kb_id(self, kb_id: int) -> int:
        """删除指定 KB 的所有向量并落盘。返回删除条数。"""
        with self._store_lock:
            before = len(self._store)
            self._store = [e for e in self._store if e["kb_id"] != kb_id]
            deleted = before - len(self._store)
        if deleted:
            self._save()
            logger.info(f"[LocalVectorStore] 删除 KB {kb_id} 的 {deleted} 条向量")
        return deleted

    # ── 全量导出（供 HybridRetriever 建 BM25 索引）──
    def get_all_chunks(self) -> List[tuple[str, str, dict]]:
        """返回全部 chunk: [(id, text, metadata), ...]。

        用于 HybridRetriever 首次检索时懒加载建 BM25 索引。
        """
        self._reload_if_changed()
        with self._store_lock:
            return [
                (entry["id"], entry["text"], entry["metadata"])
                for entry in self._store
            ]

    @property
    def size(self) -> int:
        self._reload_if_changed()
        return len(self._store)

    # ── 内部 ────────────────────────────────────────────
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
