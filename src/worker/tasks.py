from typing import List, Dict, Any
import traceback
from sqlalchemy.orm import Session
from src.worker.celery_app import celery_app
from src.database.sql_session import SessionLocal
from src.database.models import KnowledgeDocument, DocumentChunk, KnowledgeBase
from src.processors.multi_doc_parser import MultiDocParser
from src.processors.text_chunker import TextChunker
from src.embedding import get_embedding_service
from src.database.vector_db import MilvusClient
from src.models.vector import VectorRecord
from src.utils.logger import logger
import os

@celery_app.task(bind=True, name="process_document_task")
def process_document_task(self, doc_id: int):
    """
    Celery task to process a document asynchronously.
    """
    logger.info(f"Starting processing for document ID: {doc_id}")
    
    # Helper to update task state
    def update_progress(state, progress, message):
        self.update_state(state=state, meta={'progress': progress, 'message': message})

    db = SessionLocal()
    try:
        # 1. Fetch Document
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        if not doc:
            logger.error(f"Document {doc_id} not found in DB")
            return "Document not found"
        
        # If status is already completed, skip (or force re-process if needed)
        # Assuming status 0=Pending/Uploading, 1=Processing, 2=Completed, 3=Failed
        
        # Update status to Processing (1)
        doc.status = 1 
        doc.error_msg = None
        db.commit()
        db.refresh(doc) # Refresh to get latest state
        
        update_progress('PROCESSING', 10, 'Started parsing')

        # 2. Parse File
        if not os.path.exists(doc.file_path):
            # Detailed logging for debugging
            logger.error(f"File not found: {doc.file_path}")
            try:
                dir_path = os.path.dirname(doc.file_path)
                if os.path.exists(dir_path):
                    files_in_dir = os.listdir(dir_path)
                    logger.error(f"Directory {dir_path} exists. Files: {files_in_dir}")
                else:
                    logger.error(f"Directory {dir_path} does not exist.")
                logger.error(f"Current Working Directory: {os.getcwd()}")
            except Exception as e:
                logger.error(f"Error inspecting directory: {e}")
                
            raise FileNotFoundError(f"File not found: {doc.file_path}")

        parser = MultiDocParser()
        # Parse returns a Pydantic Document object
        parsed_doc = parser.parse(doc.file_path)
        
        if hasattr(parsed_doc, 'status') and parsed_doc.status == "failed":
            raise Exception(f"Parsing failed: {getattr(parsed_doc, 'error_message', 'Unknown error')}")
            
        update_progress('PROCESSING', 30, 'Parsing completed, chunking...')
        
        # 3. Chunk Text
        # Determine chunking strategy
        chunk_size = 1000
        chunk_overlap = 200
        
        # Priority: Document Config > KB Config > Default
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        
        config = doc.chunking_config or (kb.chunking_config if kb else {})
        # Ensure config is a dict (it might be None or empty)
        if not isinstance(config, dict):
            config = {}
            
        chunk_size = int(config.get("chunk_size", 1000))
        chunk_overlap = int(config.get("chunk_overlap", 200))
        
        chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        # split_document returns List[Chunk] (Pydantic models)
        chunks = chunker.split_document(parsed_doc)
        
        doc.chunk_count = len(chunks)
        db.commit()
        
        if not chunks:
             logger.warning(f"No chunks created for doc {doc_id}")
             # Treat as completed but empty
             doc.status = 2
             db.commit()
             return "Completed (No content)"
        
        update_progress('PROCESSING', 50, f'Generated {len(chunks)} chunks, embedding...')

        # 4. Generate Embeddings
        embedding_service = get_embedding_service()
        texts = [chunk.text for chunk in chunks]
        embeddings = embedding_service.embed_documents(texts)
        
        if len(embeddings) != len(chunks):
            raise Exception(f"Mismatch between chunks ({len(chunks)}) and embeddings ({len(embeddings)}) count")
            
        update_progress('PROCESSING', 70, 'Storing chunks and vectors...')

        # 5. Prepare Vector Records & Save to SQL
        milvus_client = MilvusClient()
        vector_records = []
        
        # Clear existing chunks for this doc in SQL if any (for retry scenarios)
        db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).delete()
        
        # Also need to clear vectors in Milvus? 
        # Milvus doesn't support delete by field easily without ID. 
        # If we reuse IDs, upsert might work, but Milvus insert doesn't upsert by default in some versions.
        # But we generate new IDs usually? 
        # Let's assume we just insert new ones for now. 
        # Ideally we should delete old vectors associated with this doc_id first.
        # milvus_client.delete_by_doc_id(doc.id) # Need to implement this in MilvusClient

        for i, chunk in enumerate(chunks):
            # Save to SQL
            db_chunk = DocumentChunk(
                chunk_uid=chunk.id,
                doc_id=doc.id,
                content=chunk.text,
                page_num=chunk.metadata.page if chunk.metadata.page is not None else 0, # Fix: ensure page is not None
                vector_id=chunk.id 
            )
            db.add(db_chunk)
            
            # Prepare for Milvus
            # We need to convert Pydantic model to dict for metadata
            metadata = chunk.metadata.model_dump()
            # Add extra fields needed for retrieval filtering
            metadata["doc_id"] = doc.id
            metadata["kb_id"] = doc.kb_id
            metadata["filename"] = doc.filename
            metadata["text"] = chunk.text # Ensure text is available for retrieval
            
            vector_records.append(VectorRecord(
                id=chunk.id,
                values=embeddings[i],
                metadata=metadata
            ))
            
        db.commit()
        
        # 6. Store in Milvus
        milvus_client.insert(vector_records)
        
        # 7. Update Final Status
        doc.status = 2 # Completed
        db.commit()
        
        update_progress('SUCCESS', 100, 'Processing completed successfully')
        logger.info(f"Document {doc_id} processed successfully")
        return "Success"

    except Exception as e:
        logger.error(f"Error processing document {doc_id}: {e}")
        traceback.print_exc()
        
        # Re-query doc to avoid detached instance issues if rollback happened
        db.rollback()
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        if doc:
            doc.status = 3 # Failed
            doc.error_msg = str(e)
            db.commit()
        
        update_progress('FAILURE', 100, f'Failed: {str(e)}')
        # We don't raise exception here to avoid Celery retrying indefinitely if we don't want it to.
        # But if we want retry, we should raise. 
        # Let's not raise for now, as we handled the error state in DB.
        return f"Failed: {str(e)}"
        
    finally:
        db.close()
