from typing import List, Dict, Any, Optional
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
)
from src.settings import settings
from src.utils.logger import logger
from src.models.vector import VectorRecord, SearchResult

class MilvusClient:
    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.collection_name = settings.MILVUS_COLLECTION_NAME
        self.dim = settings.MILVUS_DIMENSION
        self.collection = None
        self._connect()
        self._init_collection()

    def _connect(self):
        import time
        max_retries = 10
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                # Disconnect existing connection if any
                if connections.has_connection("default"):
                    connections.disconnect("default")
                    
                logger.info(f"Connecting to Milvus at {self.host}:{self.port} (Attempt {attempt + 1}/{max_retries})")
                connections.connect("default", host=self.host, port=self.port, timeout=10)
                logger.info(f"Connected to Milvus at {self.host}:{self.port}")
                return
            except Exception as e:
                logger.warning(f"Failed to connect to Milvus (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    logger.error("Max retries reached. Could not connect to Milvus.")
                    raise e

    def _init_collection(self):
        try:
            if not utility.has_collection(self.collection_name):
                logger.info(f"Creating collection: {self.collection_name}")
                fields = [
                    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=512, is_primary=True),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
                    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="metadata", dtype=DataType.JSON), 
                    FieldSchema(name="kb_id", dtype=DataType.INT64), # Add kb_id for filtering
                ]
                schema = CollectionSchema(fields, "RAG Document Collection")
                self.collection = Collection(self.collection_name, schema)
                
                # Create Index
                index_params = {
                    "metric_type": "L2",
                    "index_type": "IVF_FLAT",
                    "params": {"nlist": 1024}
                }
                self.collection.create_index(field_name="embedding", index_params=index_params)
                
                # Create scalar index for kb_id for faster filtering
                self.collection.create_index(field_name="kb_id", index_name="kb_id_index")
            else:
                self.collection = Collection(self.collection_name)
                # Check if kb_id exists in schema
                self.has_kb_id = any(field.name == "kb_id" for field in self.collection.schema.fields)
                if not self.has_kb_id:
                    logger.warning("Current collection schema does not have 'kb_id' field. Filtering by kb_id will be disabled.")
                else:
                    self.has_kb_id = True
                
            self.collection.load()
            if not hasattr(self, "has_kb_id"): # In case it was just created
                 self.has_kb_id = True

        except Exception as e:
            logger.error(f"Failed to initialize collection: {e}")
            raise

    def insert(self, records: List[VectorRecord]):
        if not records:
            return
            
        try:
            ids = [r.id for r in records]
            embeddings = [r.values for r in records]
            texts = [r.metadata.get("text", "") for r in records]
            metadatas = [r.metadata for r in records]
            
            data = [ids, embeddings, texts, metadatas]
            
            if self.has_kb_id:
                # Extract kb_id from metadata, default to 0 if not present
                kb_ids = [int(r.metadata.get("kb_id", 0)) for r in records]
                data.append(kb_ids)
            
            self.collection.insert(data)
            logger.info(f"Inserted {len(records)} records into Milvus")
        except Exception as e:
            logger.error(f"Failed to insert into Milvus: {e}")
            raise

    def search(self, vector: List[float], top_k: int = 10, expr: str = None) -> List[SearchResult]:
        try:
            search_params = {
                "metric_type": "L2", 
                "params": {"nprobe": 10}
            }
            
            output_fields = ["text", "metadata"]
            if self.has_kb_id:
                output_fields.append("kb_id")
            
            # If kb_id is not in schema but requested in expr, we should handle it
            if not self.has_kb_id and expr and "kb_id" in expr:
                 logger.warning("Filtering by 'kb_id' requested but field does not exist in schema. Ignoring filter. Results may include documents from other knowledge bases.")
                 expr = None

            results = self.collection.search(
                data=[vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=output_fields
            )
            
            search_results = []
            for hits in results:
                for hit in hits:
                    search_results.append(SearchResult(
                        id=hit.id,
                        score=hit.score,
                        text=hit.entity.get("text"),
                        metadata=hit.entity.get("metadata")
                    ))
                    
            return search_results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
