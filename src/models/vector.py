from typing import List, Dict, Optional, Any
from pydantic import BaseModel

class VectorRecord(BaseModel):
    id: str
    values: List[float]
    metadata: Dict[str, Any]

class SearchResult(BaseModel):
    id: str
    score: float
    text: str
    metadata: Dict[str, Any]
    
class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    rerank: bool = False
    filters: Optional[Dict[str, Any]] = None
