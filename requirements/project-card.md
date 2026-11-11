# 项目资料卡 · ragPdfSystem（RAG 智库 + AIOps 诊断 Agent）

> 本卡按 `C:\Users\Administrator\Downloads\通用-项目理解与测试资料维护提示词.txt` 的【项目资料卡｜使用时填写】逐项填写。
> 填写方式：所有结论都从当前工作区源码/文档实际读取后写入，并标注 `basis` 与来源；
> 未核实的写"未核实"，不作为结论。**本卡是理解材料，不是操作授权**——卡内任何命令、配置、旧报告结论都不自动构成执行许可。
>
> 采集时间：2026-11-11 09:2x（Asia/Shanghai）
> 约定基线（固定读取的提交）：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（分支 `main`，2026-11-11 09:10）
> 未提交差异：3 项未跟踪文件 `cleanup-flash-fix.ps1`、`pelican-bicycle.html`、`pytest-of-Administrator/`；
> 已跟踪文件无改动（`git status` 核实）。资料正文只依据已提交内容 + 工作区当前文件内容（两者一致的已逐文件 SHA-256 登记，见 `requirements/sources/index.json`）。

---

## 1. 项目名称与要解决的问题

- **名称**：ragPdfSystem（仓库目录名 `ragPdfSystem++agent`）。产品由两条业务线组成：
  1. **RAG 智库系统**——把企业/个人文档（PDF/Word/Excel/PPT/Markdown/TXT/HTML）变成可检索、可溯源的知识库，问答时给出带页码出处的答案。
  2. **AIOps 运维诊断 Agent**——接收一句中文故障现象，用 LangGraph 的 Plan-Execute-Replan 图驱动真实模型，通过 MCP 工具取证（指标/日志/变更/知识库/本机探针），产出带证据链的根因诊断报告。
- **要解决的问题**：
  - RAG 侧：文档多格式、切分粒度不可控、纯向量检索对专有名词和精确串不敏感、答案不可溯源。→ 用"多格式解析 + 页号感知切分 + BM25/向量混合检索 + rerank + 强制引用段落编号"解决。
  - AIOps 侧：值班人拿到告警后要跨多个后台人肉比对"应用实际连接的下游端口 vs 注册登记的下游端口"，容易漏判误判；模型凭空编造根因（尤其在有 Mock 数据的日志上）。→ 用"结构化调查 + 证据账本 + 判定规则门禁 + 生产纪律（真实后端不可达时如实返回 unavailable，不回退 Mock）"解决。
- basis：`observed`（README.md 首两节、`src/agent/aiops/README` 级模块 docstring、`src/settings.py` 的"生产纪律"注释原文）。

## 2. 目标用户 / 典型使用场景 / 核心业务对象

### 2.1 目标用户
| 用户类型 | 依据 |
|---|---|
| 知识库使用者（运维/研发/业务人员）：上传资料、提问、看带出处的答案 | `observed` `frontend/src/views/Chat.vue`、`KnowledgeBaseDetail.vue` |
| 值班/运维工程师：提交故障现象、看诊断过程与报告 | `observed` `frontend/src/views/AIOps.vue`（48.8KB，全站最大页面） |
| 知识库/助手的配置者：建库、配切分、配助手/Agent、生成 QA 对 | `observed` `assistant.py`/`agent.py` 路由全套 CRUD |
| 审计员（`role in {admin, auditor}`）：可读原始证据引用 | `observed` `src/api/routers/aiops.py:190,198-205` |
| 项目作者本人（本科毕设 + 真实验收迭代）：用真实付费模型跑诊断轮次并记账 | `observed` `AGENTS.md`、`docs/aiops-goal-handover-20261108.md` |

### 2.2 典型使用场景
1. **建库→上传→向量化→问答**：建知识库 → 上传 PDF → 异步解析切分向量化 → 在 Chat 页提问 → 得到带 `[Page N]` 出处的答案。
2. **故障诊断**：在 AIOps 页输入"订单服务调用下游 502" → SSE 实时看到计划/每步进展 → 得到根因 + 原因码 + 证据列表 + 建议。
3. **评测**：为知识库生成评测集（或用自定义数据集）→ 跑评测 → 看报告指标。
4. **审计/回放**：按 `thread_id` 查运行状态、证据账本、步级快照（快照默认关闭）。
5. **本机故障注入验收**（项目作者专用）：Windows 侧 Probe 采集 + 测试环境注入故障，验证诊断链路是否真能定位。

