# 模块规格：assistant-agent（助手与 Agent 的配置、版本与执行）

- 模块 ID：`assistant-agent`（前缀 `AGENT`）
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 主链路：`FLOW-ASSIST-EXEC`
- 依据来源：`requirements/modules/assistant-agent.md`；除注明 confirmed 外均为 observed
- 生成时间：2026-11-11

## 1. 入口与接口清单

### 1.1 助手（前缀 `/api/v1/assistants`）

| 用户动作 | 页面元素 | 接口 | 方法 | source |
| --- | --- | --- | --- | --- |
| 创建助手 | `/assistants` 新建表单 | `/api/v1/assistants/` | POST | `src/api/routers/assistant.py:59` |
| 查看我的助手列表 | 列表区 | `/api/v1/assistants/` | GET | `src/api/routers/assistant.py:96` |
| 查看单个助手 | 详情 | `/api/v1/assistants/{assistant_id}` | GET | `src/api/routers/assistant.py:103` |
| 编辑助手 | 编辑表单保存 | `/api/v1/assistants/{assistant_id}` | PUT | `src/api/routers/assistant.py:116` |
| 删除助手 | 列表删除按钮 | `/api/v1/assistants/{assistant_id}` | DELETE | `src/api/routers/assistant.py:156` |
| 保存版本快照 | 「保存版本」按钮 | `/api/v1/assistants/{assistant_id}/versions` | POST | `src/api/routers/assistant.py:172` |
| 查看版本历史 | 版本列表 | `/api/v1/assistants/{assistant_id}/versions` | GET | `src/api/routers/assistant.py:195` |

### 1.2 Agent（前缀 `/api/v1/agents`）

| 用户动作 | 页面元素 | 接口 | 方法 | source |
| --- | --- | --- | --- | --- |
| 创建 Agent | `/agents` 新建表单 | `/api/v1/agents/` | POST | `src/api/routers/agent.py:176` |
| 查看我的 Agent 列表 | 列表区 | `/api/v1/agents/` | GET | `src/api/routers/agent.py:206` |
| 查看单个 Agent | 详情 | `/api/v1/agents/{agent_id}` | GET | `src/api/routers/agent.py:214` |
| 编辑 Agent | 编辑表单保存 | `/api/v1/agents/{agent_id}` | PUT | `src/api/routers/agent.py:228` |
| 删除 Agent | 列表删除按钮 | `/api/v1/agents/{agent_id}` | DELETE | `src/api/routers/agent.py:258` |
| 执行一次 Agent 查询 | **无界面**（前端无调用方） | `/api/v1/agents/{agent_id}/execute` | POST | `src/api/routers/agent.py:275` |

### 1.3 Agent 执行返回的 `degradation` 取值

| 取值 | 触发条件 | answer 表现 | source |
| --- | --- | --- | --- |
| `llm_fallback` | LLM 取不到 / 首轮决策异常 / 再决策异常 | 固定中文兜底句 | `src/services/agent_tool_service.py:125-132`、`:189-204`、`:239-246` |
| `tools_unavailable` | MCP 工具加载失败，或工具列表为空 | 纯 LLM 回答（正常内容） | `src/services/agent_tool_service.py:157-181` |
| `tools_partial` | 至少一个工具执行失败 | 正常内容 + 失败工具的字符串错误 | `src/services/agent_tool_service.py:249` |
| `null` | 全链路正常 | 正常内容 | `src/services/agent_tool_service.py:249` |

### 1.4 功能单元（FEAT-AGENT-\*，供 `specs/feature-index.json` 与 `cases/assistant-agent.json` 的 `feature_id` 解析）

