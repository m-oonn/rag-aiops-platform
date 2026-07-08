import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "RAG-PDF-System"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "data" / "raw"
    PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
    VECTOR_DIR: Path = BASE_DIR / "data" / "vectors"

    SECRET_KEY: str = ""  # 必须从环境变量或 .env 填;留空则启动报错
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # —— CORS / Host 白名单(生产环境安全)——
    # 逗号分隔的显式来源/域名列表。生产环境 main.py 从这里读取,不允许通配 "*"。
    # 例:ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
    ALLOWED_ORIGINS: str = ""
    ALLOWED_HOSTS: str = "*"  # TrustedHostMiddleware 白名单(仅生产启用)

    DASHSCOPE_API_KEY: Optional[str] = None
    # LLM 底座地址(单一事实来源): 将来 Agent 侧的 ChatQwen 从这里读,显式指向国内
    # compatible-mode 站点,避免默认走新加坡站点导致与现有 ChatTongyi 行为漂移。
    # 注意: 现有 ChatTongyi 不接受此参数(走 dashscope 原生 SDK),故仅 Agent 侧消费。
    DASHSCOPE_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "text-embedding-v1"
    EMBEDDING_BATCH_SIZE: int = 20
    EMBEDDING_MAX_BATCH_SIZE: int = 25
    LLM_MODEL: str = "qwen3.7-plus"          # RAG 路径默认模型(百炼免费额度,最新代旗舰)
    # —— Agent 路径模型(新增 ChatOpenAI,走 compatible-mode,可调 Qwen 或阿里托管的 DeepSeek)——
    # 探针(scripts/probe_llm.py)实测结论:
    #   qwen-max / deepseek-v3 均支持 function calling;
    #   deepseek-chat 在阿里不存在(404,那是 DeepSeek 自家平台名);
    #   deepseek-r1 是推理模型,不返回 tool_calls,严禁用于 Agent。
    AGENT_MODEL: str = "qwen-max"             # Agent 主推理模型(qwen-max 通义旗舰,function calling 稳定)
    AGENT_MODEL_SIMPLE: str = "qwen-mt-flash"  # 简单意图(闲聊/分类/路由)降本用,百炼免费额度

    # —— 前端模型选择器可用列表(display_name, model_id) ——
    # 所有模型通过 DashScope compatible-mode 调用,前端下拉框从此读取。
    # ChatTongyi(RAG 路径)仅支持 Qwen 系列;非 Qwen(glm/deepseek)自动走 ChatOpenAI。
    AVAILABLE_MODELS: str = (
        "qwen3.7-plus,qwen-plus-2025-07-28,qwen-mt-flash,deepseek-r1-distill-qwen-7b,glm-5"
    )
    MODEL_DISPLAY_NAMES: str = (
        "Qwen3.7-Plus (旗舰),Qwen-Plus 0728 (均衡),Qwen-MT-Flash (快速),DeepSeek-R1-7B (推理),GLM-5 (智谱)"
    )

    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION_NAME: str = "rag_documents_v2"
    MILVUS_DIMENSION: int = 1536

    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    
    # MinIO Config
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "rag-documents"
    MINIO_SECURE: bool = False

    # SQL Database
    DATABASE_URL: str = "sqlite:///./rag_system.db"
    
    # RAG Config
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K: int = 20
    
    # Rerank Config
    ENABLE_RERANK: bool = True
    RERANK_MODEL: str = "gte-rerank-v2"  # DashScope rerank model (v2 is current)
    RERANK_TOP_N: int = 5
    
    # Multi-hop Config
    ENABLE_MULTI_HOP: bool = True
    MAX_HOP: int = 3

    # —— AIOps Agent Config ——
    # Phase 3 动态分类策略开关
    ENABLE_DYNAMIC_CLASSIFICATION: bool = False

    # Memory Config
    SHORT_TERM_MEMORY_TTL: int = 3600  # 1 hour
    LONG_TERM_MEMORY_COLLECTION: str = "user_memory"
    MEMORY_HISTORY_LIMIT: int = 10

    # —— MCP 工具服务地址(单一事实来源)——
    # 运维 Agent 通过这些 URL 连到独立运行的 MCP 工具进程,只认 URL、不 import 服务端代码
    # (客户端-服务端解耦,这样将来 Mock→真实 只改地址、不动 Agent)。
    # 本地 FastMCP 用 streamable_http;键名(monitor/cls)即 MultiServerMCPClient 里的 server_name。
    # 注意: 端口避开 Windows 保留段(7911-8010,Hyper-V/WSL 动态占用),否则撞 winerror 10013。
    MCP_MONITOR_URL: str = "http://127.0.0.1:8104/mcp"  # 指标服务: query_cpu_metrics / query_memory_metrics
    MCP_CLS_URL: str = "http://127.0.0.1:8103/mcp"      # 日志服务: search_topic_by_service_name / search_log
    MCP_RAG_URL: str = "http://127.0.0.1:8105/mcp"  # 知识库检索: search_knowledge_base / list_knowledge_bases

    @property
    def MCP_SERVERS(self) -> dict:
        """聚合给 MultiServerMCPClient 的配置字典。改地址只动上面几行,这里自动跟随。"""
        return {
            "monitor": {"transport": "streamable_http", "url": self.MCP_MONITOR_URL},
            "cls": {"transport": "streamable_http", "url": self.MCP_CLS_URL},
            "knowledge_base": {"transport": "streamable_http", "url": self.MCP_RAG_URL},
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.PROCESSED_DIR, exist_ok=True)
os.makedirs(settings.VECTOR_DIR, exist_ok=True)