### 2.3 核心业务对象（稳定身份 / 所有者 / 权威存储）
| 对象 | 稳定身份 | 所有者 | 权威存储 | 生命周期 | 依据 |
|---|---|---|---|---|---|
| 用户 User | `users.id`；`username`/`email` 唯一 | — | SQLite `users`（`password_hash` 只存哈希） | `is_active` 软停用 | `observed` `src/database/models.py:7-22` |
| 知识库 KnowledgeBase | `id` + `kb_uid`(unique) | `owner_id`→users | SQLite `knowledge_bases` | `is_public` 控制共享；删除级联 document/qa | `observed` `models.py:24-41` |
| 文档 KnowledgeDocument | `id` + `doc_uid`(unique) | 经 kb 归属用户 | SQLite `knowledge_documents`（`status` 0上传中/1处理中/2完成/3失败）；原始文件在 `data/raw` + MinIO 镜像 | `celery_task_id` 记录派发句柄 | `observed` `models.py:43-64` |
| 切片 DocumentChunk | `id` + `chunk_uid`(unique)；`vector_id` 指向 Milvus 主键 | 经 doc 归属 | SQLite `document_chunks`（正文+`page_num`）；向量在 Milvus `rag_documents_v2` | 重处理时先删旧 chunk | `observed` `models.py:66-77`、`src/worker/tasks.py:159-201` |
| 生成 QA 对 GeneratedQAPair | `id` | 经 kb | SQLite `generated_qa_pairs`（`status` 0待确认/1确认/2拒绝） | 支持下载 | `observed` `models.py:79-93` |
| 会话 ChatSession / 交互 ChatInteraction | `session_uid`(unique) / `id` | `user_id` | SQLite；短期对话上下文另存 Redis `session:{id}:history`（TTL 3600） | 会话删除级联 | `observed` `models.py:95-121`、`src/services/memory_service.py:55-64` |
| 评测任务 EvaluationTask / 结果 / 数据集项 | `id` | `created_by`（无 kb 的任务靠它做所有权校验） | SQLite 3 张表 | `status` 0待跑/1运行/2完成/3失败/4数据集已生成 | `observed` `models.py:123-167`、`evaluation.py:27` |
| 助手 Assistant / 版本 | `id` / `(assistant_id, version)` | `user_id` | SQLite `assistants`+`assistant_versions` | 版本快照存 JSON config | `observed` `models.py:169-212` |
| Agent（可执行智能体） | `id` | `user_id` | SQLite `agents`；执行留痕 `agent_execution_logs` | `type` = function_call/react/plan_execute | `observed` `models.py:214-264` |
| **诊断运行 AiopsRun** | `thread_id`(unique) | `user_id` | SQLite `aiops_runs`（`status` running/pending_review/approved/rejected/completed/failed） | 报告与 `degraded` 落库 | `observed` `models.py:267-282`、`docs/aiops-run-store.md` |
| 诊断审批 AiopsApproval | `id` | `reviewer_id` | SQLite `aiops_approvals` | action approve/reject | `observed` `models.py:285-297` |
| 步级快照 AiopsStepSnapshot | `(thread_id, step_index)` | — | SQLite `aiops_step_snapshots`（payload JSON 文本） | 默认不写（`ENABLE_STEP_SNAPSHOTS=False`） | `observed` `models.py:299-311`、`src/settings.py` |
| **证据 AiopsEvidence** | `evidence_id`(unique, `ev-[A-Za-z0-9]{16,80}`) | `user_id` | SQLite `aiops_evidence`（摘要脱敏）；原始数据留在受保护目录 `PROBE_EVIDENCE_DIR=data/aiops-evidence`，只存 `raw_ref`+`raw_hash` | `fresh_until` 表示新鲜期 | `observed` `models.py:346-363`、`aiops.py:196` |
| 探针目标 ProbeTarget / 快照 ProbeSnapshot | `target_id`(unique) / `id` | — | SQLite；快照保留 24h（`expires_at`） | 不持久化 secret（注释明写） | `observed` `models.py:314-343` |
| 诊断 checkpoint | `thread_id` + LangGraph checkpoint | — | `data/aiops_checkpoints.sqlite`（`AIOPS_CHECKPOINT_DB_PATH`） | 挂起期间保存图状态 | `observed` `src/settings.py`、`graph.py` |
| 向量（原始事实/派生） | Milvus 主键 = `chunk_uid`；本地降级 `vectors.npy`+`vectors_meta.json` | — | Milvus（权威）+ LocalVectorStore（降级副本，**双写**：先本地再 Milvus） | 文档重处理即重写 | `observed` `src/database/vector_db.py:127-151` |