| ID | 功能单元（用户视角） | 入口 | requirement_refs | source |
| --- | --- | --- | --- | --- |
| FEAT-AGENT-001 | 建一个助手并配好模型、提示词、知识库与工具，之后能改能删 | `/assistants` 新建与编辑表单 | REQ-AGENT-001 | `src/api/routers/assistant.py:59-147`、`frontend/src/views/Assistant.vue:481-527` |
| FEAT-AGENT-002 | 只看得到自己的助手与 Agent；越权访问被挡住，非法入参被拒绝 | 各端点的归属与校验层 | REQ-AGENT-001, REQ-AGENT-005 | `src/api/routers/assistant.py:66-75,103-114`、`src/api/routers/agent.py:214-225,40-118` |
| FEAT-AGENT-003 | 给助手存一份版本快照，之后能翻历史、能回滚 | 「保存版本」与版本列表 | REQ-AGENT-002 | `src/api/routers/assistant.py:172-212`、`frontend/src/views/Assistant.vue:472-560` |
| FEAT-AGENT-004 | 助手里的检索参数（top_k / rerank）在问答中生效 | 表单 `rag_config` 区块 | REQ-AGENT-003 | `frontend/src/views/Assistant.vue:80-94`、`src/services/rag_service.py:84-103` |
| FEAT-AGENT-005 | 助手记得住本轮对话的前几轮，长记忆暂不可用 | 表单 `memory_config` 区块 | REQ-AGENT-004 | `frontend/src/views/Assistant.vue:55-61`、`src/services/memory_service.py:30-76` |
| FEAT-AGENT-006 | 建一个 Agent 并配好 LLM 与 MCP 工具，能带工具跑一次查询 | `/agents` 表单 + `POST /agents/{id}/execute`（**执行无界面**） | REQ-AGENT-006 | `src/api/routers/agent.py:176-290`、`src/services/agent_tool_service.py:118-256` |
| FEAT-AGENT-007 | 助手挂上 Agent 后，提问改走 Agent 链路并带回工具调用记录 | 表单 `agent_ids` 多选 | REQ-AGENT-007 | `src/services/rag_service.py:196-228`、`src/api/routers/chat.py:125-142` |

## 2. 规则

### RULE-AGENT-001 所有端点要求登录态

- **要求**：7 个助手端点与 6 个 Agent 端点都挂 `Depends(get_current_user)`，无 token 或 token 失效一律 401。
- **适用条件**：全部请求。
- **可观察**：不带 `Authorization` 头请求任一端点 → 401。
- **source**：`src/api/routers/assistant.py:59-212`、`src/api/routers/agent.py:176-290`
- **requirement_refs**：REQ-AGENT-001、REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-002 资源归属校验

- **要求**：读取/修改/删除单个助手或 Agent 时比对 `user_id`；不存在 → 404，属于他人 → 403。
- **适用条件**：带 `{id}` 的单资源端点（除 versions 之外）。
- **可观察**：用用户 B 的 token 访问用户 A 的助手 → 403 `'Not authorized'`；访问不存在的 id → 404 `'Assistant not found'` / `'Agent not found'`。
- **source**：`src/api/routers/assistant.py:103-114`、`src/api/routers/agent.py:284-287`
- **requirement_refs**：REQ-AGENT-001、REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-003 列表只返回自己的资源

- **要求**：`GET /assistants/` 与 `GET /agents/` 以 `user_id == current_user.id` 过滤。
- **适用条件**：列表端点。
- **可观察**：A 的列表里不出现 B 创建的助手/Agent。
- **source**：`src/api/routers/assistant.py:96-101`、`src/api/routers/agent.py:206-211`
- **requirement_refs**：REQ-AGENT-001、REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-004 创建助手时 temperature 限定 0.0–2.0

- **要求**：`AssistantCreate.temperature` 为 `Field(0.7, ge=0.0, le=2.0)`，越界 422。
- **适用条件**：`POST /assistants/`。
- **可观察**：`temperature: 3.0` → 422；`temperature: 0.7` → 200。
- **source**：`src/api/routers/assistant.py:19`
- **requirement_refs**：REQ-AGENT-001
- **basis**：observed

### RULE-AGENT-005 更新助手时 temperature 无范围约束

