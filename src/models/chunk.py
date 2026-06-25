from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class ChunkMetadata(BaseModel):
    doc_id: str
    page: int
    section: Optional[str] = None
    chunk_index: int
    source: Optional[str] = None
    # Add other relevant metadata here

class Chunk(BaseModel):
    id: str  # Unique ID for the chunk (e.g., doc_id_chunk_index)
    text: str
    metadata: ChunkMetadata
    embedding: Optional[List[float]] = None
    doc_id: str
    
    @property
    def vector_id(self) -> str:
        return self.id
