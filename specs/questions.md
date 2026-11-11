# 冲突、缺口与待澄清（specs/questions.md）

> 本文件只登记**冲突与影响**，不代替任何正文。每条给出：现状证据、影响面、需要的决定、当前处理方式（资料里怎么写的）。
> 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`。状态：`open` 未决 / `resolved_in_docs` 资料内已按某口径处理但需产品确认 / `spec_gap` 资料缺口。
> 类型：`conflict` 口径冲突 / `gap` 缺依据 / `risk` 实现风险 / `todo` 待补材料。

---

## Q-01 后端端口：README 写 8000，源码是 8200
- 证据：`README.md:148` 写 `http://localhost:8000/docs`；`src/main.py:283-288` 实际 `port=8200`，且有注释说明 8200 是为避开 Windows 保留段 7911-8010（winerror 10013）。
- 影响：任何照 README 配代理/脚本/CI 健康检查的人都会连错端口；`frontend/vite.config.js:36-42` 代理目标已是 8200，说明前端已跟随代码。
- 需要的决定：README 是否更新（属业务文档修改，超出本任务边界）。
- 资料处理：全部按 `observed` 8200 写；README 标 `reliability: partial_outdated`。
- 状态：`resolved_in_docs`（口径已定，文档待改）

## Q-02 前端端口：README 写 5173，实际 5273，且后端开发 CORS 白名单无 5173
- 证据：`README.md:147`；`frontend/vite.config.js:31-35`（`host=127.0.0.1, port=5273, strictPort=true`）；`src/main.py:64-87` 开发白名单为 5273/3000/8080 的 localhost 与 127.0.0.1 共 6 条，**不含 5173**。
- 影响：若有人把前端改成 5173 启动，浏览器请求会被 CORS 拦（除非走 Vite 代理，代理是同源请求不受 CORS 限制 —— 这一点决定了实际是否真的会坏）。
- 资料处理：按 5273 写；CORS 白名单条目作为 RULE-PLAT 的一条规则写明"开发环境硬编码 6 个 origin"。
- 状态：`resolved_in_docs`

## Q-03 "上传后自动触发 Celery 异步任务"不成立
- 证据：`README.md:19`；`src/api/routers/knowledge_base.py:125-141` `_dispatch_document` 在 `retrieval_mode=="bm25"` 时走进程内 BackgroundTasks；`:29-41,402-409` Celery 派发有 5 秒硬超时（ThreadPoolExecutor + `future.result(timeout=5)`），超时/异常回落同步 background；`src/worker/celery_app.py` 侧 `broker_connection_retry=False` 快速失败。
- 影响：用户对"异步/同步"的预期会错；处理大文件时可能实际占住 API 进程。
- 资料处理：kb-ingest 正文把"异步边界"单列一节，写清三种情形（bm25 进程内 / hybrid-Celery / broker 不可用回落同步）。
- 状态：`resolved_in_docs`

## Q-04 `docs/api.md` 严重不完整
- 证据：`docs/api.md` 共 71 行，只覆盖 auth / knowledge-bases / chat / evaluations 四组；缺 aiops、agents、monitor、storage、health、upload 六组；evaluations 只写 2 个端点（实际 10 个）；knowledge-bases 只写 2 个（实际 20 个）。
- 影响：以该文档为依据写用例会大面积漏测。
- 资料处理：规格一律以源码为事实源；`docs/api.md` 只作冲突证据引用。
- 状态：`spec_gap`

