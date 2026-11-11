# spec · rag-qa（检索与问答）

- 模块：`rag-qa`，规则前缀 `RULE-RAG-`，断言前缀 `ASRT-RAG-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 需求依据：`requirements/modules/rag-qa.md`（REQ-RAG-001 ~ REQ-RAG-010）
- 所有 `source` 为 `完整相对路径:行号`。`basis=observed` = 读源码核实。
- 本模块**没有** `confirmed` 级断言：`requirements/project-card.md` 里的 D1–D10 是项目级决定，未直接约束本模块单条行为。
- 流程引用：`FLOW-RAG-QUERY`（提问 → 意图路由 → 检索 → 重排 → 生成 → 来源回传），流程正文与流程图见 `requirements/modules/rag-qa.md:17`。

---

## 1. 交互与接口状态

### 1.1 两个问答入口

| 用户动作 | 前端判定 | 接口 | 输出 | source |
|---|---|---|---|---|
| 直接输入问题（未选助手/知识库） | `!selectedAssistant && !selectedKB` | `POST /api/v1/chat/stream` | SSE，逐 token | `frontend/src/views/Chat.vue:340-343`、`src/api/routers/chat.py:210` |
| 选了助手或知识库后提问 | else 分支 | `POST /api/v1/chat/` | 一次性 JSON | `frontend/src/views/Chat.vue:345-358`、`src/api/routers/chat.py:64` |

### 1.2 请求/响应契约

**请求**（`ChatRequest`，`src/api/routers/chat.py:22-40`）
- `query: str`（必填）
- `session_id: Optional[str]`
- `kb_id: Optional[int]`
- `assistant_id: Optional[int]`
- `top_k: int = 5`，约束 `1 <= top_k <= 50`
- `llm_model: Optional[str]`，必须属于 `settings.AVAILABLE_MODELS`，否则 422 且 detail 含 `不支持的模型: {v}`

**响应**（`ChatResponse`，`src/api/routers/chat.py:164-169`）
```json
{"session_id":"...","query":"...","answer":"...","source_documents":[{"id":"...","text":"...","score":0.0,"metadata":{}}]}
```
`source_documents` 的来源与结构见 `src/services/rag_service.py:337-350`。

### 1.3 会话接口

| 动作 | 接口 | source |
|---|---|---|
| 建会话 | `POST /api/v1/chat/sessions` | `src/api/routers/chat.py:283` |
| 列会话 | `GET /api/v1/chat/sessions` | `src/api/routers/chat.py:312` |
| 列消息 | `GET /api/v1/chat/sessions/{session_id}/messages` | `src/api/routers/chat.py:319` |
| 删会话 | `DELETE /api/v1/chat/sessions/{session_id}` | `src/api/routers/chat.py:333` |
| 批量删 | `DELETE /api/v1/chat/sessions`（body `List[str]`） | `src/api/routers/chat.py:358` |

### 1.4 功能单元（FEAT-RAG-\*，供 `cases/rag-qa.json` 的 `feature_id` 解析）

| feature_id | 用户目标 | 主入口 | requirement_refs | 源码锚点 |
|---|---|---|---|---|
| FEAT-RAG-001 | 分两种方式提问（纯聊天流式 / 带知识库同步） | `/chat` 页输入框 | REQ-RAG-001 | `frontend/src/views/Chat.vue:331-427`、`src/api/routers/chat.py:64-278` |
| FEAT-RAG-002 | 意图识别与分支路由 | `RAGService.query` | REQ-RAG-002 | `src/services/rag_service.py:15-153` |
| FEAT-RAG-003 | 混合检索与 RRF 融合 | `HybridRetriever.retrieve` | REQ-RAG-003 | `src/retrieval/hybrid_retriever.py:22-193` |
| FEAT-RAG-004 | 重排序与降级 | `DashScopeReranker.rerank` | REQ-RAG-004 | `src/retrieval/reranker.py:14-55` |
| FEAT-RAG-005 | 生成、来源回传与界面渲染 | `/chat/` 响应 + 前端来源块 | REQ-RAG-005 | `src/services/rag_service.py:230-356`、`frontend/src/views/Chat.vue:96-103` |
| FEAT-RAG-006 | 多跳问答 | `_multi_hop_query` | REQ-RAG-006 | `src/services/rag_service.py:294-335` |
| FEAT-RAG-007 | 助手配置的保存与（不）生效 | `/chat` 左侧助手面板 | REQ-RAG-007 | `frontend/src/views/Chat.vue:24-27,170-209`、`src/services/rag_service.py:84-92` |
| FEAT-RAG-008 | 会话管理与短期记忆 | 会话列表 | REQ-RAG-008 | `src/api/routers/chat.py:283-374`、`src/services/memory_service.py:30-69` |
| FEAT-RAG-009 | 知识库可见性与权限边界 | `POST /chat/` 的 kb 过滤 | REQ-RAG-009 | `src/api/routers/chat.py:74-94` |
| FEAT-RAG-010 | 模型白名单与失败可见性 | 模型下拉 + 错误路径 | REQ-RAG-010 | `src/api/routers/chat.py:22-40`、`src/llm/llm_client.py:17-25,100-282` |

---

## 2. 规则

### RULE-RAG-001 未选助手且未选知识库才走流式
- **要求**：前端必须在 `!selectedAssistant && !selectedKB` 时才调 `/chat/stream`；一旦选了助手或知识库，必须调同步 `/chat/`。
- **适用条件**：`/chat` 页「发送」按钮或回车。
- **可观察**：Network 中该请求的 URL 与响应形态（SSE 事件流 vs 单个 JSON）。
- **source**：`frontend/src/views/Chat.vue:331-374`
- **requirement_refs**：REQ-RAG-001　**basis**：observed

### RULE-RAG-002 `/chat/stream` 是纯聊天，不检索
- **要求**：`/chat/stream` 不得使用知识库、不得返回 `source_documents`；其实现只调用 `generate_general_response_stream`。
- **适用条件**：`POST /chat/stream`。
- **可观察**：SSE 事件只有 `{"type":"token"}` 与 `{"type":"done","session_id":…}`；转发给 LLM 的只有 query + 短期记忆，无检索片段。
- **source**：`src/api/routers/chat.py:210-278`（docstring 明写 `:216-221`）
- **requirement_refs**：REQ-RAG-001　**basis**：observed

### RULE-RAG-003 同步 RAG 路径不得有流式/占位反馈
- **要求**：`POST /chat/` 内部必须同步阻塞执行（无 `run_in_threadpool`），响应一次性返回；前端在等待期间**不得**插入 assistant 占位气泡。
- **适用条件**：带 assistant_id 或 kb_id 的问答。
- **可观察**：响应 `Content-Type: application/json`（非 `text/event-stream`）；前端 DOM 在等待期间只有 user 气泡。
- **source**：`src/api/routers/chat.py:144-150`（对比 `:243-247`）、`frontend/src/views/Chat.vue:335-358`
- **requirement_refs**：REQ-RAG-001　**basis**：observed

### RULE-RAG-004 意图规则层：短问候判 chat、诊断词判 diagnosis
- **要求**：`_quick_intent_check` 必须满足：`len(query) < 15` 且含 `_CHAT_PATTERNS` 任一词 → `chat`；含 `_DIAGNOSIS_PATTERNS` 任一词 → `diagnosis`（**无长度限制**）；都不含 → `None`（交 LLM）。
- **适用条件**：所有 `RAGService.query` 调用。
- **可观察**：`len("你好")<15` → chat（不检索，`source_documents=[]`）；`"连接超时"` 含 `超时` → diagnosis（即使问题本身在问手册）。
- **source**：`src/services/rag_service.py:15-46,107-117`
- **requirement_refs**：REQ-RAG-002　**basis**：observed

### RULE-RAG-005 LLM 意图判定失败一律回落 chat
- **要求**：`QuestionAnalyzer.analyze` 解析不出 JSON 或抛异常时，必须返回 `{"intent":"chat", …}`，不得抛出。
- **适用条件**：规则层未命中。
- **可观察**：模型返回畸形文本时，问答仍成功但走 `_general_chat`（`source_documents=[]`）。
- **source**：`src/services/question_analyzer.py:12-57`
- **requirement_refs**：REQ-RAG-002　**basis**：observed

### RULE-RAG-006 分派矩阵（intent × agent × kb）
- **要求**：必须严格按下表分派：

| intent | 有 agent | 有可用 kb | 分支 |
|---|---|---|---|
| chat | — | — | `_general_chat` |
| knowledge | — | 是 | `_rag_path` |
| knowledge | — | 否 | `_general_chat` |
| diagnosis | 是 | — | `_agent_path` |
| diagnosis | 否 | 是 | `_rag_path` |
| diagnosis | 否 | 否 | `_general_chat` |
| 其他/缺失 | — | — | `_general_chat` |

- **适用条件**：`RAGService.query`。
- **可观察**：`_general_chat` 返回 `source_documents=[]`；`_rag_path` 返回非空（有命中时）；`_agent_path` 返回 `source_documents=[]`（尽管检索过）。
- **source**：`src/services/rag_service.py:125-153,172,223-228`
- **requirement_refs**：REQ-RAG-002　**basis**：observed

### RULE-RAG-007 混合检索：向量与 BM25 各取 top_k*2，RRF 常数 60
- **要求**：两路都非空时必须用 `1.0/(60+rank)` 累加融合，按融合分排序取 top_k；不得用加权求和。
- **适用条件**：`HybridRetriever.retrieve`，且 BM25 与向量都可用。
- **可观察**：同一 chunk 在两路中排名靠前时被排到最前；返回项的 `score` **不是** RRF 分（是原始分），因此数值可能 >1 或与排序不一致。
- **source**：`src/retrieval/hybrid_retriever.py:22-61,151-193`
- **requirement_refs**：REQ-RAG-003　**basis**：observed

### RULE-RAG-008 单路可用时退化为单路 top_k
- **要求**：BM25 无结果 → 只返回向量 top_k；向量无结果 → 只返回 BM25 top_k；两路皆空 → 返回 `[]`。
- **适用条件**：同上。
- **可观察**：两路皆空时 `/chat/` 仍 200，答案按 prompt 要求答复"根据提供的信息无法回答"，`source_documents=[]`。
- **source**：`src/retrieval/hybrid_retriever.py:180-193`
- **requirement_refs**：REQ-RAG-003　**basis**：observed

### RULE-RAG-009 BM25 索引进程内只建一次，不随新文档刷新
- **要求**：`_ensure_bm25_indexed` 必须在 `_bm25_populated or bm25.is_indexed` 时短路；建索引用 `WHERE kd.status = 2` 全量读；建索引失败需置 `_bm25_populated=True` 阻止重试；`index_bm25_chunks()` 不得在摄取链路被调用。
- **适用条件**：混合检索路径。
- **可观察**：**服务启动后先做一次问答**，再上传新文档至 `status=2`，同一个问题里该新文档的纯字面内容**不会**出现在 BM25 侧；但用 `POST /knowledge-bases/{kb_id}/search`（现场重建索引）能命中。
- **source**：`src/retrieval/hybrid_retriever.py:79-149`、`src/retrieval/bm25_retriever.py:43`（docstring "增删文档后需重新建索引"）
- **requirement_refs**：REQ-RAG-003　**basis**：observed

### RULE-RAG-010 中文分词为 2-gram 滑窗，不是 jieba
- **要求**：`_tokenize` 必须对中文串做相邻 2-gram 滑窗（单字保留），非中文按 `[^a-z0-9]` 切并丢弃长度 1。
- **适用条件**：BM25 建索引与查询。
- **可观察**：查询"连接拒绝"不会作为一个整体词命中；包含"连接"或"拒绝"二元组的 chunk 才命中。
- **source**：`src/retrieval/bm25_retriever.py:22-37`
- **requirement_refs**：REQ-RAG-003　**basis**：observed

### RULE-RAG-011 重排是真实在线调用，失败静默截断
- **要求**：`ENABLE_RERANK=True` 时必须调 `dashscope.TextReRank.call`；HTTP 200 用 `relevance_score` 覆盖 score 并按返回顺序；非 200 或异常时截断为 `documents[:top_n]` 且不报错。
- **适用条件**：`_single_hop_query` / `_multi_hop_query` / `_agent_path` 的 rerank 调用点。
- **可观察**：正常时 `source_documents[].score` 落在 0–1 相关性语义；网络故障时问答仍 200，score 变为原始检索分。
- **source**：`src/retrieval/reranker.py:14-55`、`src/settings.py:113-115`
- **requirement_refs**：REQ-RAG-004　**basis**：observed

### RULE-RAG-012 重排开启时候选取 top_k*2
- **要求**：`ENABLE_RERANK` 为真时 `initial_k = top_k*2`，否则 `initial_k = top_k`。
- **适用条件**：`_single_hop_query`。
- **可观察**：默认配置（`ENABLE_RERANK=True`、前端不传 top_k）下，检索阶段取 10 条候选，重排后输出 ≤ 5 条。
- **source**：`src/services/rag_service.py:241`
- **requirement_refs**：REQ-RAG-004　**basis**：observed

### RULE-RAG-013 生成 prompt 的五条硬约束
- **要求**：RAG prompt 必须包含：不添加外部知识、无相关信息时明确答复"根据提供的信息无法回答"、引用相关段落编号、准确简洁、Markdown 输出。
- **适用条件**：`_single_hop_query` / `_multi_hop_query`。
- **可观察**：给出与知识库无关的问题时，答案应含"根据提供的信息无法回答"字样（依赖模型服从性，属 graded/人工判定）。
- **source**：`src/services/rag_service.py:267-281`、`src/llm/llm_client.py:176-212`
- **requirement_refs**：REQ-RAG-005　**basis**：observed

### RULE-RAG-014 来源必须回传，且 metadata 含文件名与页码
- **要求**：`_rag_path` 返回的 `source_documents` 每项含 `id/text/score/metadata`，metadata 由写入侧带 `doc_id/kb_id/filename/text` 与 `page`。
- **适用条件**：`_rag_path`。
- **可观察**：响应 JSON 中 `source_documents[].metadata.filename` 与 `.page` 非空。
- **source**：`src/services/rag_service.py:337-350`、`src/worker/tasks.py:182-193`
- **requirement_refs**：REQ-RAG-005　**basis**：observed

### RULE-RAG-015 界面来源块只显示前 50 字与相关度
- **要求**：`Chat.vue` 的来源渲染必须只输出 `text.substring(0,50)` 与 `score.toFixed(2)`，**不显示** filename/page。
- **适用条件**：前端收到非空 `source_documents`。
- **可观察**：DOM 中"参考来源："后每行形如 `xxx...（相关度：0.87）`，无文件名/页码字样。
- **source**：`frontend/src/views/Chat.vue:96-103`
- **requirement_refs**：REQ-RAG-005　**basis**：observed

### RULE-RAG-016 诊断路径固定返回空来源
- **要求**：`_agent_path` 的返回必须写死 `source_documents: []`，即使它已把检索结果拼进增强 query。
- **适用条件**：intent=diagnosis 且有 agent。
- **可观察**：响应 `source_documents` 为 `[]`；但 LLM 的回答里可能出现知识库内容（`【知识库参考资料】`）。
- **source**：`src/services/rag_service.py:196-228`
- **requirement_refs**：REQ-RAG-002, REQ-RAG-005　**basis**：observed

### RULE-RAG-017 多跳上限 MAX_HOP=3，结果按 id 去重
- **要求**：必须满足 `analysis and ENABLE_MULTI_HOP and analysis.is_multi_hop` 才走多跳；`steps = sub_queries[:3]`；合并结果按 `id` 去重。
- **适用条件**：`_rag_path`。
- **可观察**：`source_documents` 中无重复 `id`；单次问答最多 3 个子查询。
- **source**：`src/services/rag_service.py:174-194,294-335`、`src/settings.py:127-128`
- **requirement_refs**：REQ-RAG-006　**basis**：observed

### RULE-RAG-018 助手 rag_config 不被读取
- **要求**：`RAGService.query` 只允许读 `system_prompt / agent_ids / agents / llm_model / temperature / memory_config`；**不得**读 `rag_config`。`top_k` 只能来自 `ChatRequest.top_k`（默认 5），rerank 只能受 `settings.ENABLE_RERANK` 控制。
- **适用条件**：带 `assistant_id` 的问答。
- **可观察**：把助手 `rag_config.top_k` 从 5 改成 20、`enable_rerank` 改为 false 后，同一问题的 `source_documents` 数量与顺序**不变**（在检索结果稳定的前提下）。
- **source**：`src/services/rag_service.py:84-92`、`src/api/routers/chat.py:22-40,133-142`、`src/database/models.py:188`
- **requirement_refs**：REQ-RAG-007　**basis**：observed

### RULE-RAG-019 无效知识库静默丢弃
- **要求**：`valid_kb_ids` 只保留 `owner_id == current_user.id` 或 `is_public=True` 的库；被过滤掉时**不得**返回 4xx。
- **适用条件**：所有带 kb 的问答。
- **可观察**：传他人私有库 id → HTTP 200，答案走 `_general_chat`（`source_documents=[]`），无任何错误提示。
- **source**：`src/api/routers/chat.py:89-94`
- **requirement_refs**：REQ-RAG-009　**basis**：observed

### RULE-RAG-020 助手权限：404 与 403 分治
- **要求**：`assistant_id` 不存在 → 404 `Assistant not found`；存在但不属于当前用户 → 403。
- **适用条件**：带 `assistant_id`。
- **可观察**：两个不同的状态码。
- **source**：`src/api/routers/chat.py:74-80`
- **requirement_refs**：REQ-RAG-009　**basis**：observed

### RULE-RAG-021 模型白名单校验 + 内部兜底
- **要求**：`ChatRequest.llm_model` 不在 `settings.AVAILABLE_MODELS` 时 422，detail 含 `不支持的模型`；`LLMClient._get_llm` 对未白名单模型回落到默认模型（不报错）。
- **适用条件**：请求带 `llm_model`。
- **可观察**：422 的 detail 文案；若绕过接口层直接调 `LLMClient`，未知模型会静默使用默认模型。
- **source**：`src/api/routers/chat.py:22-40`、`src/llm/llm_client.py:100-140`、`src/settings.py:77-79`
- **requirement_refs**：REQ-RAG-010　**basis**：observed

### RULE-RAG-022 生成异常返回错误字符串而非抛错
- **要求**：`generate_response_with_metrics` / `generate_custom_response` 捕获异常后必须返回 `"Error generating response: {e}"`（metrics 为 0.0），**不得**抛给调用方。
- **适用条件**：LLM 调用失败且 fallback 也失败。
- **可观察**：HTTP 200，`answer` 字段以 `Error generating response:` 开头。
- **source**：`src/llm/llm_client.py:142-174,267-282`
- **requirement_refs**：REQ-RAG-010　**basis**：observed

### RULE-RAG-023 短期记忆窗口 10、TTL 3600、Redis 异常静默
- **要求**：`get_short_term_memory` 取 `lrange(0, limit-1)` 后 `reverse()`；写入 `lpush` + `ltrim(0, history_limit-1)` + `expire(ttl)`；Redis 异常时返回空列表并只记日志。
- **适用条件**：`enable_short_term` 为真（默认）。
- **可观察**：第 11 轮之前的对话内容不再进入 context；Redis 停机时问答仍可用（无历史）。
- **source**：`src/services/memory_service.py:30-69`、`src/settings.py:194-196`、`src/services/rag_service.py:91-92`
- **requirement_refs**：REQ-RAG-008　**basis**：observed

### RULE-RAG-024 删会话三步且不清向量
- **要求**：`DELETE /chat/sessions/{id}` 必须先删 `ChatInteraction`、再删 `ChatSession`、再清短期记忆（清缓存失败只 `print`）；不得删除向量数据。
- **适用条件**：会话 owner。
- **可观察**：删除后 `GET /sessions/{id}/messages` 返回 404 或空；`data/vectors/` 与 Milvus 无变化。
- **source**：`src/api/routers/chat.py:333-356`
- **requirement_refs**：REQ-RAG-008　**basis**：observed

### RULE-RAG-025 阈值过滤未生效
- **要求**：`RAG_MIN_SCORE` 必须不参与检索过滤；`retrieve(min_score=)` 使用默认 `0.0`；`_assess_retrieval_quality` 只写日志。
- **适用条件**：所有检索。
- **可观察**：即使检索结果的最高分很低（如 0.12），仍会进入 context 并出现在 `source_documents`（不被过滤）。
- **source**：`src/settings.py:110`、`src/retrieval/hybrid_retriever.py:156,191-192`、`src/services/rag_service.py:49-64,244`
- **requirement_refs**：REQ-RAG-003　**basis**：observed

### RULE-RAG-026 metrics 无对外出口
- **要求**：`result["metrics"]` 只存在于 `RAGService` 返回值内部；`chat.py` 落库时 `metrics` 必须写 `{}`，响应体不含 metrics。
- **适用条件**：`/chat/`。
- **可观察**：响应 JSON 无 `metrics` 键；`chat_interactions.metrics` 为 `{}`。
- **source**：`src/services/rag_service.py:282-288`、`src/api/routers/chat.py:153-162`
- **requirement_refs**：REQ-RAG-005　**basis**：observed

### RULE-RAG-027 长期记忆为空实现
- **要求**：`add_long_term_memory` 必须无副作用（仅 `pass`）；`retrieve_long_term_memory` 复用文档向量库；`enable_long_term` 为真时只记日志。
- **适用条件**：`memory_config.enable_long_term=True`。
- **可观察**：跨会话的"用户偏好记忆"不生效；开启开关后行为与关闭相同。
- **source**：`src/services/memory_service.py:72-76`、`src/services/rag_service.py:100-103`
- **requirement_refs**：REQ-RAG-008　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
|---|---|---|---|---|
| ASRT-RAG-001 | `/chat` 页不选助手不选知识库、输入"你好"发送 → Network 出现 `POST /api/v1/chat/stream`，响应为 SSE（`text/event-stream`），**无** `POST /api/v1/chat/` | RULE-RAG-001 | REQ-RAG-001 | observed |
| ASRT-RAG-002 | 选中任一助手后输入同样问题 → Network 只出现 `POST /api/v1/chat/`，无 `/chat/stream`；响应为单个 JSON | RULE-RAG-001 | REQ-RAG-001 | observed |
| ASRT-RAG-003 | 直接 `curl POST /api/v1/chat/stream`（带 token，body `{"query":"你好"}`）→ 响应 `Content-Type` 含 `text/event-stream`，事件序列含 `{"type":"done","session_id":...}`，且**不含**任何 `source_documents` 字段 | RULE-RAG-002 | REQ-RAG-001 | observed |
| ASRT-RAG-004 | 带 `kb_id` 调 `POST /api/v1/chat/`，在响应到达前观察前端 DOM：只存在 user 气泡，无 assistant 占位气泡、无"检索中"字样 | RULE-RAG-003 | REQ-RAG-001 | observed |
| ASRT-RAG-005 | 问题 `"你好"`（len<15，含问候词）→ 响应 `source_documents` 为 `[]`，且无检索副作用（无 `[retrieval_quality]` 日志） | RULE-RAG-004 | REQ-RAG-002 | observed |
| ASRT-RAG-006 | 问题 `"连接超时"`（含诊断词 `超时`，len<15）必须被判为 diagnosis 而非 chat。分支取决于 Agent：**无 Agent 且传了可用 kb_id** → 落 `_rag_path`，`source_documents` **非空**；**有 Agent** → 落 `_agent_path`，`source_documents` 恒为 `[]`（即使检索过） | RULE-RAG-004, RULE-RAG-006, RULE-RAG-016 | REQ-RAG-002, REQ-RAG-005 | observed |
| ASRT-RAG-007 | 问题 `"接口报错怎么处理"` 含 `报错` → 判为 diagnosis；若该用户无 agent，则落到 `_rag_path` 并返回非空 `source_documents` | RULE-RAG-004, RULE-RAG-006 | REQ-RAG-002 | observed |
| ASRT-RAG-008 | `POST /api/v1/chat/` 传 `llm_model: "gpt-4o"` → **422**，detail 含 `不支持的模型` 且列出可用模型 | RULE-RAG-021 | REQ-RAG-010 | observed |
| ASRT-RAG-009 | 传 `top_k: 0` 或 `top_k: 51` → 422（字段约束 `ge=1, le=50`）；传 `top_k: 20` → 200 | RULE-RAG-018 | REQ-RAG-007 | observed |
| ASRT-RAG-010 | 传他人私有库 id 作为 `kb_id` → HTTP **200**（不是 403/404），`source_documents` 为 `[]`，`answer` 为通用回答 | RULE-RAG-019 | REQ-RAG-009 | observed |
| ASRT-RAG-011 | 传不存在的 `assistant_id: 999999` → **404**，detail 为 `Assistant not found`；传他人助手 id → **403** | RULE-RAG-020 | REQ-RAG-009 | observed |
| ASRT-RAG-012 | 用知识库问一个明确在库内某 PDF 页出现的问题 → 响应 `source_documents` 非空，且每项 `metadata.filename` 非空、`metadata.page ≥ 1` | RULE-RAG-014 | REQ-RAG-005 | observed |
| ASRT-RAG-013 | 同一响应在前端渲染后，"参考来源："块每行形如 `…（相关度：0.xx）`，且**不出现**文件名与页码字样 | RULE-RAG-015 | REQ-RAG-005 | observed |
| ASRT-RAG-014 | 问一个知识库完全无关的问题 → 答案文本含 `根据提供的信息无法回答`（或等价中文表述），`source_documents` 为空或分数极低 | RULE-RAG-013 | REQ-RAG-005 | observed（判定为 graded） |
| ASRT-RAG-015 | 同一 `kb_id`、同一问题连续两次请求：第一次在服务启动后（触发索引建立），随后上传新文档至 `status=2`，再问一个只在新文档里出现的字面词 → 该词内容**不出现**在结果中；而 `POST /knowledge-bases/{kb_id}/search` 同词可命中 | RULE-RAG-009, RULE-RAG-019(kb-ingest) | REQ-RAG-003 | observed |
| ASRT-RAG-016 | 记录 `POST /chat/` 请求前的时间戳，响应返回后再请求一次同一问题，比较两次响应中 `source_documents` 的 `score` 集合：正常联网时第一次为 rerank 相关性分（0–1 小数），断网/使 DashScope 返回非 200 时为原始检索分；两次均 HTTP 200 | RULE-RAG-011 | REQ-RAG-004 | observed |
| ASRT-RAG-017 | 助手 `rag_config` 由 `{"top_k":5,"enable_rerank":true}` 改为 `{"top_k":20,"enable_rerank":false}`，保存后同一问题再问：`source_documents` 的条数 ≤ 5 且与改前一致（不变） | RULE-RAG-018 | REQ-RAG-007 | observed |
| ASRT-RAG-018 | 助手 `rag_config.top_k=1` 时同一问题仍返回 5 条来源（证明该配置未被消费） | RULE-RAG-018 | REQ-RAG-007 | observed |
| ASRT-RAG-019 | 故障注入使 LLM 抛异常且 fallback 也失败 → HTTP **200**，`answer` 以 `Error generating response:` 开头 | RULE-RAG-022 | REQ-RAG-010 | observed |
| ASRT-RAG-020 | 同一会话连续提 12 轮，每轮问题不同；第 12 轮的回答不引用第 1 轮内容（窗口 10）——通过日志或让模型复述第 1 轮内容判定 | RULE-RAG-023 | REQ-RAG-008 | observed（graded） |
| ASRT-RAG-021 | 停止 Redis 后提问 → HTTP 200，答案正常，仅无历史上下文；`GET /chat/sessions/{id}/messages` 仍返回历史（来自 SQLite） | RULE-RAG-023 | REQ-RAG-008 | observed |
| ASRT-RAG-022 | 删除一个会话后：`GET /chat/sessions/{session_id}/messages` → 404/空；`data/vectors/vectors_meta.json` 的条数不变 | RULE-RAG-024 | REQ-RAG-008 | observed |
| ASRT-RAG-023 | 检索结果的最高 `score` 低于 0.2 时仍出现在 `source_documents` 中（未被 `RAG_MIN_SCORE=0.10` 以外的逻辑过滤） | RULE-RAG-025 | REQ-RAG-003 | observed |
| ASRT-RAG-024 | `POST /api/v1/chat/` 响应 JSON 的键集合为 `{session_id, query, answer, source_documents}`，**不含** `metrics` | RULE-RAG-026 | REQ-RAG-005 | observed |
| ASRT-RAG-025 | 在助手 `memory_config.enable_long_term=true` 下完成一次问答，重启服务后同一用户新会话提问 → 无任何来自上次跨会话的偏好注入（长期记忆无副作用） | RULE-RAG-027 | REQ-RAG-008 | observed |
| ASRT-RAG-026 | 多跳：构造一个经 LLM 判为 multi_hop 的问题，响应 `source_documents` 中 `id` 无重复，且条数 ≤ 3 个子查询 × 每次 top_k 的并集 | RULE-RAG-017 | REQ-RAG-006 | observed |
| ASRT-RAG-027 | 混合检索下同一 query，`source_documents` 的 `score` 不单调对应其排序位置（因为返回的是原始分而非 RRF 分） | RULE-RAG-007 | REQ-RAG-003 | observed |

---

## 4. 未决（供 `specs/questions.md` 汇总）

见 `requirements/modules/rag-qa.md` §4 的 10 条。规格层需补充的判定口径：

- **ASRT-RAG-015 的执行前提**：需要一个未建立过 BM25 索引的干净进程 + 新上传文档，属 `controlled_fixture`；若环境已有索引，需先重启 API 进程才能复现。
- **ASRT-RAG-016 需要故障注入**：使 DashScope rerank 返回非 200，属 `controlled_fixture`。
- **ASRT-RAG-020 需要 12 轮真实模型调用**，成本与耗时需计入资源预算，`evaluation_mode` 建议 `graded`。
- **未核实**：Celery/Milvus/Redis/DashScope 的在线状态；本模块所有"已验证"列均为"否"。