- **要求**：`AssistantUpdate.temperature` 为 `Optional[float] = None`，不带 ge/le，任意浮点可写入。
- **适用条件**：`PUT /assistants/{id}`。
- **可观察**：`PUT` 传 `temperature: 99.0` → 200 且回读为 99.0（与 RULE-AGENT-004 不对称）。
- **source**：`src/api/routers/assistant.py:32`
- **requirement_refs**：REQ-AGENT-001
- **basis**：observed

### RULE-AGENT-006 助手 kb_ids 归属校验

- **要求**：创建或更新助手时，`kb_ids` 非空则查库比对归属当前用户，数量不符即 400 `'Invalid KB IDs: some knowledge bases do not exist or do not belong to you'`。
- **适用条件**：`POST /assistants/`、`PUT /assistants/{id}`。
- **可观察**：传他人知识库 id → 400 且携带上述 detail；传自己的 → 200。
- **source**：`src/api/routers/assistant.py:66-75`、`:131-141`
- **requirement_refs**：REQ-AGENT-001
- **basis**：observed

### RULE-AGENT-007 agent_ids 不做归属校验

- **要求**：现状为 `agent_ids` 仅按 `Optional[List[int]]` 收下并原样落库，不校验这些 Agent 是否属于当前用户。
- **适用条件**：`POST /assistants/`、`PUT /assistants/{id}`。
- **可观察**：传一个他人 Agent 的 id → 仍 200，且 `GET /assistants/{id}` 回读该 id。
- **source**：`src/api/routers/assistant.py:26`、`:89`、`:66-75`（只对 kb_ids 做校验）
- **requirement_refs**：REQ-AGENT-001、REQ-AGENT-007
- **basis**：observed

### RULE-AGENT-008 版本快照请求体不做 schema 校验

- **要求**：`POST /assistants/{id}/versions` 收裸 `dict`，取 `version` 与 `config`；`config` 缺失存 `{}`，`version` 缺失存 NULL，无唯一性约束。
- **适用条件**：版本端点。
- **可观察**：body `{}` → 200 `'Version saved'`；`GET .../versions` 出现一条 `config={}` 的记录。
- **source**：`src/api/routers/assistant.py:185-189`
- **requirement_refs**：REQ-AGENT-002
- **basis**：observed

### RULE-AGENT-009 删除助手级联删除其版本

- **要求**：`Assistant.versions` 关系设 `cascade="all, delete-orphan"`，删助手时其 `assistant_versions` 一并删除。
- **适用条件**：`DELETE /assistants/{id}`。
- **可观察**：删助手后 `select count(*) from assistant_versions where assistant_id=<id>` 为 0。
- **source**：`src/database/models.py:199-201`、`src/api/routers/assistant.py:156-170`
- **requirement_refs**：REQ-AGENT-002
- **basis**：observed

### RULE-AGENT-010 rag_config 写入但不被消费

- **要求**：现状为 `rag_config` 随 `Assistant` 落库并进入 `assistant_config`，但 `RAGService.query()` 内无 `rag_config` 读取点；检索用入参 `top_k`，重排用全局 `settings.ENABLE_RERANK`。
- **适用条件**：任何通过聊天入口使用助手的场景。
- **可观察**：把 `rag_config.top_k` 从 1 改到 20 后同一问题提问，`source_documents` 条数与内容不变；改 `ENABLE_RERANK` 才影响重排。
- **source**：`src/api/routers/chat.py:138`、`src/services/rag_service.py:84-103`、`src/services/rag_service.py:241`、`src/services/rag_service.py:250-253`
- **requirement_refs**：REQ-AGENT-003
- **basis**：observed

### RULE-AGENT-011 hybrid_weight 与 rerank_top_n 无消费者

- **要求**：现状为前端可编辑的 `rag_config.hybrid_weight`、`rag_config.rerank_top_n` 在 `src/` 内无任何读取点。
- **适用条件**：助手配置表单。
- **可观察**：`grep -rn "hybrid_weight" src/` 与 `grep -rn "rerank_top_n" src/` 均无命中。
- **source**：`frontend/src/views/Assistant.vue:80-94`
- **requirement_refs**：REQ-AGENT-003
- **basis**：observed