## Q-05 测试数量口径三方冲突
- 证据：
  - `README.md` 自述"离线单测 137 个 / 集成测试 98 个（需 PostgreSQL/Redis/ES/Milvus）"。
  - `docs/aiops-goal-handover-20261108.md` 记全量 `pytest tests -q` 为 **2071 passed / 37 failed**，并说明 37 个为改动前既存失败（test_matching503_output_flow.py 24、test_four_issue_closeout.py 6、test_agent_knowledge_consumption.py 5、test_live_probe_mechanisms.py 1、test_probe_summary_output_flow.py 1），已用 git stash 比对失败集合相同。
  - 实际 `tests/` 有 118 个 `test_*.py`（含 conftest.py）；`pytest.ini` 的 `addopts = -ra -m "not integration"` 意味着默认只跑非集成。
  - 且集成测试依赖写"PostgreSQL"，但 `src/settings.py:103` 的 `DATABASE_URL` 是 SQLite —— 集成测试到底连什么，**未核实**（本轮不运行测试）。
- 影响：任何"测试全绿/共 N 个通过"的陈述都不可直接引用。
- 资料处理：三个数字全部登记为 `unresolved`，资料中不出现"测试通过 N 个"的结论；CI 门禁只描述**步骤名与命令**（那是 `confirmed` 的）。
- 状态：`open`

## Q-06 `RAG_MIN_SCORE` / `CHUNK_SIZE` / `TOP_K` / `LONG_TERM_MEMORY_COLLECTION` 是死配置
- 证据：`src/settings.py:106-110` 定义 `CHUNK_SIZE=1000`、`CHUNK_OVERLAP=200`、`TOP_K=20`、`RAG_MIN_SCORE=0.10`；但 `src/services/rag_service.py:244` 调 `retrieve()` 时从不传 `min_score`（默认 0.0）；切分实际值来自 `src/worker/tasks.py:95-107` 的 doc/kb 配置或硬编码 1000/200；`LONG_TERM_MEMORY_COLLECTION="user_memory"`（`src/settings.py:195`）全 src 无引用。
- 影响：用户改这几个环境变量**不会改变行为**，属"看起来能配、实际无效"，是很常见的误判源。
- 资料处理：作为 RULE-RAG 的一条明确规则写出"这些配置项当前不生效"；标 `observed`。
- 状态：`resolved_in_docs`

## Q-07 助手 `rag_config` 写入但从不被读取
- 证据：`src/api/routers/chat.py:138` 把 `assistant.rag_config` 透传给 `rag_service.query(assistant_config=...)`；`src/services/rag_service.py:84-103` 只读 `system_prompt/agent_ids/agents/llm_model/temperature/memory_config`，**从不读 `rag_config`**。
- 影响：助手里配的 `top_k` / `enable_rerank` 全部无效；用户会以为调优生效了。
- 资料处理：assistant-agent 模块正文与 unresolved 清单双写。
- 状态：`resolved_in_docs`（资料已写明），但**是否要修是产品决定** → `open`

## Q-08 长期记忆是空实现
- 证据：`src/services/memory_service.py:71-73` `add_long_term_memory` 函数体只有 `pass`；`:75-76` 的读取实为对 `rag_documents_v2` 做通用向量检索（返回的是文档片段，不是用户画像）；`src/services/rag_service.py:100-103` 的 `enable_long_term` 分支只打一条 logger.info，`long_term_context` 恒为空串。
- 影响：任何"支持长期记忆/用户偏好"的说法都不成立。
- 资料处理：标 `observed` 事实 + 明确"未实现"。
- 状态：`resolved_in_docs`

## Q-09 对象存储下载/预览在前端会 401（真实可用性缺口）
- 证据：`frontend/src/views/Monitor.vue:309,329` 用 `window.open` / `iframe` 直连 download/preview；`src/api/routers/storage.py:63,99` 两端点都 `Depends(get_current_user)`。浏览器无法给 `window.open` 附加 Authorization 头。
- 影响：文件下载与预览在真实浏览器里很可能直接 401 —— 这是**前端可用性缺陷**，不是后端 bug。
- 资料处理：storage-queue 正文"异常/恢复"单列；用例用 `controlled_fixture` 或 `static_review` 记录；标 `observed`。
- 状态：`open`（需产品决定修法：带 token 的临时 URL / cookie 会话 / fetch+blob）