派生视图 / 缓存 / 客户端状态（与权威存储分开看）：
- 前端 `localStorage.token` 只是**客户端状态**，不是授权凭据（后端每次请求独立验签）。
- BM25 索引是**进程内派生索引**，懒加载构建一次后不随新文档增量刷新（`observed` `src/retrieval/hybrid_retriever.py:85,141-149`）。
- Redis 短期会话记忆是**缓存**（TTL 3600），丢失不影响权威数据。
- `data/vectors/vectors.npy`（71.8MB）+`vectors_meta.json`（20.3MB）是 Milvus 的**降级副本**，不是唯一真相。

## 3. 本次任务目标 · 项目阶段 · 本期范围与后续目标

### 3.1 本次任务目标（用户本次请求，m00002）
用上面的模板建立本项目的**基础认知资料**：先读源码核实，再产出可追溯的需求/规格/用例资料，并把【项目资料卡】填实。
**不包含**：改业务代码、跑产品用例、触发模型、付费、部署。

### 3.2 项目阶段（事实与判断分开）
- `observed`（事实）：仓库处于"持续真实验收迭代期"。`docs/aiops-goal-handover-20261108.md` 记录 036–050 共 15 轮真实付费诊断，10 轮通过、5 轮未通过（3 次判定逻辑缺陷已修 + 2 次模型侧失误故意不修）。
- `observed`（事实）：`AGENTS.md` 2026-11-06 记录"目标已由用户暂停"，并载明 022 endpoint、033 stopped 产品链路通过，034 normal 未通过。
- `observed`（事实）：`ENABLE_HITL=False`、`ENABLE_SUPERVISOR=False`、`ENABLE_STEP_SNAPSHOTS=False`、`ENABLE_DYNAMIC_CLASSIFICATION=False`、`ENABLE_LLM_EVIDENCE_JUDGE=False` 等大批能力开关**默认关闭**（`src/settings.py`）。
- `unresolved`（判断）：项目性质（本科毕设 / 已转向产品化）只能从文档自述推断，用户未在本次任务中确认。资料中一律写"毕设项目 + 真实验收迭代"，不宣称产品已上线。

### 3.3 本期范围（本次资料覆盖）
- 覆盖：RAG 主链路（建库→上传→解析切分→向量化→混合检索→rerank→问答→溯源）、AIOps 诊断链路（SSE 入口→图→计划/执行/证据/报告→运行记录与审计端点）、评测链路、助手/Agent 配置链路、鉴权与前端控制台、平台运行约束（端口/密钥/CI/降级纪律）。
- 不覆盖/未展开：`src/probe` Windows 采集器内部实现细节（只登记入口与去向）、`mcp_servers` 各 server 的协议细节（只登记进程与端口）、`docs/thesis`、`docs/research`、`docs/history`（明确声明"历史结果不作当前验收"）、`scripts/aiops_round/*` 验收脚本族（只登记用途）。

### 3.4 后续目标（来自文档，未经本次确认）
- `observed`：把 AIOps 诊断从"10/15 通过"推向稳定复现（handover 文档的"别宣称"清单明确当前不能这么宣称）。
- `observed`：`ENABLE_SUPERVISOR` 端点"尚未实现，默认关闭勿依赖"（README 自述）。
- `proposed`（AI 建议，不自动成立）：把散落在 `docs/` 的 15 轮验收口径统一成单一权威表；补齐 `docs/api.md`（当前只覆盖 4 组路由，缺 aiops/agents/monitor/storage/health/upload）。

## 4. 已确认产品决定（及来源与适用条件）

判定标准：`confirmed` 只给"文档里由作者/用户明确决定、并写明理由"的条目；代码里能看到但没写成决定的一律 `observed`。