### RULE-AGENT-012 短期记忆按 window_size 取历史

- **要求**：`enable_short_term` 默认 `True`、`window_size` 默认 `10`；取历史调用 `get_short_term_memory(session_id, limit=window_size)`；Redis 键为 `session:{session_id}:history`，写入用 `lpush` + `ltrim(0, history_limit-1)` + `expire(ttl)`。
- **适用条件**：所有走 RAG 分支的问答。
- **可观察**：Redis 中该键的 `LLEN` 不超过 `MEMORY_HISTORY_LIMIT`；`window_size=1` 时 prompt 只带 1 条历史。
- **source**：`src/services/rag_service.py:90-96`、`src/services/memory_service.py:30-64`
- **requirement_refs**：REQ-AGENT-004
- **basis**：observed

### RULE-AGENT-013 长期记忆为空实现

- **要求**：`enable_long_term` 只写 `logger.info`，`long_term_context` 恒为空串；`add_long_term_memory` 函数体为 `pass`。
- **适用条件**：`memory_config.enable_long_term=True`。
- **可观察**：开启后问答内容与关闭时一致；`src/services/memory_service.py:72-73` 无副作用。
- **source**：`src/services/rag_service.py:100-103`、`src/services/memory_service.py:71-73`
- **requirement_refs**：REQ-AGENT-004
- **basis**：observed

### RULE-AGENT-014 Redis 不可用时短期记忆降级为空

- **要求**：`get_short_term_memory` 捕获异常记 `logger.error` 并返回 `[]`，不向上抛。
- **适用条件**：Redis 未启动或连接失败。
- **可观察**：停掉 Redis 后提问仍返回 200，回答无上下文，服务端日志出现 `Error getting short term memory`。
- **source**：`src/services/memory_service.py:51-53`
- **requirement_refs**：REQ-AGENT-004
- **basis**：observed

### RULE-AGENT-015 创建 Agent 时 type 无枚举约束

- **要求**：`AgentCreate.type: str = "function_call"`，非 Literal，任意字符串可入库。
- **适用条件**：`POST /agents/`、`PUT /agents/{id}`。
- **可观察**：`type: "whatever"` → 200 且 `GET /agents/{id}` 回读 `"whatever"`。
- **source**：`src/api/routers/agent.py:135-139`、`src/database/models.py:220`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-016 MCP 服务器配置严格校验与 SSRF 防护

- **要求**：`MCPServerConfig` 设 `extra="forbid"`；`transport` 仅允许 `streamable_http` / `sse`；`url` 仅允许 http/https，拦截私网、回环、链路本地、`169.254.169.254`、`fc00::/7`；开发环境放行 loopback 与 localhost；非开发环境做 DNS 解析后复查；`socket.gaierror` 放行。
- **适用条件**：`tools_config` 中出现的每个 MCP 服务器条目。
- **可观察**：`transport: "ws"` → 422；`url: "http://169.254.169.254/latest"` → 422；生产环境下 `url: "http://127.0.0.1:8080"` → 422，开发环境 → 200。
- **source**：`src/api/routers/agent.py:16-96`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-017 execution_config 数值边界

- **要求**：`max_iterations` 要求 `> 0` 且 `≤ 20`；`llm_timeout` / `tool_timeout` / `mcp_load_timeout` 要求 `> 0.0`；`extra="forbid"`。
- **适用条件**：`execution_config` 出现时。
- **可观察**：`max_iterations: 21` → 422；`max_iterations: 20` → 200；`llm_timeout: 0` → 422。
- **source**：`src/api/routers/agent.py:110-118`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-018 llm_config 数值边界

- **要求**：`temperature` 0–2、`max_tokens > 0`、`top_p` 0–1，`extra="forbid"`。
- **适用条件**：`llm_config` 出现时。
- **可观察**：`temperature: 2.5` → 422；`top_p: 1.5` → 422。
- **source**：`src/api/routers/agent.py:99-107`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-019 子模型落库前二次转 dict