## Q-10 monitor 删除任务前端传字符串，后端强制 int
- 证据：`frontend/src/views/Monitor.vue:213,225` 传 `row.task_id`（可能为 Celery UUID 字符串）；`src/api/routers/monitor.py:116-119` 路径参数按 int 处理。
- 影响：删除/批量删除可能 422。
- 资料处理：登记为 risk；用例预期写"若 task_id 为 UUID 则 422（未核实实际值类型）"。
- 状态：`open`（未核实后端 task_id 字段实际是 int 还是 str → 降级为 `unresolved`）

## Q-11 评测打分是自研 LLM-as-Judge，不是 RAGAS；无 Recall 维度
- 证据：`src/services/evaluator.py:17-47` 自实现 prompt + JSON 解析，四维度 faithfulness/relevancy/context_precision/accuracy（各 0-10），**无 recall**；`src/` 内 grep 无 ragas 引用；`requirements.txt:159` 与 `scripts/run_ragas_eval.py:41-44` 才有 ragas（离线脚本用）。
- 影响：README 的"基于 RAGAS""召回率"会让人误判评测能力与可比性。
- 资料处理：evaluation 正文明确"自研 LLM-as-Judge"，`unresolved`：与业界 RAGAS 指标是否可比未核实。
- 状态：`resolved_in_docs`

## Q-12 评测解析脆弱：`re.search(r'\{.*\}')`
- 证据：`src/services/evaluator.py:50-53` 用贪婪正则抓第一个 `{` 到最后一个 `}` 再 `json.loads`；失败返回 `{"error": ...}`。
- 影响：模型输出含多个 JSON 对象或带解释文字时会解析失败，而失败被静默吞成 error 字段 → 指标缺失但不报错。
- 资料处理：登记为 risk，用例预期写"模型返回不符合 JSON 契约时该项指标应为 error 而非静默 0 分（未核实）"。
- 状态：`open`

## Q-13 HITL_TTL_SECONDS=600 无消费者
- 证据：`src/settings.py:189` 声明 `HITL_TTL_SECONDS=600`；`src/` 内无任何读取点。
- 影响：HITL 挂起的**超时自动清理并未实现**，挂起线程会一直等（内存 checkpointer 下重启即丢）。
- 资料处理：aiops-diagnosis 正文写"挂起无超时机制"，标 `observed`。
- 状态：`resolved_in_docs`

## Q-14 `ENABLE_SUPERVISOR` 端点未实现
- 证据：全仓仅 `src/settings.py:184-185` 两行（注释 + `bool = False`）；`src/main.py:255-265` 挂载的 11 个 router 内无 supervisor。
- 影响：任何"多智能体 Supervisor"能力描述都不成立。
- 资料处理：`unresolved` 级"仅开关与注释"；资料不写该能力。
- 状态：`resolved_in_docs`

## Q-15 默认配置下 AIOps 不可跨重启恢复
- 证据：`src/agent/aiops/graph.py:106` 默认 `MemorySaver()`；`:148-156` 持久 AsyncSqliteSaver 仅在 managed_run 时启用；`:348-353` `managed_run = ENABLE_HITL or TERMCP_ENABLED or PROBE_ENABLED`，三者默认全 False（`src/settings.py`）。
- 影响：默认部署下诊断进程崩溃/重启 = 运行丢失，且**不会建 `aiops_runs` 记录**（意味着审计端点大面积 404）。
- 资料处理：aiops-diagnosis 与 aiops-audit 正文都要先讲这个前提；用例预置条件必须写明。
- 状态：`resolved_in_docs`

## Q-16 事件类型文档漏列
- 证据：`src/api/routers/aiops.py:47-53` docstring 只列 plan/step_complete/report/complete/error 5 种；实际还有 status/draft/pending_review/evidence（`src/agent/aiops/events.py:66-85`）+ usage（路由层直出）+ pending_terminal_approval（graph 层直出）= 11 种。
- 影响：照 docstring 写前端消费逻辑会漏掉一半事件。
- 资料处理：规格里列全 11 种并标"文档与实际不一致"。
- 状态：`resolved_in_docs`