| # | 决定 | 理由（原文依据） | 来源 | basis | 适用条件 |
|---|---|---|---|---|---|
| D1 | 诊断走**独立 SSE 端点**，不接进 chat/rag_service | "解耦：运维诊断自成一路，不动现有 RAG 链路" | `src/api/routers/aiops.py:1-7` | confirmed | 诊断入口固定为 `POST /api/v1/aiops` |
| D2 | 真实后端配置了却不可达时**不回退 Mock**，如实返回 `data_source=unavailable` | 注释原文：Mock 日志的 OOM 堆栈曾让 Agent 编错根因 | `src/settings.py`（MONITOR_BACKEND/CLS_BACKEND 注释段） | confirmed | 生产/验收环境；本机自测可显式选 mock |
| D3 | 改 `strategies/investigation.py` 判定逻辑前**必须先跑零成本回放门禁** | "把可以稳定复现做成 CI 门禁"；门禁四条不变量 | `.github/workflows/tests.yml` 步骤 `Decision-rule gate`；`docs/aiops-goal-handover-20261108.md` | confirmed | 任何触碰 `decide_from_evidence` 的提交 |
| D4 | 端口 8200（非 README 写的 8000），避开 Windows 保留段 7911-8010 | 源码注释：避开 winerror 10013 | `src/main.py:283-288` | confirmed | Windows 本地开发 |
| D5 | 环境变量加载后**追加 NO_PROXY** 覆盖 127.0.0.1/localhost/::1 | 注释：本机代理 127.0.0.1:14118 曾劫持本机 MCP 请求致 502 | `src/settings.py` 末尾 | confirmed | 本机跑 MCP 的场景 |
| D6 | `SECRET_KEY` 必须存在、不在黑名单、长度≥32，否则启动即失败 | `_validate_secrets()` + `_MIN_SECRET_KEY_LENGTH=32` | `src/main.py:36-61` | confirmed | 所有环境启动 |
| D7 | 历史结果不作当前验收；资料不写"原失败回写" | `AGENTS.md` / `docs/history` 反复声明"历史时点" | `AGENTS.md`（前 94 行流水头）、`docs/README.md` | confirmed | 所有验收结论引用 |
| D8 | 数据保护：`data/` 是有效实验依据不得当缓存删；`runtime/` 每次用独立子目录且保留失败；`.env`/`rag_system.db` 原位保留不提交不打印凭据 | `docs/project-layout.md` | `docs/project-layout.md` | confirmed | 所有本机操作 |
| D9 | 诊断 `--run-model` 硬闸门：一轮只允许一次 `POST /api/v1/aiops`，之后 403；轮次不符 503 | handover 文档"真实一轮流程" | `docs/aiops-goal-handover-20261108.md`、`scripts/aiops_test_environment.py` | confirmed | 付费验收轮次 |
| D10 | CI 用假模型跑离线单测，真实密钥永不进 CI（CI 里 `LLM_API_KEY` 被赋成占位假值 `sk-ci-placeholder`，仅供 LLMClient 构造通过）；重量级 OCR/数据集依赖从 CI 安装清单中 grep 排除 | `.github/workflows/tests.yml` 注释 | 同左 | confirmed | CI |

## 5. 产品/服务入口 · 源码位置 · 约定基线

### 5.1 用户可见入口
| 入口 | 地址/形态 | 依据 |
|---|---|---|
| Web 控制台 | Vue3 SPA，路由 `/login /dashboard /chat /knowledge-bases(/ :id) /evaluation /assistants /agents /aiops /monitor /queue-monitor` | `observed` `frontend/src/router/index.js:4-22` |
| HTTP API | `http://<host>:8200/api/v1/...`（`API_PREFIX=/api/v1`） | `observed` `src/main.py:288`、`src/settings.py:12` |
| OpenAPI 文档 | FastAPI 自动 `/docs`（未关闭） | `observed` `src/main.py` 未设 `docs_url=None` |
| Prometheus 指标 | `/metrics`（子应用挂载，`prometheus-fastapi-instrumentator` 可选） | `observed` `src/main.py` `_setup_prometheus()` |
| 独立 MCP 服务 | monitor :8104、cls :8103、rag :8105、change :8106、diagnostic :8107（默认关）、termcp :18766（默认关）、probe :18767（默认关） | `observed` `src/settings.py`、`mcp_servers/*` |
| 命令行入口 | `scripts/` 下约 90 个脚本（测试环境、验收、蒸馏、回放、验证）；`start_demo.bat`、`启动基础服务.bat` | `observed` 目录清单 |

