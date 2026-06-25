from .base import BaseEmbedding
from .dashscope_embedding import DashScopeEmbeddingService

def get_embedding_service() -> BaseEmbedding:
    # Factory function to get the configured embedding service
    # Currently defaults to DashScope
    return DashScopeEmbeddingService()
