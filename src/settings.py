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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 安全最佳实践: 8 小时，平衡可用性与安全

    # —— CORS / Host 白名单(生产环境安全)——
    # 逗号分隔的显式来源/域名列表。生产环境 main.py 从这里读取,不允许通配 "*".
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
    LLM_MODEL: str = "glm-5.3"  # RAG 路径默认模型(2026-09-23 复测: qwen3.8-max-0902 已耗尽,切 glm-5.3)
    # —— Agent 路径模型(新增 ChatOpenAI,走 compatible-mode,可调 Qwen 或阿里托管的 DeepSeek)——
    # 免费额度探针结论(2026-09-10, 脚本 scripts/_tmp_probe_new_models.py / probe_more_models.py):
    #   ⚠️ 免费额度纪律: 只使用有免费额度的模型;额度耗尽(403 FreeTierOnly)即重新探测,
    #      绝不切换计费模型。探测用最小请求("你好"),403 不计费。
    #   2026-09-10 实测免费可用(对话 OK):
    #     - qwen3.8-max / qwen3.8-flash / qwen3.8-27b (宽松 function calling OK)
    #     - qwen3.7-flash / kimi-k3 / glm-5.2 (tool_choice=required OK, Agent 首选)
    #   2026-09-14 复测: qwen3.7-flash 免费额度已耗尽(403 FreeTierOnly), 切 qwen3.8-flash;
    #   同日盲测后 qwen3.8-flash 亦耗尽, 再切 qwen3.8-max(免费)。
    #   2026-09-15 复测: qwen3.8-max/qwen3.8-flash/glm-5.2 全部耗尽(403),
    #     仅 qwen3.8-27b / kimi-k3 可用, 切 qwen3.8-27b(对话+function calling OK)。
    #   2026-09-15 全量重跑后 qwen3.8-27b 亦耗尽(403), 仅剩 kimi-k3 可用, 再切 kimi-k3。
    #   2026-09-16 复测: kimi-k3 / qwen3.8-27b / max / flash / glm-5.2 全部 403 耗尽。
    #   2026-09-16 起「无可用免费模型」阻塞真实 LLM 任务(A/B 补测 / 707 复验 / 12 场景复测)。
    #   2026-09-23 全量探测(scripts/_tmp_probe_all.py, compatible-mode /models + 原生 OpenAPI):
    #     发现: 带日期后缀的版本型号是**独立免费额度主体**,主型号耗尽但日期版仍免费可用,
    #     且全部支持 function calling(实测 FC-OK):
    #       - qwen3.8-max-0902          (qwen3.8-max 系日期版,行为最接近已验证配置 → 主推理)
    #       - qwen3.7-flash-2026-07-15  (flash 档,更快更省 → AGENT_MODEL_SIMPLE/降本)
    #       - glm-5.3 / glm-5.3-prime / glm-5.2-fast-preview
    #       - deepseek-v4.1-flash / deepseek-v4-flash-0731 / deepseek-v4-pro-0813
    #       - qwen3.8-2.4t-a95b / qwen3.8-omni-flash / qwen3.5-omni-plus 等
    AGENT_MODEL: str = "glm-5.3"        # Agent 主推理模型(2026-09-23 复测: qwen3.8-max-0902 已 403 耗尽,切 glm-5.3; function calling OK)
    AGENT_MODEL_SIMPLE: str = "qwen3.7-flash-2026-07-15"  # 简单意图(闲聊/分类/路由)降本用,flash 档更快

    # —— 证据裁判 LLM（动态分类策略用）——
    # 开启后 EvidenceJudge 用 LLM 语义判断观测对假设的支持/矛盾关系，
    # 可理解同义词、否定句与隐含证据（修复对抗测试 synonym_blind / negation_trap）。
    # 默认关闭：保证单测确定性；开启后 LLM 不可用/失败会自动降级到规则关键词。
    ENABLE_LLM_EVIDENCE_JUDGE: bool = False
    EVIDENCE_LLM_MODEL: str = "qwen3.7-flash-2026-07-15"  # 证据裁判用模型(2026-09-23; 裁判任务质量要求低于主推理, 用 flash 档降本)

    # —— 前端模型选择器可用列表(display_name, model_id) ——
    # 只列 2026-09-23 免费额度实测可用的模型(日期版为主;非 Qwen 系自动走 ChatOpenAI)。
    # 额度耗尽时重新运行 scripts/probe_available_models.py 探测(含 compatible-mode /models 全量拉取),
    # 并把新可用模型更新到这里(严禁加入计费模型)。
    AVAILABLE_MODELS: str = (
        "glm-5.3,qwen3.7-flash-2026-07-15,deepseek-v4.1-flash"
    )
    MODEL_DISPLAY_NAMES: str = (
        "GLM-5.3 (免费),Qwen3.7-Flash-0715 (免费),DeepSeek-V4.1-Flash (免费)"
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

    # —— 诊断经验注入(AIOps planner) ——
    # 2026-09-16 知识噪声修复: 检索源白名单 + 相关性阈值。
    #   EXPERIENCE_KB_IDS: 逗号分隔的 KB id, 仅检索指定的运维案例库(空=全部知识库)。
    #     背景: 知识库混有功能测试上传的"运维排查手册"(kb 1/2/3/17), 其内容
    #     ("CPU 高→应用死循环/GC 停顿")与诊断根因相悖, 污染 planner 规划路径(202 盲测误判)。
    #   EXPERIENCE_MIN_SCORE: 经验 chunk 相关性下限(余弦相似度), 低于阈值不注入。
    EXPERIENCE_KB_IDS: str = ""
    EXPERIENCE_MIN_SCORE: float = 0.30
    
    # Multi-hop Config
    ENABLE_MULTI_HOP: bool = True
    MAX_HOP: int = 3

    # —— AIOps Agent Config ——
    # Phase 3 动态分类策略开关
    ENABLE_DYNAMIC_CLASSIFICATION: bool = False

    # —— 多智能体协同（Supervisor / HITL / 并行观测）——
    # Supervisor 统一入口：注册 /supervisor/chat 端点，前端显示"统一入口"开关
    ENABLE_SUPERVISOR: bool = False
    # 人在回路（HITL）：诊断结论在 respond 前中断，等待人工审批后恢复
    ENABLE_HITL: bool = False
    # pending_review 挂起超时（秒），超时自动落库为"已出草稿、未人工确认"
    HITL_TTL_SECONDS: int = 600
    # 并行观测采集：executor 对可并行的观测步骤并发执行（指标/日志）
    ENABLE_PARALLEL_OBSERVATION: bool = False

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

    # —— Monitor MCP 生产化后端(Mock→Prometheus 双轨,见 docs/MCP生产化改造方案.md)——
    # MONITOR_BACKEND: "mock"(默认,演示剧本) 或 "prometheus"(真实监控查询)
    # PROMETHEUS_URL 配置后且 MONITOR_BACKEND=prometheus 时,指标查询走 Prometheus HTTP API;
    # 工具名/参数/返回结构不变,Agent 侧零改动;Prometheus 不可达时回退 mock。
    MONITOR_BACKEND: str = "mock"
    PROMETHEUS_URL: str = ""
    # PromQL 模板,{service} 为服务名占位;默认适配 node_exporter 指标
    PROMETHEUS_CPU_PROMQL: str = (
        '100 - avg(rate(node_cpu_seconds_total{mode="idle", instance=~"{service}.*"}[5m])) * 100'
    )
    PROMETHEUS_MEMORY_PROMQL: str = (
        '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'
    )
    PROMETHEUS_TIMEOUT_SECONDS: float = 5.0

    # —— RAG 知识源采集(connectors,见 docs/MCP生产化改造方案.md §5)——
    # MinIO 知识源: 扫描该桶内 .md/.txt 文档注入知识库(与文档备份桶 rag-documents 可不同)
    MINIO_SOURCE_BUCKET: str = "rag-documents"

    # —— CLS MCP 生产化后端(Mock→Elasticsearch 双轨,见 docs/MCP生产化改造方案.md §4.2)——
    # CLS_BACKEND: "mock"(默认,演示剧本) 或 "elasticsearch"(真实日志平台)
    # 配置 CLS_ES_URL 且 CLS_BACKEND=elasticsearch 时,日志查询走 ES;不可达回退 mock。
    CLS_BACKEND: str = "mock"
    CLS_ES_URL: str = ""
    # 服务名→日志索引模式;search_topic 用该模式匹配索引,search_log 查具体索引
    CLS_INDEX_PATTERN: str = "{service}-logs-*"
    # 日志文档字段名(真实平台字段映射到 timestamp/level/message)
    CLS_LOG_TIMESTAMP_FIELD: str = "@timestamp"
    CLS_LOG_LEVEL_FIELD: str = "level"
    CLS_LOG_MESSAGE_FIELD: str = "message"
    CLS_TIMEOUT_SECONDS: float = 5.0

    # —— 服务名别名表(生产关键: 口头名↔监控前缀↔日志索引前缀,见 docs/MCP生产化改造方案.md §3)——
    # JSON 字符串: {"口头服务名": {"monitor": "监控instance前缀", "logs": "日志索引前缀"}}
    # 双轨真实路径查询前先经 service_map.resolve_service 归一化并展开候选,
    # 解决"用户说订单服务,监控叫 order-svc,索引叫 order-service-logs-*"导致的检索落空。
    SERVICE_ALIASES: str = "{}"

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
