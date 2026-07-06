from typing import List, Dict, Any, Optional
from src.settings import settings
from src.utils.logger import logger
from src.models.vector import VectorRecord, SearchResult
from src.database.local_vector_store import LocalVectorStore


class MilvusClient:
    """Milvus 向量存储客户端—封装 PyMilvus ORM 接口。

    __init__ 时尝试连接 Milvus(host:port),失败则降级为不可用状态。
    之后调用 insert/search 自动跳过,不抛异常。

    进程级单例: 多处 MilvusClient() 复用同一实例,避免 Milvus 不可用时
    每次 new 都等一遍连接超时(本地无 Milvus 时曾拖慢启动 ~1 分钟)。
    """

    _instance: "MilvusClient | None" = None
    _initialized: bool = False

    def __new__(cls) -> "MilvusClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if type(self)._initialized:
            return
        type(self)._initialized = True
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.collection_name = settings.MILVUS_COLLECTION_NAME
        self.dim = settings.MILVUS_DIMENSION
        self.collection = None
        self._available = False
        self.has_kb_id = False
        self._local_store = LocalVectorStore()  # 本地内存降级存储
        try:
            self._connect()
            self._init_collection()
            self._available = True
            logger.info(f"Milvus 已连接 {self.host}:{self.port}")
        except Exception:
            logger.warning(
                f"Milvus 不可用({self.host}:{self.port}),"
                " 向量检索将降级到本地内存存储"
            )

    # ── 连接 ──────────────────────────────────────────
    def _connect(self) -> None:
        from pymilvus import connections

        # 快速连一次——不重试
        connections.connect(
            "default",
            host=self.host,
            port=self.port,
            timeout=5,
        )

    def _init_collection(self) -> None:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            utility,
        )

        if not utility.has_collection(self.collection_name):
            logger.info(f"创建 Milvus collection: {self.collection_name}")
            fields = [
                FieldSchema(
                    name="id", dtype=DataType.VARCHAR,
                    max_length=512, is_primary=True,
                ),
                FieldSchema(
                    name="embedding", dtype=DataType.FLOAT_VECTOR,
                    dim=self.dim,
                ),
                FieldSchema(
                    name="text", dtype=DataType.VARCHAR, max_length=65535,
                ),
                FieldSchema(name="metadata", dtype=DataType.JSON),
                FieldSchema(name="kb_id", dtype=DataType.INT64),
            ]
            schema = CollectionSchema(fields, "RAG Document Collection")
            self.collection = Collection(self.collection_name, schema)
            self.collection.create_index(
                field_name="embedding",
                index_params={
                    "metric_type": "L2",
                    "index_type": "IVF_FLAT",
                    "params": {"nlist": 1024},
                },
            )
            self.collection.create_index(field_name="kb_id",
                                         index_name="kb_id_index")
        else:
            self.collection = Collection(self.collection_name)

        self.collection.load()
        self.has_kb_id = any(
            field.name == "kb_id" for field in self.collection.schema.fields
        )

    # ── 插入 ──────────────────────────────────────────
    def insert(self, records: List[VectorRecord]) -> None:
        if not records:
            return

        # 始终写入本地存储作为降级备份（Milvus 重启后数据仍在本地）
        self._local_store.insert(records)

        if not self._available:
            return

        try:
            ids = [r.id for r in records]
            embeddings = [r.values for r in records]
            texts = [r.metadata.get("text", "") for r in records]
            metadatas = [r.metadata for r in records]
            data = [ids, embeddings, texts, metadatas]
            if self.has_kb_id:
                kb_ids = [int(r.metadata.get("kb_id", 0)) for r in records]
                data.append(kb_ids)
            self.collection.insert(data)
            logger.info(f"Milvus 插入 {len(records)} 条")
        except Exception:
            logger.exception("Milvus insert 失败，数据已存入本地降级存储")

    # ── 检索 ──────────────────────────────────────────
    def search(
        self,
        vector: List[float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[SearchResult]:
        if not self._available:
            # Milvus 不可用，降级到本地内存存储
            return self._local_store.search(vector, top_k=top_k, expr=expr)

        try:
            output_fields = ["text", "metadata"]
            if self.has_kb_id:
                output_fields.append("kb_id")
            if not self.has_kb_id and expr and "kb_id" in expr:
                logger.warning("kb_id 过滤不可用(collection 无此字段)")
                expr = None
            results = self.collection.search(
                data=[vector],
                anns_field="embedding",
                param={"metric_type": "L2", "params": {"nprobe": 10}},
                limit=top_k,
                expr=expr,
                output_fields=output_fields,
            )
            search_results: List[SearchResult] = []
            for hits in results:
                for hit in hits:
                    search_results.append(SearchResult(
                        id=hit.id,
                        score=hit.score,
                        text=hit.entity.get("text"),
                        metadata=hit.entity.get("metadata"),
                    ))
            return search_results
        except Exception:
            logger.exception("Milvus search 失败，降级到本地存储")
            return self._local_store.search(vector, top_k=top_k, expr=expr)

    # ── 按 KB 删除 ─────────────────────────────────────
    def delete_by_kb_id(self, kb_id: int) -> None:
        """删除指定 KB 在 Milvus 和本地存储中的所有向量。"""
        # 始终清理本地存储
        self._local_store.delete_by_kb_id(kb_id)

        if not self._available or not self.has_kb_id:
            return
        try:
            expr = f"kb_id == {int(kb_id)}"
            self.collection.delete(expr)
            logger.info(f"Milvus 已删除 KB {kb_id} 的向量")
        except Exception:
            logger.exception(f"Milvus 删除 KB {kb_id} 向量失败")
