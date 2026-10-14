from src.settings import settings

from .base import BaseEmbedding
from .dashscope_embedding import DashScopeEmbeddingService
from .openai_compat_embedding import OpenAICompatEmbeddingService


def get_embedding_service() -> BaseEmbedding:
    """嵌入服务工厂。

    优先: 同时配置了 EMBEDDING_API_BASE + EMBEDDING_API_KEY 时, 使用 OpenAI 兼容嵌入服务
          (2026-10-13 起: 硅基流动免费 BAAI/bge-m3, 因 DashScope 额度耗尽)。
    回退: 未配置时保持原 DashScope 行为(向后兼容)。
    """
    if settings.EMBEDDING_API_BASE and settings.EMBEDDING_API_KEY:
        return OpenAICompatEmbeddingService()
    return DashScopeEmbeddingService()