### 5.2 源码位置（模块地图）
```
src/main.py            FastAPI 装配：密钥校验→建表/补列→中间件→路由挂载→uvicorn(8200)
src/settings.py        136 项配置字段（LLM/Embedding/RAG/AIOps/MCP/双轨后端开关；与 .env.example 136 键一一对齐）
src/api/routers/       13 个路由模块（auth health knowledge_base chat evaluation storage
                       monitor assistant agent loadfile query tasks aiops）
src/services/          rag_service(意图路由+3条路径) memory_service(Redis 短期) agent_tool_service
src/worker/            Celery app + process_document（薄封装纯函数，可同步调）
src/processors/        多格式解析 + 切分（页号感知）
src/retrieval/         hybrid(BM25+向量 RRF) / bm25 / vector / reranker(DashScope 在线)
src/database/          models(20 表) vector_db(Milvus+双写降级) local_vector_store(npy)
src/embedding/         DashScope TextEmbedding 或 OpenAI 兼容 /embeddings
src/llm/llm_client.py  OpenAI 兼容 + 主备回退 + 关思考链 + 模型白名单
src/agent/aiops/       诊断图与全部能力（graph/planner/executor/replanner/investigation...）
src/probe/             Windows 本机采集（collector/config/service/worker/protocol/evidence/storage）
frontend/src/          Vue3 控制台（AIOps.vue 48.8KB 为最大页面）
mcp_servers/           16 个 MCP 服务/客户端实现（独立进程）
```

### 5.3 约定基线
- 提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（`main`）。资料内所有 `file:line` 锚点均以此提交为基线，不写"main 分支当前"。
- 约束来源优先级：`AGENTS.md`（151KB 项目约定）> `CLAUDE.md`（通用行为准则）> `docs/project-layout.md`（目录约定）> `README.md`（会过期）。
- README 已知过期点（不采信）：端口 8000（实为 8200）；"自动触发 Celery"（bm25 库走进程内 BackgroundTasks）；测试矩阵"98 集成/PostgreSQL"（实为 SQLite）。

## 6. 资料工作区 · 交付位置 · 目录 schema

- **工作区**：本仓库工作树内新建 `requirements/`、`specs/`、`cases/`、`changes/`（本次新建，之前不存在）。
- **不在根目录新增开发入口文件**（遵循 `docs/project-layout.md`）；资料目录不与 `src/`、`frontend/src`、`mcp_servers`、`tests`、`docs/fixtures` 混放。
- **交付位置**：工作区本地文件（未提交、未推送；提交与发布按 §10 约定另行确认）。
- **目录 schema**：
```
requirements/
  project-card.md          ← 本卡（基础认知，人读入口）
  overview.md              ← 产品正文：目标/角色/对象关系/服务职责/业务闭环/范围
  index.json               ← requirement_id → 正文位置 / 来源 / 适用条件 / basis
  modules/<module>.md      ← 分模块正文（用户预期/入口/校验/反馈/异常/权限/数据影响）
  sources/index.json       ← source_id → 类型/位置/可用状态/采集时间/版本或 SHA-256/摘要/材料路径
  sources/<source-id>.md   ← 单来源登记（代码只登记提交+路径+符号，不复制仓库）
specs/
  feature-index.json       ← feature_id → 模块/用户目标/入口/需求引用/实现与资料状态/源码锚点
  modules/<module>.md      ← 交互与接口状态、规则(rule_id)、业务结果与断言
  questions.md             ← 冲突与影响（不代替正文）
  catalog.json             ← 模块路径/核实版本/ready|partial|draft/剩余范围/用例分类统计
cases/<module>.json        ← 用例（步骤/预期/证据要求/执行条件）
changes/current.md         ← 增量维护记录（原位追加，不建日期副本）
```

## 7. 运行平台 · 部署环境 · 外部依赖及已知模块

### 7.1 运行平台
- 开发/验收：**Windows 本机**（`D:\ragPdfSystem++agent`），Python 3.12、Node/Vite、SQLite。
- CI：`ubuntu-latest` Python 3.12（`offline-tests` workflow）。
- 容器：`docker/` 下有 `docker-compose.yml`（主栈）、`docker-compose.observability.yml`、`docker-compose.probe-local.yml`、`Dockerfile`、`frontend.Dockerfile`、`prometheus.yml`、`seccomp.json` 以及 probe 相关 `gateway.Dockerfile`/`patched.Dockerfile`/`approval-expiry.patch`/`config.toml.example`。
  - `observed` 注意：`docker/docker-compose.yml` 的 minio 镜像写作 `pgsty/silo:...` 而非官方 `minio/minio`，是否等价可用**未核实**。