## Q-17 `evidence` 事件不带 raw_hash
- 证据：`src/agent/aiops/events.py:316-320` `make_evidence_event` 接收 `raw_hash` 参数但未写入事件体。
- 影响：前端无法用 SSE 事件校验证据完整性，只能事后查库。
- 资料处理：aiops-audit 规格标 `observed` 缺口。
- 状态：`open`

## Q-18 `aiops_runs.status` 注释漏 `pending_terminal`
- 证据：`src/database/models.py:276` 注释列 `running / pending_review / approved / rejected / completed / failed`（6 个）；`src/agent/aiops/run_store.py:25-31` 实际 7 个常量，含 `pending_terminal`。
- 影响：按注释写状态机判断会漏掉终态审批分支。
- 资料处理：状态图以 run_store 为准并注明注释未更新。
- 状态：`resolved_in_docs`

## Q-19 `query.py` / `tasks.py` 是死路由
- 证据：`src/api/routers/query.py:18`（`POST /chat`）、`src/api/routers/tasks.py:9`（`GET /{task_id}`）；`src/main.py:255-265` 的 include_router 列表里没有它们。
- 影响：这两个端点不可达；前端也因此无法查 Celery 任务状态。
- 资料处理：列入"已实现但未挂载"，不写进任何 feature 的可用入口。
- 状态：`resolved_in_docs`

## Q-20 `data/vectors` 已有 1536→1024 维迁移痕迹
- 证据：`data/vectors/` 内 `vectors.npy` 71.8MB、`vectors_meta.json` 20.3MB，另存 `.1536.bak` 备份；`src/settings.py:87` 现 `MILVUS_DIMENSION=1024`。
- 影响：说明该降级存储**真实在用**（否则不会这么大），也说明历史向量维度变更过一次；旧数据是否已被完整重建**未核实**。
- 资料处理：登记为"降级路径在用的间接证据"，属 `observed` 推断；不做进一步结论。
- 状态：`spec_gap`

## Q-21 依赖在线状态全部未核实
- 缺口：Milvus(19530)/Redis/RabbitMQ/MinIO/Elasticsearch/Celery worker/MCP 服务，本轮**禁止联网与外起服务**，无法确认在线。
- 影响：所有"依赖缺失则降级"的断言只能是 `observed(代码路径)`，不能是"实测降级有效"。
- 资料处理：所有相关断言 `basis: observed` + `readiness: ready`（资料完整度够），但 evaluation 时只能记 OBSERVED，不能记 PASS。
- 状态：`spec_gap`

## Q-22 `docker-compose.yml` 的 minio 镜像非同官方
- 证据：`docker/docker-compose.yml:142` 使用 `pgsty/silo:...` 而非 `minio/minio`。
- 影响：是否能等价提供 MinIO API 未核实；若不等价，compose 起的环境里 storage 会降级。
- 资料处理：登记 `unresolved`，不写进任何"已验证部署"结论。
- 状态：`open`

## Q-23 `docs/configuration-fields-20261027.md` 列 132 项，`settings.py` 实测 136 个字段
- 证据：`docs/README.md` 提到该文档覆盖 132 项；本次用脚本实测 `src/settings.py` 的 `Settings` 类字段 **136 个**，且根目录 `.env.example` 恰好 **136 键**、两边完全一致（早前记的"113 个字段"是人工目测偏小的估值，已按实测更正）。
- 影响：配置文档（132）与代码（136）差 4 项，差值来源未逐项定位（可能新增字段后未回填文档）。
- 资料处理：`requirements/modules/platform.md` 的 REQ-PLAT-003 按 **136** 写并注明 `.env.example` 与之对齐；差值本身登记为 `spec_gap`，不猜是哪 4 个。
- 状态：`spec_gap`