- **要求**：`tools_config` 与 `PUT` 路径上的各子 config 在写入 JSON 列前做 `model_dump(exclude_none=True)`，未设字段不进库。
- **适用条件**：创建/更新 Agent。
- **可观察**：只传 `llm_config.model` 时，`agents.llm_config` 里只有 `model` 键。
- **source**：`src/api/routers/agent.py:189`、`:243-248`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

### RULE-AGENT-020 execute 端点鉴权与返回形态

- **要求**：`POST /agents/{id}/execute` 先查 Agent（404 `'Agent not found'`）、再比对 `user_id`（403 `'Not authorized'`），随后 `await execute_agent_query(agent, payload.query)` 并把返回 dict 原样输出；无 `response_model`。
- **适用条件**：执行端点。
- **可观察**：返回体只有 `query` / `answer` / `tool_calls` / `degradation` 四个键，HTTP 200；跳过鉴权直接调用他人 Agent → 403。
- **source**：`src/api/routers/agent.py:275-290`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-021 工具加载失败降级为纯 LLM

- **要求**：`load_agent_tools` 返回 `(tools, error)` 且不抛异常；`error` 非空或 `tools` 为空时走纯 LLM 分支，返回 `degradation="tools_unavailable"`。
- **适用条件**：`tools_config` 为空、MCP 服务不可达、或加载超时（10s）。
- **可观察**：配一个不可达的 MCP url 后执行 → HTTP 200，`degradation` 为 `"tools_unavailable"`，`answer` 仍是一段正常回答，`tool_calls` 为 `[]`。
- **source**：`src/services/agent_tool_service.py:42-52`、`:157-181`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-022 多轮工具调用受 max_iterations 限制

- **要求**：`for _ in range(max_iterations)` 循环，默认 5，配置上限 20；无 `tool_calls` 即 break。
- **适用条件**：模型持续要求调用工具的场景。
- **可观察**：把 `max_iterations` 设 1 且工具总是要求继续调用时，`tool_calls` 条数对应的轮次不超过 1 轮。
- **source**：`src/services/agent_tool_service.py:206-247`、`src/services/agent_tool_service.py:31`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-023 工具并发执行且单工具异常不冒泡

- **要求**：同一轮的多个 `tool_calls` 用 `asyncio.gather` 并发执行；工具不存在返回 `'Tool {name} not found.'`，单工具异常返回 `'Error executing {name}: {e}'` 并记 warning；任一失败使终态 `degradation="tools_partial"`。
- **适用条件**：一轮内有多个工具调用或工具抛异常。
- **可观察**：执行返回 200，`tool_calls` 含多条；失败工具的返回内容为上述字符串之一；`degradation` 为 `"tools_partial"`。
- **source**：`src/services/agent_tool_service.py:85-115`、`:249`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-024 LLM 不可用时返回固定兜底句

- **要求**：`_get_agent_llm` 取不到 LLM 时返回 `degradation="llm_fallback"` 与 `answer='LLM 服务暂不可用，请稍后重试。'`；决策阶段异常时返回 `degradation="llm_fallback"` 与 `'模型决策时出错，请稍后重试。'` / `'模型再决策时出错，请稍后重试。'`。
- **适用条件**：模型白名单为空、`create_agent_llm` 失败、或 LLM 调用抛异常。
- **可观察**：HTTP 仍为 200，`answer` 命中上述固定句，`tool_calls` 为 `[]`。
- **source**：`src/services/agent_tool_service.py:55-76`、`:125-132`、`:189-204`、`:239-246`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-025 模型白名单外回落 AGENT_MODEL

- **要求**：`llm_config.model` 不在 `settings.AVAILABLE_MODELS` 拆分集合内时回落 `settings.AGENT_MODEL`。
- **适用条件**：Agent 指定了不存在的模型名。
- **可观察**：`llm_config.model` 设为 `"not-a-model"` 时执行仍成功（用 `AGENT_MODEL`），无报错。
- **source**：`src/services/agent_tool_service.py:55-76`、`src/settings.py:77-79`、`src/settings.py:59`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-026 执行日志字段截断与空缺