### 7.2 外部依赖与"缺失即降级"行为
| 依赖 | 用途 | 缺失/失败时的行为 | 依据 |
|---|---|---|---|
| DashScope / OpenAI 兼容 LLM 服务 | 全部生成与判定 | 主模型→备用模型 `with_fallbacks`（仅连接/超时/5xx/限流类） | `observed` `src/llm/llm_client.py:17-25,59-98` |
| Embedding 服务（DashScope 或 OpenAI 兼容，实际 .env 用硅基流动 bge-m3，1024 维） | 向量化 | 数量不匹配即抛异常 → 文档 status=3 | `observed` `src/worker/tasks.py:145-150` |
| Rerank（DashScope TextReRank，**在线调用**） | 精排 | 失败/非 200 → 直接截断 top_n，不重试 | `observed` `src/retrieval/reranker.py:48-55` |
| Milvus | 向量权威存储 | 连接失败只 warning，`_available=False` → 全部走本地 `data/vectors` | `observed` `src/database/vector_db.py:38-47,172-174` |
| Redis | 短期会话记忆 + Celery broker | 读取失败/为空则无历史；broker 不可用时 Celery 派发 5s 超时回落同步 | `observed` `memory_service.py`、`knowledge_base.py:29-41` |
| RabbitMQ | Celery broker（默认 Redis 亦可） | 同上（`broker_connection_retry=False` 快速失败） | `observed` `src/worker/celery_app.py` |
| MinIO | 对象存储/预览 | 上传失败仅 `print`、**不阻断** → "MinIO 预览可用"在缺席时不成立 | `observed` `knowledge_base.py:374-380` |
| MCP 服务（monitor/cls/change/rag/probe/termcp/diagnostic） | 诊断取证 | 缺席时 `evidence_source_availability` 如实记录；不静默伪造 | `observed` `src/settings.py`、`state.py` 注释 |
| Prometheus | 指标后端 | `MONITOR_BACKEND=mock` 时用 mock | `observed` `src/settings.py` |

### 7.3 已知模块（`confirmed`/`observed` 混合，逐条标）
- `observed` **20 张** SQLite 表（`src/database/models.py` 实测 20 个 `__tablename__`），无 Alembic 迁移；建表靠 `create_all` + `_migrate_schema()` 列级 `ALTER`。
- `observed` SQLite 连接设 WAL + `busy_timeout=10000`，为 API 与 Celery worker 多进程并写。
- `observed` 检索 = BM25 与向量各取 `top_k*2`，**RRF 融合（常数 60）**，非加权求和；中文分词是 2-gram 滑窗，不用 jieba。
- `observed` `RAGService.query` 是**意图路由**：规则快过滤（问候→chat；含 cpu/内存/故障/超时/oom 等→diagnosis）→ 未命中才调 LLM 分类 → 按 `(intent, 有无 kb, 有无 agent)` 矩阵分派 `_general_chat`/`_rag_path`/`_agent_path`。
- `observed` 长期记忆是**空实现**（`add_long_term_memory` 函数体 `pass`；读取复用文档向量库），不是用户画像库。
- `observed` `src/api/routers/query.py`、`tasks.py` **未挂载**，对应端点不可达。
- `observed` `src/services/pdf_processor.py`（loadfile 遗留链路）只写 Milvus、不写 SQL、不走 Celery，与主链路并行。
- `observed` `ParentChildChunker`/`TextCleaner`/`MetadataExtractor` 无业务调用方（仅 `__init__` 导出）。
- `observed` 前端路由守卫只查 `localStorage.token` 是否存在，**不校验有效性/过期**；真正授权在后端每次请求。

## 8. 需求 / 设计 / 旧总结 / 源码 / 实测材料

| 类别 | 材料 | 可用性 | 备注 |
|---|---|---|---|
| 需求/约定 | `AGENTS.md`（151KB） | available | 前 94 行是倒序逐日流水，**历史时点**，不得当验收结论 |
| 约定 | `CLAUDE.md`、`docs/project-layout.md` | available | 行为准则与目录约定 |
| 产品说明 | `README.md` | available（部分过期） | 端口/异步机制/测试矩阵三处与代码冲突，已列入 `specs/questions.md` |
| 架构/接口 | `docs/api.md`(71 行，仅 4 组路由)；架构说明以源码为准（`src/main.py`、`src/agent/aiops/graph.py`、`src/agent/aiops/strategies/investigation.py`） | available（`api.md` 覆盖面严重不足） | 原 `docs/architecture.md`（旧旁开式动态分类口径）已于 2026-11-11 随旧标准清理移除，未替代为新文档；`api.md` 缺 aiops/agents/monitor/storage/health/upload |
| 现状/验收 | `docs/aiops-goal-handover-20261108.md`（294 行） | available | 唯一权威现状：15 轮 10 通过、五项"别宣称"、复现入口 |
| 配置 | `docs/configuration-current-20261027.md`、`configuration-fields-20261027.md`（文档称 132 项） | available | 实测 `src/settings.py` **136 个字段**、`.env.example` **136 键**且两边完全一致；文档少 4 项，差值未逐项定位（见 `specs/questions.md` Q-23） |
| 运行记录 | `docs/aiops-run-store.md`、`aiops-events.md` | available | 三张表 + `/steps` 未启用 |
| 本机探针 | `docs/windows-probe.md`、`windows-probe-fault-acceptance.md`、`docs/termcp-aiops.md` | available | 本次未展开 |
| 旧报告 | `docs/history/*`、`docs/thesis/*`、`docs/research/*` | available 但**不作为当前验收** | 文档自身声明 |
| 源码 | `src/`（13 路由/9 服务/6 处理器/6 检索/4 数据库/aiops 33 文件） | available | 逐文件 SHA-256 已登记 |
| 测试 | `tests/` 118 个 `test_*.py`；`pytest.ini`（`addopts=-ra -m "not integration"`）；前端 vitest | available | 未运行（任务边界禁止执行产品用例） |
| 实测材料 | `data/`（vectors/aiops-evidence/runbooks/reports…）、`runtime/`（按轮次命名的实验目录） | available（只读） | `data/` 不得当缓存删；`runtime/` 已 gitignore |

