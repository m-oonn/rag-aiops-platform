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

    # —— LLM 供应商切换(2026-10-09 新增,支持 DeepSeek 官方 API)——
    # 目的: 把"换模型供应商"收敛成纯配置切换,代码零改动(.env 改 2 行即可)。
    #   LLM_API_BASE: 显式指定时优先于各供应商默认地址(DASHSCOPE_API_BASE / deepseek 默认)
    #   LLM_API_KEY : 显式指定时优先;否则依次回退 DEEPSEEK_API_KEY → DASHSCOPE_API_KEY
    # 兼容性: 两者都不设置时,行为与旧版完全一致(走 DASHSCOPE_API_BASE + DASHSCOPE_API_KEY)。
    LLM_API_BASE: Optional[str] = None     # 例: "https://api.deepseek.com"
    LLM_API_KEY: Optional[str] = None      # DeepSeek 官方 API Key(sk-xxx)
    DEEPSEEK_API_KEY: Optional[str] = None # 备选变量名(给只认这个名字的场景)

    # 2026-10-10 切换: text-embedding-v1 已欠费(Arrearage),换免费的 qwen3.7-text-embedding(1024维)。
    # 换模型必须同步 MILVUS_DIMENSION 与 index_runbooks.py 的维度校验。
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    EMBEDDING_BATCH_SIZE: int = 20
    EMBEDDING_MAX_BATCH_SIZE: int = 25
    # OpenAI 兼容嵌入服务(2026-10-13 新增; 如硅基流动 https://api.siliconflow.cn/v1):
    # 与 EMBEDDING_API_KEY 同时配置时优先启用, 否则回退 DashScope(见 src/embedding/__init__.py)
    EMBEDDING_API_BASE: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None
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

    # —— Agent 是否关闭模型 thinking 模式(2026-10-10 新增)——
    # 背景: DeepSeek thinking 模型拒绝"强制 tool_choice",导致 with_structured_output
    # (method="function_calling") 400 报错并降级成正则抠 JSON。实测关闭 thinking 后
    # 原生强制工具调用直接可用(见 scripts/_probe_structured_fix2.py 结论)。
    # 仅对支持的供应商(DeepSeek)生效;换回保留推理能力的模型时置 False 即可。
    AGENT_DISABLE_THINKING: bool = True

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
    MILVUS_DIMENSION: int = 1024  # 2026-10-10: 随 EMBEDDING_MODEL 切 qwen3.7-text-embedding(1024维)

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
    # MCP 知识库结果低于该分数时视为无可靠匹配，避免把无关资料硬套进诊断。
    RAG_MIN_SCORE: float = 0.10
    
    # Rerank Config
    ENABLE_RERANK: bool = True
    RERANK_MODEL: str = "qwen3.7-text-rerank"  # 2026-10-10: gte-rerank-v2 已欠费,换免费的 qwen3.7-text-rerank
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

    # —— 工具调用守卫层（B1，src/agent/aiops/tool_guards.py）——
    # 逗号分隔的守卫停用列表（空=全开）。论文消融/定位用。
    # 可选值: topic_alignment / generic_filter / metric_time_anchor / change_time_anchor
    DISABLED_TOOL_GUARDS: str = ""

    # —— LLM 调用统一重试（B5，src/agent/aiops_llm.py）——
    # 瞬态错误(429/5xx/连接超时)指数退避重试; False=单次调用(旧行为,回归兼容)
    ENABLE_LLM_RETRY: bool = True
    LLM_RETRY_MAX_ATTEMPTS: int = 3

    # —— 上下文压缩（B2a，src/agent/aiops/compaction.py）——
    # True 时: 超过阈值步数的诊断历史改走"旧步骤摘要+近步骤详情"; False=旧口径(最近5步×150字)
    ENABLE_CONTEXT_COMPACTION: bool = False

    # —— 技能路由（B2b，src/agent/aiops/skills.py）——
    # True 时: planner 按征兆懒加载 Top-2 技能卡; False=全量注入 9 卡(旧行为)
    ENABLE_SKILL_ROUTING: bool = False

    # —— 步级快照（B3，aiops_step_snapshots 表）——
    # True 时: 每步节点输出摘要落库（回放/审计）; False=不写（默认,零开销）
    ENABLE_STEP_SNAPSHOTS: bool = False

    # —— 证据裁判采信原始工具返回（2026-10-12 命中率根因修复）——
    # 背景: executor 存进 past_steps 的是 LLM 写的自然语言总结, 原始日志里的鉴别
    #       关键词(kubelet/evicted/OOMKilled、dial tcp/connection refused)被转述稀释成
    #       中文通用词, 规则裁判关键词匹配失效 → 全倒向"外部依赖故障"(实测命中率 25%)。
    # True 时: 证据裁判优先采信 state.raw_evidence(未加工的原始工具返回),
    #          转述文本仅作补充; False=沿用旧行为(只吃转述, 回归兼容)。
    ENABLE_RAW_EVIDENCE_FOR_JUDGE: bool = False

    # —— 信念 softmax 温度（置信度校准，2026-10-12）——
    # 竞争归一时 logits 除以该温度：1.0=旧行为(不校准)；>1=平滑，抑制"证据真空下
    # 7 条相近先验被 softmax 放大成 99% 虚高置信度"（实测"0 证据却 99%"）。
    # 仅在 ENABLE_CONFIDENCE_CALIBRATION 开启时生效。
    ENABLE_CONFIDENCE_CALIBRATION: bool = False
    BELIEF_SOFTMAX_TEMPERATURE: float = 3.0

    # —— 论文消融开关（仅实验用；生产保持全 False）——
    # 对齐开题报告"消融分析：逐项关闭 假设保护 / 证据门控 / 降级标注"。
    # 每个开关只关闭**一个**机制，用于量化该机制对诊断准确率与诚实性的贡献；
    # 关闭只影响该机制，不改变其余链路，保证消融结果可归因。
    #   假设保护: 弱信号保护(_incubate_weak_signals) + 深度回溯复活(_maybe_reactivate_hypotheses)
    #   证据门控: 证据充分性门控(_evidence_sufficiency_problem) → 关后不再把结论降级为"推测"
    #   降级标注: 报告的证据来源小节与降级来源 caveat → 关后不再披露来源降级/缺席
    ABLATION_DISABLE_HYPOTHESIS_PROTECTION: bool = False
    ABLATION_DISABLE_EVIDENCE_GATE: bool = False
    ABLATION_DISABLE_DEGRADATION_LABEL: bool = False

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
    MCP_CHANGE_URL: str = "http://127.0.0.1:8106/mcp"  # 变更/发布事件: search_changes / get_change_detail
    # 受限现场诊断 MCP。服务必须部署在目标诊断环境内，并由容器/账户提供真实隔离。
    MCP_DIAGNOSTIC_URL: str = "http://127.0.0.1:8107/mcp"
    DIAGNOSTIC_ENABLED: bool = False
    DIAGNOSTIC_TOKEN: str = ""
    DIAGNOSTIC_TARGET_CATALOG: str = "{}"  # 服务入口/依赖关系 JSON，仅作定位上下文
    MCP_TERMCP_URL: str = "http://127.0.0.1:18766/mcp"  # 受控终端 MCP 代理
    TERMCP_ENABLED: bool = False
    TERMCP_APPROVAL_API_URL: str = "http://127.0.0.1:18766"
    TERMCP_UI_URL: str = "http://127.0.0.1:18765"
    TERMCP_SSH_PROFILE: str = "test-target"
    AIOPS_CHECKPOINT_DB_PATH: str = "data/aiops_checkpoints.sqlite"

    # —— Windows Probe（只读现场证据；默认关闭，启用前需配置独立网关 token）——
    PROBE_ENABLED: bool = False
    PROBE_TARGET_ID: str = "windows-local-01"
    PROBE_TOKEN: str = ""
    PROBE_TLS_VERIFY: bool = True
    MCP_PROBE_URL: str = "http://127.0.0.1:18767/mcp"
    PROBE_EVIDENCE_DIR: str = "data/aiops-evidence"

    # —— Monitor MCP 生产化后端(Mock→Prometheus 双轨,见 docs/MCP生产化改造方案.md)——
    # MONITOR_BACKEND: "mock"(默认,演示剧本) 或 "prometheus"(真实监控查询)
    # PROMETHEUS_URL 配置后且 MONITOR_BACKEND=prometheus 时,指标查询走 Prometheus HTTP API;
    # 工具名/参数/返回结构不变,Agent 侧零改动;不可达时**不回退 mock**,如实返回
    # data_source=unavailable(见下方生产纪律)。
    MONITOR_BACKEND: str = "mock"
    PROMETHEUS_URL: str = ""
    # 生产纪律(2026-10-10): 配置了真实后端(指标 MONITOR_BACKEND=prometheus / 日志
    # CLS_BACKEND=elasticsearch)却不可达时,**一律不回退 Mock** —— 宁可如实返回
    # "数据不可用",也不拿编造的指标/日志当真实证据(实测中 Mock 日志的 OOM 堆栈
    # 曾让 Agent 编出错误根因)。
    # PromQL 模板,{service} 为**值**占位(经 service_map 展开成候选正则);
    # 标签键(instance/service/pod...)随监控栈而变,生产集群需按实际调整 —— 用
    # scripts/discover_prometheus_metrics.py 可自动发现指标名与服务名所在标签。
    PROMETHEUS_CPU_PROMQL: str = (
        'clamp_min(100 - avg(rate(node_cpu_seconds_total{mode="idle", '
        'instance=~"{service}.*"}[5m])) * 100, 0)'
    )
    # 内存模板同样带 {service} 过滤: 不加就变成"整机内存",会被 Agent 误当成该服务的内存
    # (宁可如实返回空点,也不给出张冠李戴的指标)
    PROMETHEUS_MEMORY_PROMQL: str = (
        '100 * (1 - node_memory_MemAvailable_bytes{instance=~"{service}.*"} '
        '/ node_memory_MemTotal_bytes{instance=~"{service}.*"})'
    )
    PROMETHEUS_TIMEOUT_SECONDS: float = 5.0
    # Prometheus 鉴权 / TLS(真实环境常启用;三项全留空 = 匿名直连,仅内网可信网络可用)
    PROMETHEUS_USERNAME: str = ""
    PROMETHEUS_PASSWORD: str = ""
    PROMETHEUS_BEARER_TOKEN: str = ""  # 设置后优先于 Basic Auth(如前置网关/Thanos 场景)
    PROMETHEUS_VERIFY_SSL: bool = True  # 自签证书的内网环境可置 False

    # —— RAG 知识源采集(connectors,见 docs/MCP生产化改造方案.md §5)——
    # MinIO 知识源: 扫描该桶内 .md/.txt 文档注入知识库(与文档备份桶 rag-documents 可不同)
    MINIO_SOURCE_BUCKET: str = "rag-documents"

    # —— CLS MCP 生产化后端(Mock→Elasticsearch 双轨,见 docs/MCP生产化改造方案.md §4.2)——
    # CLS_BACKEND: "mock"(默认,演示剧本) 或 "elasticsearch"(真实日志平台)
    # 配置 CLS_ES_URL 且 CLS_BACKEND=elasticsearch 时,日志查询走 ES;不可达时**不回退 mock**,
    # 如实返回 data_source=unavailable(见上方生产纪律)。
    CLS_BACKEND: str = "mock"
    CLS_ES_URL: str = ""
    # 服务名→日志索引模式;search_topic 用该模式匹配索引,search_log 查具体索引
    CLS_INDEX_PATTERN: str = "{service}-logs-*"
    # 日志文档字段名(真实平台字段映射到 timestamp/level/message)
    CLS_LOG_TIMESTAMP_FIELD: str = "@timestamp"
    CLS_LOG_LEVEL_FIELD: str = "level"
    CLS_LOG_MESSAGE_FIELD: str = "message"
    CLS_TIMEOUT_SECONDS: float = 5.0
    # ES 鉴权 / TLS(留空 = 匿名直连;真实集群通常至少需要其一)
    CLS_ES_USERNAME: str = ""
    CLS_ES_PASSWORD: str = ""
    CLS_ES_API_KEY: str = ""  # ES ApiKey 鉴权;设置后优先于 Basic Auth
    CLS_ES_VERIFY_SSL: bool = True  # 自签证书的内网环境可置 False

    # —— 变更/发布事件 MCP(2026-10-10 新增,独立证据源) ——
    # 变更事件与指标/日志正交,是根因鉴别(尤其"指标异常 + 刚发过版")的第二类独立证据。
    # 数据源复用现有 ES 集群: CHANGE_ES_URL 留空时回退 CLS_ES_URL(同集群不同索引)。
    # 无 mock 分支 —— 与日志侧同纪律: 后端不可达时如实返回"数据不可用",绝不编造变更记录。
    CHANGE_ES_URL: str = ""  # 留空则用 CLS_ES_URL(同一 ES 集群)
    CHANGE_INDEX_PATTERN: str = "change-events-*"  # 变更事件集中索引(用 service 字段区分服务)
    # 变更事件字段映射(真实平台字段名 → 语义字段)
    CHANGE_TIMESTAMP_FIELD: str = "@timestamp"
    CHANGE_SERVICE_FIELD: str = "service"
    CHANGE_ID_FIELD: str = "change_id"
    CHANGE_TYPE_FIELD: str = "change_type"  # deploy / config / scale / rollback
    CHANGE_OPERATOR_FIELD: str = "operator"
    CHANGE_VERSION_FIELD: str = "version"
    CHANGE_DESCRIPTION_FIELD: str = "description"
    CHANGE_STATUS_FIELD: str = "status"
    CHANGE_TIMEOUT_SECONDS: float = 5.0

    # —— 服务名别名表(生产关键: 口头名↔监控前缀↔日志索引前缀,见 docs/MCP生产化改造方案.md §3)——
    # JSON 字符串: {"口头服务名": {"monitor": "监控instance前缀", "logs": "日志索引前缀"}}
    # 双轨真实路径查询前先经 service_map.resolve_service 归一化并展开候选,
    # 解决"用户说订单服务,监控叫 order-svc,索引叫 order-service-logs-*"导致的检索落空。
    SERVICE_ALIASES: str = "{}"

    @property
    def MCP_SERVERS(self) -> dict:
        """聚合给 MultiServerMCPClient 的配置字典。改地址只动上面几行,这里自动跟随。"""
        servers = {
            "monitor": {"transport": "streamable_http", "url": self.MCP_MONITOR_URL},
            "cls": {"transport": "streamable_http", "url": self.MCP_CLS_URL},
            "knowledge_base": {"transport": "streamable_http", "url": self.MCP_RAG_URL},
            "change": {"transport": "streamable_http", "url": self.MCP_CHANGE_URL},
        }
        if self.PROBE_ENABLED:
            probe = {"transport": "streamable_http", "url": self.MCP_PROBE_URL}
            if self.PROBE_TOKEN:
                probe["headers"] = {"Authorization": f"Bearer {self.PROBE_TOKEN}"}
            # httpx.AsyncClient consumes this through langchain-mcp-adapters.
            # Keep verification enabled by default; disabling it is an explicit
            # local-test choice and should never be inferred from the URL.
            if self.MCP_PROBE_URL.lower().startswith("https://"):
                probe["tls_verify"] = self.PROBE_TLS_VERIFY
            servers["probe"] = probe
        return servers

    @property
    def MCP_TERMCP_SERVER(self) -> dict:
        return {
            "transport": "streamable_http",
            "url": self.MCP_TERMCP_URL,
        }

    @property
    def RESOLVED_CHANGE_ES_URL(self) -> str:
        """变更事件 ES 地址: CHANGE_ES_URL 显式配置优先,否则回退 CLS_ES_URL(同集群)。"""
        return (self.CHANGE_ES_URL or self.CLS_ES_URL).strip()

    @property
    def RESOLVED_LLM_API_BASE(self) -> str:
        """解析后的 LLM 接口地址(供应商无关)。

        优先级: LLM_API_BASE(显式) → 检测到 DEEPSEEK_API_KEY 时用 DeepSeek 官方地址
                → DASHSCOPE_API_BASE(旧行为,兼容)
        """
        if self.LLM_API_BASE:
            return self.LLM_API_BASE.rstrip("/")
        if self.DEEPSEEK_API_KEY:
            return "https://api.deepseek.com"
        return self.DASHSCOPE_API_BASE.rstrip("/")

    @property
    def RESOLVED_LLM_API_KEY(self) -> Optional[str]:
        """解析后的 LLM API Key。优先级: LLM_API_KEY → DEEPSEEK_API_KEY → DASHSCOPE_API_KEY。"""
        return self.LLM_API_KEY or self.DEEPSEEK_API_KEY or self.DASHSCOPE_API_KEY

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

# ── 本机内部通信绕过系统代理（2026-10-09 修复）─────────────────────────
# 背景: 本机环境存在 HTTP_PROXY/HTTPS_PROXY(如 127.0.0.1:14118 的调试代理),
# httpx/urllib 默认会读取它,导致连本机 MCP 服务(127.0.0.1:8103/8104/8105)时
# 请求被代理劫持 → 502 Bad Gateway → "MCP 工具加载失败"整个诊断链路瘫掉。
# 修复: 进程启动时设置 NO_PROXY,让 localhost/127.0.0.1 直连。
# 注意: 这是**增量**设置(不覆盖已有的 NO_PROXY 值),只补上本机地址。
_LOCAL_NO_PROXY = "127.0.0.1,localhost,::1"
for _var in ("NO_PROXY", "no_proxy"):
    _existing = os.environ.get(_var, "").strip()
    if _LOCAL_NO_PROXY not in _existing:
        os.environ[_var] = f"{_existing},{_LOCAL_NO_PROXY}".lstrip(",") if _existing else _LOCAL_NO_PROXY

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.PROCESSED_DIR, exist_ok=True)
os.makedirs(settings.VECTOR_DIR, exist_ok=True)
