from typing import List, Optional
from src.retrieval.base_retriever import BaseRetriever
from src.database.vector_db import MilvusClient
from src.embedding import get_embedding_service
from src.models.vector import SearchResult

class VectorRetriever(BaseRetriever):
    def __init__(self):
        self.milvus_client = MilvusClient()
        self.embedding_service = get_embedding_service()

    def retrieve(self, query: str, top_k: int = 10, kb_id: Optional[int] = None, kb_ids: Optional[List[int]] = None) -> List[SearchResult]:
        # 1. Embed query
        query_vector = self.embedding_service.embed_query(query)
        if not query_vector:
            return []
            
        # 2. Search in Milvus
        expr = None
        if kb_ids:
            # Milvus expression for IN list
            # kb_ids_str = ",".join(map(str, kb_ids))
            # expr = f"kb_id in [{kb_ids_str}]"
            # NOTE: Milvus scalar filtering syntax depends on version. 
            # PyMilvus usually supports `field in [1,2]`
            expr = f"kb_id in {kb_ids}"
        elif kb_id is not None:
            expr = f"kb_id == {kb_id}"
            
        results = self.milvus_client.search(query_vector, top_k=top_k, expr=expr)
        
        return results