- **要求**：写 `AgentExecutionLog` 时 `query` 截断 5000 字、`answer` 截断 10000 字、`tool_count = len(tool_calls)`、记录 `degradation`；`trace_id` 不写入、`latency_ms` 不传（恒 NULL）；写日志失败只记 warning，不影响响应。
- **适用条件**：每次 `execute_agent_query` 结束。
- **可观察**：`select length(query), length(answer), tool_count, degradation, trace_id, latency_ms from agent_execution_logs order by id desc limit 1` → `trace_id`、`latency_ms` 为 NULL。
- **source**：`src/services/execution_log_service.py:28-44`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-027 助手挂 Agent 时只取第一个

- **要求**：`_agent_path` 内 `agent = agents[0]`，多绑的 Agent 只第一个生效；有 `kb_ids` 时先检索并按全局开关重排，拼成 `【知识库参考资料】` 再交给 `execute_agent_query`。
- **适用条件**：助手 `agent_ids` 非空且通过 `/chat/` 提问。
- **可观察**：绑定两个 Agent 后提问，只有第一个 Agent 的执行日志新增行。
- **source**：`src/services/rag_service.py:196-228`
- **requirement_refs**：REQ-AGENT-007
- **basis**：observed

### RULE-AGENT-028 助手执行链路携带 tool_calls 回传

- **要求**：`_agent_path` 返回 `{query, answer, source_documents, tool_calls}`，聊天响应可见 `tool_calls`。
- **适用条件**：走 Agent 分支的问答。
- **可观察**：`POST /chat/` 响应体含 `tool_calls` 键（可能为空数组）。
- **source**：`src/services/rag_service.py:223-228`
- **requirement_refs**：REQ-AGENT-007
- **basis**：observed

### RULE-AGENT-029 execute 端点无前端调用方

- **要求**：现状为前端 `frontend/src/views/Agent.vue` 全文无 `/agents/{id}/execute` 调用，Agent 执行只能由接口或脚本触发。
- **适用条件**：全部前端页面。
- **可观察**：`grep -n "execute" frontend/src/views/Agent.vue` 仅命中 `'plan_execute'` 选项、`execute_code` 复选框与类型映射函数，无 HTTP 调用。
- **source**：`frontend/src/views/Agent.vue:1-451`
- **requirement_refs**：REQ-AGENT-006
- **basis**：observed

### RULE-AGENT-030 前端不发送 tools_config

- **要求**：现状为前端保存 Agent 时显式不发送 `tools_config`（避免后端 `dict[str, MCPServerConfig]` 校验 422），并把 `llm_config.model_name` → `model`、`execution_config.timeout` → `llm_timeout`+`tool_timeout`、`retry_times` → `max_iterations`。
- **适用条件**：`frontend/src/views/Agent.vue` 保存动作。
- **可观察**：从界面创建 Agent 后，`GET /agents/{id}` 的 `tools_config` 为空/未设置；`execution_config` 的 `llm_timeout` 与 `tool_timeout` 数值相同。
- **source**：`frontend/src/views/Agent.vue:383-399`
- **requirement_refs**：REQ-AGENT-005
- **basis**：observed

