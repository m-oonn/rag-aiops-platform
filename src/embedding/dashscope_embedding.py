from typing import List
from http import HTTPStatus
import dashscope
from dashscope import TextEmbedding
from src.settings import settings
from src.utils.logger import logger
from src.embedding.base import BaseEmbedding

class DashScopeEmbeddingService(BaseEmbedding):
    def __init__(self):
        self.api_key = settings.DASHSCOPE_API_KEY
        if not self.api_key:
            logger.warning("DashScope API Key not found. Embeddings will fail.")
        dashscope.api_key = self.api_key
        self.model = settings.EMBEDDING_MODEL

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        
        batch_size = min(settings.EMBEDDING_BATCH_SIZE, settings.EMBEDDING_MAX_BATCH_SIZE)
        embeddings: List[List[float]] = []

        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                resp = TextEmbedding.call(
                    model=self.model,
                    input=batch,
                    api_key=self.api_key
                )
                
                if resp.status_code == HTTPStatus.OK:
                    batch_embeddings = [item["embedding"] for item in resp.output["embeddings"]]
                    embeddings.extend(batch_embeddings)
                else:
                    logger.error(f"DashScope Embedding Error: {resp.code} - {resp.message}")
                    raise Exception(f"DashScope Embedding Error: {resp.message}")
                
            return embeddings
        except Exception as e:
            logger.error(f"Embedding failed: {str(e)}")
            raise

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query.
        """
        embeddings = self.embed_documents([text])
        if embeddings:
            return embeddings[0]
        return []
