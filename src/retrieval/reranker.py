from typing import List, Any
import dashscope
from http import HTTPStatus
from src.settings import settings
from src.utils.logger import logger
from src.models.vector import SearchResult

class DashScopeReranker:
    def __init__(self):
        self.api_key = settings.DASHSCOPE_API_KEY
        self.model = settings.RERANK_MODEL
        self.top_n = settings.RERANK_TOP_N

    def rerank(self, query: str, documents: List[SearchResult]) -> List[SearchResult]:
        if not documents:
            return []
            
        if not settings.ENABLE_RERANK:
            return documents[:self.top_n]

        try:
            # Prepare documents for reranking
            doc_texts = [doc.text for doc in documents]
            
            # Call DashScope Rerank API
            # Note: DashScope rerank API usage might vary depending on version
            # Here we use the common pattern for dashscope.TextReRank
            from dashscope import TextReRank
            
            resp = TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_texts,
                top_n=self.top_n,
                api_key=self.api_key
            )

            if resp.status_code == HTTPStatus.OK:
                reranked_results = []
                for item in resp.output.results:
                    idx = item.index
                    score = item.relevance_score
                    original_doc = documents[idx]
                    # Update score with rerank score
                    original_doc.score = score
                    reranked_results.append(original_doc)
                return reranked_results
            else:
                logger.error(f"DashScope Rerank Error: {resp.code} - {resp.message}")
                # Fallback to original results
                return documents[:self.top_n]
                
        except Exception as e:
            logger.error(f"Rerank failed: {e}")
            return documents[:self.top_n]