## 3. 断言表

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
| --- | --- | --- | --- | --- |
| ASRT-AGENT-001 | 不带 `Authorization` 头请求 `GET /api/v1/assistants/` 与 `GET /api/v1/agents/` 均返回 401 | RULE-AGENT-001 | REQ-AGENT-001 | observed |
| ASRT-AGENT-002 | 用户 B 用自己 token `GET /api/v1/assistants/{A 的 id}` 返回 403 且 detail 等于 `'Not authorized'`；`GET /api/v1/agents/{A 的 id}` 同样 403 | RULE-AGENT-002 | REQ-AGENT-001 | observed |
| ASRT-AGENT-003 | `GET /api/v1/assistants/` 返回列表中不含 B 创建的助手 id；`GET /api/v1/agents/` 同理 | RULE-AGENT-003 | REQ-AGENT-001 | observed |
| ASRT-AGENT-004 | `POST /api/v1/assistants/` 传 `temperature: 3.0` 返回 422；传 `0.7` 返回 200 | RULE-AGENT-004 | REQ-AGENT-001 | observed |
| ASRT-AGENT-005 | `PUT /api/v1/assistants/{id}` 传 `temperature: 99.0` 返回 200，回读 `temperature` 为 99.0 | RULE-AGENT-005 | REQ-AGENT-001 | observed |
| ASRT-AGENT-006 | `POST /api/v1/assistants/` 传他人 knowledge_base id 返回 400，detail 等于 `'Invalid KB IDs: some knowledge bases do not exist or do not belong to you'` | RULE-AGENT-006 | REQ-AGENT-001 | observed |
| ASRT-AGENT-007 | `POST /api/v1/assistants/` 的 `agent_ids` 传他人 Agent id 返回 200，且回读该 id（无归属校验） | RULE-AGENT-007 | REQ-AGENT-001、REQ-AGENT-007 | observed |
| ASRT-AGENT-008 | `POST /api/v1/assistants/{id}/versions` 传空 body `{}` 返回 200 且 message 等于 `'Version saved'`，随后 `GET .../versions` 出现 `config` 为 `{}` 的记录 | RULE-AGENT-008 | REQ-AGENT-002 | observed |
| ASRT-AGENT-009 | 删除助手后 `SELECT count(*) FROM assistant_versions WHERE assistant_id=<该 id>` 等于 0 | RULE-AGENT-009 | REQ-AGENT-002 | observed |
| ASRT-AGENT-010 | 把助手 `rag_config.top_k` 从 1 改到 20，同一问题两次 `POST /api/v1/chat/` 的 `source_documents` 条数相同（配置未被消费） | RULE-AGENT-010 | REQ-AGENT-003 | observed |
| ASRT-AGENT-011 | `grep -rn "hybrid_weight" src/` 与 `grep -rn "rerank_top_n" src/` 均无输出 | RULE-AGENT-011 | REQ-AGENT-003 | observed |
| ASRT-AGENT-012 | 在同一 `session_id` 连问两轮后，Redis 键 `session:{session_id}:history` 的 `LLEN` 大于 0 且不超过 `MEMORY_HISTORY_LIMIT` | RULE-AGENT-012 | REQ-AGENT-004 | observed |
| ASRT-AGENT-013 | 把 `memory_config.enable_long_term` 设为 true 与 false 各问一次，两次回答的 context 中均不含长期记忆片段（`long_term_context` 恒空） | RULE-AGENT-013 | REQ-AGENT-004 | observed |
| ASRT-AGENT-014 | 停掉 Redis 后 `POST /api/v1/chat/` 仍返回 200，服务端日志出现 `Error getting short term memory` | RULE-AGENT-014 | REQ-AGENT-004 | observed |
| ASRT-AGENT-015 | `POST /api/v1/agents/` 传 `type: "whatever"` 返回 200，`GET /api/v1/agents/{id}` 回读 `type` 为 `"whatever"` | RULE-AGENT-015 | REQ-AGENT-005 | observed |
| ASRT-AGENT-016 | `POST /api/v1/agents/` 的 `tools_config` 条目传 `transport: "ws"` 返回 422；传 `url: "http://169.254.169.254/latest"` 返回 422；传 `extra_key: 1` 返回 422 | RULE-AGENT-016 | REQ-AGENT-005 | observed |
| ASRT-AGENT-017 | `POST /api/v1/agents/` 传 `execution_config: {"max_iterations": 21}` 返回 422，传 `20` 返回 200，传 `llm_timeout: 0` 返回 422 | RULE-AGENT-017 | REQ-AGENT-005 | observed |
| ASRT-AGENT-018 | `POST /api/v1/agents/` 传 `llm_config: {"temperature": 2.5}` 返回 422，传 `{"top_p": 1.5}` 返回 422 | RULE-AGENT-018 | REQ-AGENT-005 | observed |
| ASRT-AGENT-019 | 只传 `llm_config: {"model": "deepseek-v4.1-flash-1017"}` 创建 Agent 后，`GET /api/v1/agents/{id}` 的 `llm_config` 只含 `model` 一个键 | RULE-AGENT-019 | REQ-AGENT-005 | observed |
| ASRT-AGENT-020 | `POST /api/v1/agents/{id}/execute` 传 `{"query": "你好"}` 返回 HTTP 200，响应体键集合恰为 `{query, answer, tool_calls, degradation}` | RULE-AGENT-020 | REQ-AGENT-006 | observed |
| ASRT-AGENT-021 | 给 Agent 配一个不可达的 MCP `url` 后执行，返回 200 且 `degradation` 等于 `"tools_unavailable"`、`tool_calls` 为空数组 | RULE-AGENT-021 | REQ-AGENT-006 | observed |
| ASRT-AGENT-022 | 执行后 `agent_execution_logs` 最新行的 `tool_count` 等于响应体 `tool_calls` 长度、`degradation` 与响应体一致 | RULE-AGENT-026 | REQ-AGENT-006 | observed |
| ASRT-AGENT-023 | `grep -n "execute" frontend/src/views/Agent.vue` 无 `/agents/` 的 HTTP 调用行（仅命中类型字符串与权限复选框文案） | RULE-AGENT-029 | REQ-AGENT-006 | observed |
| ASRT-AGENT-024 | 界面创建 Agent 后 `GET /api/v1/agents/{id}` 的 `tools_config` 为空，且 `execution_config.llm_timeout` 等于 `tool_timeout` | RULE-AGENT-030 | REQ-AGENT-005 | observed |
| ASRT-AGENT-025 | 执行后 `SELECT trace_id, latency_ms FROM agent_execution_logs ORDER BY id DESC LIMIT 1` 两列均为 NULL | RULE-AGENT-026 | REQ-AGENT-006 | observed |
| ASRT-AGENT-026 | 配两个 `agent_ids` 的助手提问一次，`agent_execution_logs` 只新增 1 行且 `agent_id` 等于第一个 Agent 的 id | RULE-AGENT-027 | REQ-AGENT-007 | observed |
| ASRT-AGENT-027 | 助手带 `agent_ids` 时 `POST /api/v1/chat/` 响应体含 `tool_calls` 键 | RULE-AGENT-028 | REQ-AGENT-007 | observed |
| ASRT-AGENT-028 | 模型白名单外的 `llm_config.model`（如 `"not-a-model"`）不影响执行成功，返回 200 | RULE-AGENT-025 | REQ-AGENT-006 | observed |
| ASRT-AGENT-029 | `grep -rn "/agents/" frontend/src/` 的输出中不存在含 `execute` 的 URL 拼接（无任何视图调用 `POST /agents/{id}/execute`）；且 `frontend/src/views/Agent.vue:375-416` 构造的 payload 不含 `tools_config` 键 | RULE-AGENT-029、RULE-AGENT-030 | REQ-AGENT-006、REQ-AGENT-007 | observed |

## 4. 未决

- SPEC_GAP-1：`rag_config` 应为"生效"还是"下线"未定（RULE-AGENT-010、RULE-AGENT-011 只描述现状）。已登记 `specs/questions.md` Q-07。
- SPEC_GAP-2：`POST /agents/{id}/execute` 无前端调用方，是否补界面未定（RULE-AGENT-029）。已登记 Q-29。
- SPEC_GAP-3：`agent_ids` 无归属校验 + 只取 `agents[0]`，是否属缺陷需产品定性（RULE-AGENT-007、RULE-AGENT-027）。
- SPEC_GAP-4：`Agent.type` 三值是否应有不同执行策略未定（RULE-AGENT-015 只记录"无约束且无分派"）。
- SPEC_GAP-5：`trace_id`、`latency_ms` 恒空是否可接受未定（RULE-AGENT-026）。
- 未核实：MCP 服务真实可用性、per-config 客户端缓存的并发表现（本次只读源码）。
