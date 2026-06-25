from abc import ABC, abstractmethod
from typing import List
from src.models.vector import SearchResult

class BaseRetriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 10) -> List[SearchResult]:
        pass