## 9. 代表性完整业务场景 + 关注的异常/恢复

### 场景 A（RAG 主闭环，`observed` 全链路已接通的路径）
建库 → 上传 PDF → 魔数校验/50MB 上限 → 落盘 `data/raw` + MinIO 镜像（失败不阻断）→ `_dispatch_document` 判异步边界 → Celery（5s 超时则回落进程内）→ 解析（PyMuPDF 逐页，空页回退 pdfplumber）→ 页号感知切分（配置优先级 doc > kb > 1000/200）→ embedding → 先删旧 chunk → 写 SQL（`vector_id=chunk.id`）→ Milvus 插入（同时双写本地向量）→ `status=2` → Chat 提问 → 意图路由 → 混合检索 + rerank → 生成（强制"引用段落编号"）→ 返回 `source_documents` 带 `[Page N]`。
关注的异常/恢复：
- 解析/向量化异常 → `status=3` + `error_msg`，**不 re-raise**（避免 Celery 无限重试）。
- Celery broker 不可用 → 5 秒超时回落同步后台，用户仍拿到"已排队/处理中"。
- Milvus 不可用 → 走本地 npy 检索，答案仍可给出（但检索面变窄，属**降级不报错**）。
- 取消/超时/结果未知：**无跨请求取消机制**（`observed`）；任务状态只能靠 `GET /{kb_id}/documents` 轮询，`tasks.py` 端点未挂载。

### 场景 B（AIOps 诊断，`observed` 代码链路 + `confirmed` 验收口径）
`POST /api/v1/aiops {query, session_id, terminal_enabled}` → 鉴权 → SSE 建立 → 图执行（planner→executor→replanner…）→ 逐事件 `{type: plan|step_complete|report|complete|error}` → 结束时额外一条 `{type: usage, llm_calls, input_tokens, output_tokens, cost_cny_estimated, elapsed_s}`；`run_store` 同步落 `aiops_runs`；证据落 `aiops_evidence`（摘要脱敏，原始在受保护目录）。
关注的异常/恢复：
- `terminal_enabled=true` 而 `TERMCP_ENABLED=false` → **503「受控终端诊断尚未启用」**（前置拒绝，不建 run）。
- 图内异常 → 事件 `{type:error, stage:exception}` + Prometheus `result=failed`。
- 终态挂起（`STATUS_PENDING_TERMINAL`）→ `POST /runs/{id}/continue` 校验审批有效性后 `Command(resume=...)` 续跑；`STATUS_PENDING_REVIEW` 走到该端点 → **409「此诊断等待的不是 Termcp 命令审批」**；其它状态 → 409。
- 断线/刷新：**未做断线续传（无 Last-Event-ID），也不能从第 k 步重放**（`confirmed` 文档自述）；只能靠 `GET /runs/{thread_id}` 拿现状。
- 诊断"结果未知"与"执行失败"在状态机上可区分：`investigation_failure`（执行失败）vs 正常 completed 但 `unlocated`（未能定位）。

### 场景 C（审计/回放，`observed`）
普通用户 `can_read_raw=false`，拿到的证据行不含 `raw_ref`；`admin/auditor` 才 `include_raw=True`。`GET /runs/{id}/steps` 因 `ENABLE_STEP_SNAPSHOTS=False` 实测返回 `total:0`——**端点存在 ≠ 数据存在**，这是本资料要反复标明的"已实现 vs 已启用"差别。

