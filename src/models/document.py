from typing import List, Dict, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

class DocumentMetadata(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    creation_date: Optional[str] = None
    page_count: Optional[int] = None
    source: Optional[str] = None
    file_type: str = "pdf"
    
class Document(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    content: Optional[str] = None  # Full text content if needed, but usually we split into chunks
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    chunks_count: int = 0
    status: str = "pending" # pending, processing, completed, failed
    error_message: Optional[str] = None
