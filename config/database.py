from pydantic_settings import BaseSettings
from .settings import settings

class DatabaseSettings(BaseSettings):
    # Milvus Configuration
    MILVUS_HOST: str = settings.MILVUS_HOST
    MILVUS_PORT: int = settings.MILVUS_PORT
    MILVUS_COLLECTION_NAME: str = settings.MILVUS_COLLECTION_NAME
    MILVUS_DIMENSION: int = settings.MILVUS_DIMENSION
    
    # Redis Configuration (Cache & Celery)
    REDIS_URL: str = settings.REDIS_URL

    # Metadata DB (Optional, if using SQL database for metadata)
    # DATABASE_URL: str = "sqlite:///./data/metadata.db"

db_settings = DatabaseSettings()