## Q-24 `AGENTS.md` 前 94 行是历史流水
- 证据：`AGENTS.md` 正文前 94 行倒序追加的逐日进展（含 commit、证据目录、passed/failed、模型调用次数与费用），文档自身反复强调"历史时点""原失败不回写"。
- 影响：直接引用这些数字当"当前验收结论"会出错（且与 handover 文档的现状口径不同）。
- 资料处理：一律标注历史时点，不参与任何当前结论；当前现状只引 `docs/aiops-goal-handover-20261108.md`。
- 状态：`resolved_in_docs`

## Q-25 AIOps 验收口径存在多个分母
- 证据：`docs/aiops-goal-handover-20261108.md` 明确分阶段口径：含全部 15 轮 **10/15**；修复一后(040–050) **7/11**；修复二后(042–050) **6/9**；修复三后(050) **0/1**；最长连续通过 042、043（2 轮）与 045–048（4 轮）。
- 影响：说"通过率 67%"或"通过率 0%"都能被单一口径支持，**必须带分母与区间**。
- 资料处理：所有涉及通过率的断言必须写全"哪个区间/多少轮/几通过"，标 `confirmed`（文档明确决定的口径）。
- 状态：`resolved_in_docs`

## Q-26 费用口径不能说成账单
- 证据：handover 明确 9.611526 元是**新增预留/峰值上界**而非账单；账本有 61 行无 `pricing_verified`、第 710 行 usage 未知，故 `cumulative_actual_cost="unknown"`。
- 影响：任何"真实花费 9.6 元"的表述都是错的。
- 资料处理：涉及费用的断言只写"预留上界"，actual 标 unknown。
- 状态：`resolved_in_docs`

## Q-27 原始 SSE 未留证
- 证据：handover 记 `raw_sse_frames_persisted=false`；轨迹靠 checkpoint + 工具调用 + 模型输入 + 账本重建。
- 影响：不能声称"有完整前端链路录像"，只能声称"可由 checkpoint 重建"。
- 资料处理：aiops 模块"可观察结果"一节写清证据来源边界。
- 状态：`resolved_in_docs`

## Q-28 `/steps` 端点存在但默认无数据
- 证据：`src/api/routers/aiops.py:169` 端点已实现；`src/settings.py:154` `ENABLE_STEP_SNAPSHOTS=False` → 表里不写行 → 实测 `total:0`（handover 记录各轮均为 0）。
- 影响：这是"已实现 ≠ 已启用"的典型；按端点存在就断言"有步级回放能力"会错。
- 资料处理：用例预期写"默认 total=0；开启快照后才有数据（开启后行为未核实）"。
- 状态：`resolved_in_docs`

## Q-29 `assets` 类小缺口汇总（单条不值得建独立 issue）
- `frontend/src/App.vue:105` 判断 `/register` 页，但 router 无该路由（只在 Login.vue 内 `isRegister` 切换）。
- `src/api/routers/health.py` 的 `GET /models` 无鉴权，返回 `AVAILABLE_MODELS`（模型清单对外可见）。
- `src/api/routers/loadfile.py`（Legacy `/upload`）与 `POST /agents/{id}/execute` **前端无任何调用方**。
- `src/api/middleware/`、`src/api/models/`、`src/api/dependencies/`（目录）为空，中间件全写在 `main.py`。
- 注册端点无限流，只有登录限流 5/minute。
- 全部 `observed`，资料处理为"已实现无入口/无边界的说明"，不写成缺陷结论。
- 状态：`resolved_in_docs`

## Q-30 `src/services/pdf_processor.py` 与主链路的重复实现
- 证据：`src/services/pdf_processor.py:17-67` 只写 Milvus、不写 SQL、不走 Celery，与 `src/worker/tasks.py` 的主链路并行；`ParentChildChunker` / `TextCleaner` / `MetadataExtractor` 仅被 `src/processors/__init__.py:4-11` 导出，无业务调用方。
- 影响：存在两套文档摄取实现，容易误读"哪个是真的"。
- 资料处理：kb-ingest 正文明确"主链路是 worker/tasks.py；pdf_processor 是 loadfile 遗留链路"。
- 状态：`resolved_in_docs`

