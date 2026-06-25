from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from src.models.chunk import Chunk, ChunkMetadata
from src.models.document import Document
import uuid
import re

class TextChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""]
        )

    def split_document(self, document: Document) -> List[Chunk]:
        """
        Split a document into chunks.
        """
        if not document.content:
            return []
            
        # We can implement more advanced splitting here (e.g., semantic)
        # For now, we use RecursiveCharacterTextSplitter
        
        # Note: The document content currently contains "[Page X]" markers. 
        # A better approach would be to split by page first if we want accurate page numbers in metadata.
        # However, for simplicity and cross-page context, we split the full text.
        # To get accurate page numbers, we would need to pass the list of pages to this function instead of full string.
        
        # Let's try a regex split to recover pages if possible, or just treat as one big text
        # Assuming the content format from PDFParser: "[Page {p}] {t}"
        
        chunks = []
        
        # Simple splitting of the whole text
        raw_chunks = self.splitter.split_text(document.content)
        
        current_page = 1
        
        for i, text in enumerate(raw_chunks):
            # Try to extract page number from text if present (heuristic)
            # This is not perfect as a chunk might span multiple pages
            # We look for [Page X] or [Slide X] markers.
            page_matches = re.findall(r'\[(?:Page|Slide) (\d+)\]', text)
            if page_matches:
                current_page = int(page_matches[0])
            
            chunk_id = f"doc_{document.id}_chunk_{i}"
            
            metadata = ChunkMetadata(
                doc_id=document.id,
                page=current_page,
                chunk_index=i,
                source=document.metadata.source
            )
            
            chunks.append(Chunk(
                id=chunk_id,
                text=text,
                metadata=metadata,
                doc_id=document.id
            ))
            
        return chunks
        
    def split_text_with_pages(self, pages: List[tuple[int, str]], doc_id: str, source: str) -> List[Chunk]:
        """
        Split text while preserving page info.
        pages: List of (page_num, text)
        """
        chunks = []
        global_index = 0
        
        for page_num, text in pages:
            page_chunks = self.splitter.split_text(text)
            for text_chunk in page_chunks:
                chunk_id = f"doc_{doc_id}_chunk_{global_index}"
                metadata = ChunkMetadata(
                    doc_id=doc_id,
                    page=page_num,
                    chunk_index=global_index,
                    source=source
                )
                chunks.append(Chunk(
                    id=chunk_id,
                    text=text_chunk,
                    metadata=metadata,
                    doc_id=doc_id
                ))
                global_index += 1
                
        return chunks