### 场景 D（权限与身份）
注册 → 登录拿 JWT（HS256，`ACCESS_TOKEN_EXPIRE_MINUTES=480`）→ 前端存 `localStorage.token` → 每次请求 `OAuth2PasswordBearer` 验签 + `is_active` 校验。越权边界：`_owned_run` 用 `run.user_id != user.id` 判 404（**不泄露存在性**）；评测任务用 `_check_task_ownership`；MinIO 用 `_user_prefix`/`_safe_object_name` 做用户目录隔离。

## 10. 本任务授权 · 执行者权限 · 调用预算 · 提交与发布约定

- **本任务授权范围**（用户 m00002 + 模板【任务边界】）：
  - 允许：只读源码、只读文档/数据/运行时目录；在工作区新建 `requirements/ spec/s cases/ changes/` 资料文件；运行**纯文档校验器**（如 JSON 语法检查、ID/引用一致性检查）。
  - 禁止：改业务代码、构建、部署、重启服务、执行产品用例、触发模型调用、产生任何费用、调用付费脚本（`scripts/aiops_round/*`、`--run-model`）、提交或推送。
- **执行者权限**：本次以只读身份读取本地工作区；不读取 `.env` 中的密钥明文写进任何输出（只登记"该字段存在/指向哪个服务"）；不打印 Token/Cookie/私钥。
- **调用预算**：模型调用预算 = 0（本次不触发任何真实模型）；付费额度 = 0；外部网络请求 = 0（未联网核实 Milvus/RabbitMQ 在线状态，相关项标 `unresolved`）。
- **提交与发布约定**：本次产物为**工作区本地资料**，`delivery_status = delivered_local`（未提交、未推送、未发布）。如要入库，需用户另行确认提交范围与信息（`.env`/`rag_system.db`/`runtime/` 永不入库）。

## 11. 输出语言 · 角色划分 · 其它已约束

- **输出语言**：简体中文（用户提示词为中文；源码注释亦为中文）。
- **角色划分**（按模板）：`functional`（单功能行为）/`core-flow`（完整链路）/`performance`（可测量指标）/`experience`（使用路径与反馈）/`product-details`（产品细节）。整套资料**只对确有区别的断言分配角色**，不为每个需求机械复制五份。
- **basis 分级**：`confirmed` / `observed` / `unresolved` / `proposed` 四档，语义同模板；`observed` 可以 ready（记录 OBSERVED），但不证明设计正确。
- **exeution_kind**：`live_ui` / `live_api` / `live_cli` / `static_review` / `controlled_fixture`；普通入口能触发的校验错误仍算对应 live 类型，只有需要响应模拟/故障注入/特殊预置才用 `controlled_fixture`。
- **其它约束**（来自工作区指令）：
  - `CLAUDE.md`：先想后写、最小改动、外科手术式修改、目标驱动可验证；不确定就问，不要静默假设。
  - `docs/project-layout.md`：根目录只放工程入口/依赖/规则；`data/` 不得当缓存删；`.env`、`rag_system.db` 原位保留；临时产物走系统临时目录或 `runtime/` 独立子目录。
  - `AGENTS.md`：历史流水不回写成当前结论；每轮验收必须"先停后端再停环境"；禁止在未审查情况下自动跑 `scripts/probes`（涉及网络与费用）。

---

## 附：本次核实的已知缺口（摘要，明细见 `specs/questions.md`）

1. `README.md` 与源码三处冲突：端口（8000 vs 8200）、"自动触发 Celery"（bm25 走进程内）、测试矩阵（98 集成/PostgreSQL vs 实际 SQLite）。
2. `docs/api.md` 只覆盖 4 组路由，缺 aiops/agents/monitor/storage/health/upload —— 规格资料以源码为准，不以该文档为准。
3. `RAG_MIN_SCORE`、`CHUNK_SIZE`、`TOP_K` 三个配置项在 `src/` 内无业务引用（死配置：实际值来自硬编码 1000/200 与请求参数），`LONG_TERM_MEMORY_COLLECTION` 同样无引用。
4. `assistant.rag_config` 写入 DB 并透传，但 `RAGService` 从不读它 → 助手的 `top_k`/`enable_rerank` 配置实际无效。
5. 环境在线状态（Milvus/RabbitMQ/Celery worker/Elasticsearch）本轮未联网核实，一律 `unresolved`。
6. 全量测试口径冲突：README 写离线 137 / 集成 98；handover 文档写全量 `pytest tests -q` 为 2071 passed / 37 failed（37 为改动前既存失败）。本次未运行任何测试。
