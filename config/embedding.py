from typing import Dict, Any
from pydantic_settings import BaseSettings
from .settings import settings

class EmbeddingSettings(BaseSettings):
    # Provider: "openai", "dashscope", "huggingface"
    PROVIDER: str = "dashscope"
    
    # Model Names
    # Qwen/Dashscope: text-embedding-v1, text-embedding-v2
    MODEL_NAME: str = settings.EMBEDDING_MODEL
    
    # Dimensions
    DIMENSION: int = 1536
    
    # Batch Size
    BATCH_SIZE: int = 10
    
    # API Key (loaded from settings/env)
    API_KEY: str | None = settings.DASHSCOPE_API_KEY

embedding_settings = EmbeddingSettings()
