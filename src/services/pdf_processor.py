from typing import List
from src.processors.multi_doc_parser import MultiDocParser
from src.processors.text_chunker import TextChunker
from src.embedding import get_embedding_service
from src.database.vector_db import MilvusClient
from src.models.document import Document
from src.models.vector import VectorRecord
from src.utils.logger import logger

class PDFProcessorService:
    def __init__(self):
        self.parser = MultiDocParser()
        self.chunker = TextChunker()
        self.embedding_service = get_embedding_service()
        self.milvus_client = MilvusClient()

    def process_file(self, file_path: str) -> Document:
        try:
            # 1. Parse PDF
            logger.info(f"Parsing file: {file_path}")
            document = self.parser.parse(file_path)
            if document.status == "failed":
                raise Exception(f"Failed to parse document: {document.error_message}")

            # 2. Chunk Text
            logger.info(f"Chunking document: {document.id}")
            chunks = self.chunker.split_document(document)
            document.chunks_count = len(chunks)
            
            if not chunks:
                logger.warning("No chunks created from document.")
                return document

            # 3. Generate Embeddings
            logger.info(f"Generating embeddings for {len(chunks)} chunks")
            texts = [chunk.text for chunk in chunks]
            embeddings = self.embedding_service.embed_documents(texts)
            
            if len(embeddings) != len(chunks):
                raise Exception("Mismatch between chunks and embeddings count")

            # 4. Prepare Vector Records
            vector_records = []
            for i, chunk in enumerate(chunks):
                chunk.embedding = embeddings[i]
                
                # Prepare metadata for Milvus
                metadata = chunk.metadata.model_dump()
                metadata["text"] = chunk.text # Store text in metadata for retrieval
                
                vector_records.append(VectorRecord(
                    id=chunk.id,
                    values=chunk.embedding,
                    metadata=metadata
                ))

            # 5. Store in Milvus
            logger.info("Storing vectors in Milvus")
            self.milvus_client.insert(vector_records)
            
            document.status = "completed"
            logger.info(f"Document processed successfully: {document.id}")
            return document

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            raise