---

## Q-31 `AiopsApproval` 表无写入方 → `approved`/`rejected` 状态永不可达
- 证据：`src/agent/aiops/run_store.py:98-131` 定义了 `mark_approved` / `mark_rejected` / `add_approval`，但全仓**无任何调用点**（`src/agent/aiops/graph.py` 只调 `create_run` / `mark_pending_*` / `mark_completed` / `mark_failed` / `get_run`）。
- 影响：run 状态机里 `approved` / `rejected` 两个状态**无法进入**，`aiops_approvals` 表**永远为空**；用户可观察到的现象是状态永远停在 `pending_review` 或 `pending_terminal`。`POST /runs/{thread_id}/continue` 走的是 terminal 分支，不写 approvals 表。
- 需要的决定：是否补 HITL 审批端点（写 approvals 表并推进状态）。属产品决定，不是缺陷修复。
- 资料处理：`REQ-AUDIT-002`（运行状态 7 个）与 `REQ-DIAG-011`（HITL 无 HTTP 审批入口）双写；`REQ-AUDIT-009`「审计面四个空洞」把它列为空洞之一。
- 状态：`open`（建议 critical）

## Q-32 `docs/aiops-run-store.md` 与代码对"何时建 run"的判定不一致
- 证据：文档 `docs/aiops-run-store.md:23`、`:47` 说"仅在 `ENABLE_HITL=true` 时创建 run"；代码是 `managed_run = settings.ENABLE_HITL or settings.TERMCP_ENABLED or settings.PROBE_ENABLED`（`src/agent/aiops/graph.py:348`）三开关任一。
- 影响：照文档判断会出现"默认配置下以为没有 run 记录"的误读（实际是三个都关才没有）。
- 资料处理：需求按文档写、实现状态记代码事实，冲突已双写于 `REQ-AUDIT-001`。
- 状态：`resolved_in_docs`（口径以代码为准，文档待改）

## Q-33 `POST /runs/{thread_id}/continue` 无 reject 分支
- 证据：`src/api/routers/aiops.py:156` 写死 `decision = {"action": "approve"}`；平台内**无法表达驳回**。Termcp 侧驳回只能靠 `verify_terminal_approval` 第 7 条（`src/agent/aiops/termcp_tools.py:79`，HTTP 410）兜住。
- 影响：Termcp 命令审批是"只能批准"的单向门；要驳回只能等审批过期（由 expires_at 触发）。
- 资料处理：`REQ-DIAG-012` 写明"续跑只走 approve"；`ASRT-DIAG-*` 中涉及驳回的断言标 `controlled_fixture`。
- 状态：`open`

## Q-34 前端不渲染 `usage` / `draft` / `pending_review` 三类事件
- 证据：`frontend/src/views/AIOps.vue:715-792` 的 `handleEvent` 无 `draft` / `pending_review` 分支（落入 default 静默忽略）；全文无 `usage` / `cost_cny` / `llm_calls` 渲染。
- 影响：开启 `ENABLE_HITL` 后前端界面**完全没有挂起提示**；费用数据只存在于 SSE 帧里，用户看不到。是"刻意不展示"还是"未做"，未核实。
- 资料处理：`REQ-DIAG-013` 标题即写"后端一定会推，前端一定不显示"；用例预期按"帧里有、界面没有"写。
- 状态：`open`

## Q-35 `auditor` 角色不在模型注释里
- 证据：`src/database/models.py:14` 的角色注释只写 `admin, user, editor`；但 `src/api/routers/aiops.py:190,198` 的判定集合是 `{"admin","auditor"}`。
- 影响：注释遗漏还是角色设计变更未核实；由于无任何授予 `admin`/`auditor` 的代码路径（见 Q-36 关联缺口），这两类能力实际不可达。
- 资料处理：`REQ-AUDIT-006`、`RULE-AUTH-*` 按代码判定集合 `{"admin","auditor"}` 写，并注明"无授予路径"。
- 状态：`open`（建议 low）

