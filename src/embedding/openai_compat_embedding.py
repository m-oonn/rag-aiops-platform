"""OpenAI 兼容格式的嵌入服务(如硅基流动 SiliconFlow)。

背景(2026-10-13): DashScope 嵌入额度耗尽(免费额度尽 + 付费模型欠费), 原
DashScopeEmbeddingService 不可用; 切换到硅基流动免费嵌入 BAAI/bge-m3(1024 维,
与 MILVUS_DIMENSION 保持一致), 接口为 OpenAI /v1/embeddings 规范。

启用条件: .env 同时配置 EMBEDDING_API_BASE + EMBEDDING_API_KEY(见 __init__.py 工厂);
未配置时回退 DashScope, 保持向后兼容。
"""

from typing import List

import requests

from src.settings import settings
from src.utils.logger import logger
from src.embedding.base import BaseEmbedding


class OpenAICompatEmbeddingService(BaseEmbedding):
    def __init__(self):
        self.api_base = (settings.EMBEDDING_API_BASE or "").rstrip("/")
        self.api_key = settings.EMBEDDING_API_KEY
        self.model = settings.EMBEDDING_MODEL
        if not self.api_base or not self.api_key:
            logger.warning("EMBEDDING_API_BASE / EMBEDDING_API_KEY 未配置, 嵌入调用将失败")

    def _call(self, texts: List[str]) -> List[List[float]]:
        """调用一次 /embeddings(OpenAI 规范), 返回与输入顺序一致的向量列表。"""
        resp = requests.post(
            f"{self.api_base}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        if resp.status_code != 200:
            raise Exception(f"Embedding API Error: HTTP {resp.status_code} - {resp.text[:200]}")
        data = resp.json()
        # OpenAI 格式: {"data": [{"embedding": [...], "index": 0}, ...], "usage": {...}}
        items = sorted(data["data"], key=lambda x: x.get("index", 0))
        return [it["embedding"] for it in items]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        batch_size = min(settings.EMBEDDING_BATCH_SIZE, settings.EMBEDDING_MAX_BATCH_SIZE)
        embeddings: List[List[float]] = []

        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                embeddings.extend(self._call(batch))
            return embeddings
        except Exception as e:
            logger.error(f"Embedding failed: {str(e)}")
            raise

    def embed_query(self, text: str) -> List[float]:
        embeddings = self.embed_documents([text])
        return embeddings[0] if embeddings else []