## Q-36 `aiops_runs.degraded` 列无写入方
- 证据：`src/database/models.py:280` 定义 `degraded String(64)`；`grep -rn "degraded" src/` 只命中这一行列定义本身，无任何赋值点 → **恒为 NULL**。
- 影响：想靠该列判断"本轮是否降级运行"不可行，只能从报告 `degraded` 字段与降级事件推。
- 资料处理：不写"有降级标记可查"这类结论；`REQ-DIAG-008` 的降级说明只引报告与事件。
- 状态：`open`（建议 low）

## Q-37 证据文件与 `aiops_evidence` 行无清理机制
- 证据：`data/aiops-evidence/` 与 `aiops_evidence` 行**永久累积**；对比 `ProbeSnapshot` 有 24h TTL（`src/agent/aiops/run_store.py:319` 写 `expires_at=collected_at+timedelta(hours=24)` 且写入即清理过期行）。
- 影响：长期运行时证据目录会持续增长；审计数据的"哪些会自己过期"存在不对称（探针基线会过期，证据不会）。
- 资料处理：`REQ-AUDIT-010` 如实写"探针基线 24h，证据文件不自动清理"。
- 状态：`open`

## Q-38 `GET /targets/{id}/status` 不校验 run 归属
- 证据：`src/api/routers/aiops.py:209-218` 是 aiops 路由里**唯一不经过 `_owned_run`** 的端点——任何登录用户都能查探针在线状态（只校验 `target_id == settings.PROBE_TARGET_ID`）。
- 影响：有意便利（探针是整机级资源，非用户私有）还是权限过宽，未核实。
- 资料处理：`RULE-AUDIT-012`（target_id 三段校验）如实写校验链，不判是否越权。
- 状态：`open`（建议 low）

## Q-39 探针网关需要外部启动，自身无入口
- 证据：`mcp_servers/probe_gateway.py` 全文件无 `uvicorn.run` / `__main__`（`:311` 注释仅提及 Uvicorn socket）。
- 影响：`/targets/{id}/status` 的数据来源可能整段为空——网关没起就没有 `probe_snapshots` 行；且该模块的在线状态本任务无法核实（见 Q-21）。
- 资料处理：`overview.md` 服务入口表把 probe_gateway 列为"需外部启动"；`REQ-AUDIT-008` 的读数前提写明"网关已启动且探针已连通"。
- 状态：`open`

---

## 汇总

| 状态 | 条数 | 编号 |
|---|---|---|
| `open`（需产品决定/未核实） | 14 | Q-05, Q-09, Q-10, Q-12, Q-17, Q-22, Q-31, Q-33, Q-34, Q-35, Q-36, Q-37, Q-38, Q-39 |
| `spec_gap`（资料缺口） | 4 | Q-04, Q-20, Q-21, Q-23 |
| `resolved_in_docs`（资料内已按代码口径处理） | 21 | Q-01, Q-02, Q-03, Q-06, Q-07, Q-08, Q-11, Q-13, Q-14, Q-15, Q-16, Q-18, Q-19, Q-24, Q-25, Q-26, Q-27, Q-28, Q-29, Q-30, Q-32 |

**对读者最重要的一条**：本项目的文档（README/`docs/api.md`）与代码存在多处系统性偏差，**资料一律以提交 `bf789d9` 的源码为事实源**；文档只用于捕捉"作者意图/产品决定"，不用于捕捉"当前实现"。

另有 **88 条执行条件型未决**（不是冲突，不需要产品决定），按模块写在 `requirements/modules/<module>.md` 的「未决」一节：需要 `controlled_fixture`、需要真实等待（如 180s 探针新鲜度）、需要付费授权（产生模型费用的用例已逐条标 `resource_requirements`）、或依赖外部服务在线状态。这些不进 questions.md，因为它们不影响正文口径。
