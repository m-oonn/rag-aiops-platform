# 企业级 Multi-Agent GraphRAG 知识库平台 — 设计方案

## Context（背景与目标）

在**原版** RAG 项目基础上，升级为 **LangGraph 多智能体 GraphRAG 平台**。

**代码基线**：`C:\Users\Administrator\Desktop\ragPdfSystem`（原版，非 e:\rag-system 简化版）

**目标**：做一个**找实习用的高质量项目**，深度对标竞品简历 `Ragent-KOS`，但建立在自己的项目之上、且**每个技术点都能在面试中讲透（深度理解级）**。

**硬约束**：
- 时间线：**1 个月**
- 讲解要求：**深度理解级**（能回答任何追问：为什么选、tradeoff、不用会怎样）
- 能力焦点：**Agent 编排能力 + RAG 工程能力**
- 不换技术栈，基于现有项目演进

### 原版已有的地基（重要：减少了大量工作量）

| 已有，可直接复用/扩展 | 状态 |
|--------------------|------|
| **LangGraph 1.0.7** + checkpoint + prebuilt + sdk | ✅ 已装，未用 → 直接上手 |
| **Milvus** 向量库（IVF_FLAT + kb_id 标量过滤） | ✅ 生产级实现 |
| **评测框架**（QA生成 + LLM评估 + 报告 + 数据集上传） | ✅ 完整 → 扩展 Agent 维度即可 |
| **ragas / instructor / networkx** | ✅ 已装（评测/结构化输出/图结构） |
| **记忆系统**（Redis短期 + Milvus长期骨架） | ✅ 有骨架 → 补全长期偏好 |
| **Vue3 前端** SPA + Celery/RabbitMQ/MinIO + RBAC | ✅ 完整 → 前端加追踪面板 |
| **Agent/Assistant 数据模型** + CRUD API | ✅ 已有 schema，缺执行引擎 |

### 真正要新增的工作（新代码集中在这）

1. **DeepSeek provider**：原版主力是 Qwen/DashScope，需把简化版的 DeepSeek 实现搬过来，主力切 DeepSeek（Qwen/Ollama 备）
2. **LLM 工具调用**：原版 LLMClient 无 function calling，需加 `chat_with_tools`
3. **三路混合检索**：原版只有向量检索，需把简化版的 BM25+RRF 搬来 + 加 Graph 通道
4. **检索增强**：HyDE / Query Rewrite / Step-Back（全新）
5. **GraphRAG**：Neo4j + 三元组抽取 + GraphCypherQAChain（全新）
6. **MCP 工具服务**：FastMCP（全新）
7. **LangGraph 多Agent图**：Supervisor-Worker 并行 + Critique/Replan + HITL（全新，核心）
8. **降本增效**：语义缓存 + 动态模型路由 + 熔断（全新）
9. **PostgreSQL Checkpointer**：替换/补充（全新）
10. **前端 Agent 追踪面板** + Agent 评测扩展（扩展现有）

---

## 与 Ragent-KOS 的深度对标结论

竞品 Ragent-KOS 是生产级项目，但部分是"堆术语"（Leiden社区发现、SingleFlight、全套可观测栈）。我们的策略是 **聚焦深做 + 砍掉性价比低的炫技点**，做出一个**不输它、且你真讲得明白**的项目。

| 维度 | 本方案 | Ragent-KOS | 取舍理由 |
|------|--------|-----------|---------|
| 多Agent | Supervisor-Worker 并行+动态路由 | 同左 | 持平，map-reduce 好讲 |
| GraphRAG | 朴素图RAG（三元组+Cypher+多跳） | +Leiden社区/Global-Local | Leiden难讲且1个月风险大，砍掉 |
| 检索增强 | Query Rewrite+HyDE+Step-Back+三路融合 | 同左 | **全做**，便宜好讲高ROI |
| 自纠错/HITL | Planner/Critique/Replan + 计划审核 | 同左 | **全做**，和Agent焦点契合 |
| 工具架构 | 全 MCP | MCP | 持平 |
| 降本增效 | 语义缓存+动态模型路由+熔断 | +SingleFlight | 砍掉SingleFlight（太niche） |
| 可观测 | 轻量（结构化日志+指标+trace） | 全套OTel/Grafana/Jaeger | 偏DevOps离焦点远，做轻量版 |
| 评测 | 50-80 Golden+Ragas多维+路由准确率 | +A/B+CI | 砍A/B+CI（性价比一般） |
| 持久化 | PostgreSQL Checkpointer | MySQL | PG的LangGraph支持更成熟 |
| 向量库 | Milvus主/Chroma备 | Milvus | 持平 |

---

## 最终技术决策汇总

| 决策点 | 选择 |
|--------|------|
| Agent 框架 | LangGraph（StateGraph + Send API + Interrupt + Checkpointer） |
| Agent 协作 | **Supervisor-Worker 并行 + 动态路由**（map-reduce） |
| 工具架构 | **全 MCP**（FastMCP 独立服务进程） |
| 主力 LLM | DeepSeek（动态路由：简单→deepseek-chat，复杂→更强模型） |
| GraphRAG | 朴素图RAG（Neo4j + LLM三元组抽取 + GraphCypherQAChain 多跳） |
| 检索增强 | Query Rewrite + HyDE + Step-Back + 三路融合(Dense+BM25+Graph) + Rerank |
| 自纠错 | Planner / Critique / Replan 闭环 |
| 人工干预 | **计划审核**（Supervisor生成计划后、执行前 interrupt） |
| 记忆系统 | 两级（Redis短期 + Milvus长期偏好） |
| 持久化 | PostgreSQL Checkpointer |
| 降本增效 | 语义缓存 + 动态模型路由 + 熔断降级 |
| 可观测 | 轻量版（结构化日志 + 关键指标 + trace 记录） |
| 评测 | 50-80 Golden Dataset + Ragas多维 + 路由准确率 + 工具选择准确率 |
| Web搜索 | Bocha API |
| 向量库 | Milvus 主 / Chroma 备 |
| 前端 | Vue3 完整 Agent 追踪面板（含 HITL 审核UI） |
| Data Analyst Agent | 不做（聚焦知识库问答） |

---

## 技术栈

```
Agent 框架:    LangGraph (StateGraph, Send, interrupt, PostgresSaver)
LLM:          DeepSeek (主) + 动态模型路由
工具协议:      MCP (FastMCP Server, MultiServerMCPClient)
向量数据库:     Milvus (主) / ChromaDB (备)
图数据库:      Neo4j (GraphRAG)
关系库:        PostgreSQL (checkpointer + 业务数据) / SQLite (开发)
缓存/短期记忆:  Redis
长期记忆:      Milvus (向量化偏好)
Web搜索:       Bocha API
重排序:        CrossEncoder (bge-reranker / ms-marco)
嵌入:          BAAI/bge-small-zh-v1.5 (本地) / DashScope (云)
评测:          Ragas + 自研 Agent 评测
可观测:        结构化日志(loguru) + 指标统计 + trace
后端:          FastAPI + SSE Streaming
前端:          Vue3 + Element Plus + Pinia
部署:          Docker Compose
```

---

## 系统架构

### LangGraph 图结构（并行 + 自纠错 + HITL）

```
                          START
                            │
                            ▼
              ┌──────────────────────────┐
              │  Query Rewrite (入口预处理) │  多轮指代消解、补全省略
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │   Supervisor / Planner    │  意图识别 + 复杂度判断
              │   + Step-Back 抽象        │  + 任务拆解 → 执行计划
              └────────────┬─────────────┘
                           │
                  ╔════════▼═════════╗
                  ║  HITL: 计划审核   ║  ← interrupt，用户确认/修改计划
                  ║ (LangGraph 中断)  ║     PostgreSQL 保存状态可恢复
                  ╚════════┬═════════╝
                           │ 动态路由
              ┌────────────┼─────────────────────┐
              │ simple                            │ medium/complex
              ▼                                   ▼
        ┌──────────┐              ╔═══════════════════════════════╗
        │ General  │              ║  并行分发 (Send API, map)      ║
        │ Worker   │              ║  ┌──────────┐ ┌──────────┐    ║
        └────┬─────┘              ║  │RAG Worker│ │Graph     │ …  ║
             │                    ║  │Dense+BM25│ │Worker    │    ║
             ▼                    ║  │+HyDE+RRF │ │Neo4j多跳 │    ║
            END                   ║  │+Rerank   │ │          │    ║
                                  ║  └────┬─────┘ └────┬─────┘    ║
                                  ║       │  ┌──────────┐         ║
                                  ║       │  │Web Worker│(fallback)║
                                  ║       │  │  Bocha   │         ║
                                  ║       │  └────┬─────┘         ║
                                  ╚═══════╪═══════╪═══════════════╝
                                          ▼       ▼
                                  ┌──────────────────────┐
                                  │  Reduce: 三路 RRF 融合 │
                                  └──────────┬───────────┘
                                             ▼
                                  ┌──────────────────────┐
                                  │   Critique 自我评估    │ 结果是否充分/相关?
                                  └─────┬──────────┬──────┘
                                  不通过 │          │ 通过
                                        ▼          ▼
                                  ┌─────────┐ ┌──────────────┐
                                  │ Replan  │ │ Synthesizer  │ 生成带引用答案
                                  │(带反思)  │ │  /Writer     │
                                  └────┬────┘ └──────┬───────┘
                                       │             ▼
                                  回到并行分发        END
```

### State 定义

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # 对话历史
    query: str                                 # 原始查询
    rewritten_query: str                       # Query Rewrite 后
    complexity: str                            # simple/medium/complex
    plan: list[dict]                           # Supervisor 生成的执行计划
    plan_approved: bool                        # HITL 审核结果
    subtasks: list[dict]                       # 并行子任务（Send 用）
    retrieval_results: Annotated[list, operator.add]  # 各 Worker 召回(并行聚合)
    fused_context: str                         # Reduce 融合后上下文
    critique: dict                             # {passed: bool, reason, gaps}
    replan_count: int                          # 自纠错次数(防死循环)
    final_answer: str
    user_id: str
    session_id: str
    memory_context: str                        # 注入的记忆
    trace: Annotated[list, operator.add]       # 可观测追踪
```

---

## 核心技术模块详解（含「怎么讲」）

### 1. 多 Agent 并行编排（Supervisor-Worker + Send API）

**做什么**：Supervisor 把复杂查询拆成独立子任务，用 LangGraph `Send` API 把多个 Worker **并行**派发（map），各自检索后在 Reduce 节点**汇总**（reduce）。动态路由按复杂度决定走哪些 Worker。

**为什么**：传统 RAG 一次只做一种检索、串行执行慢。并行 map-reduce 既快又能融合多源知识。

**怎么讲**：
- "我用 Supervisor-Worker 模式，Supervisor 是大脑负责规划，Worker 是手负责执行。"
- "并行靠 LangGraph 的 Send API，它能动态 fan-out 多个相同节点的实例，本质是 map-reduce。"
- 追问"和串行比快多少"→ "N 路检索从 O(N·t) 降到 O(max(t))，3路检索约提速2-3倍"。
- 追问"动态路由怎么实现"→ "Supervisor 输出 complexity 字段，条件边 `add_conditional_edges` 据此路由"。

### 2. GraphRAG（朴素图RAG）

**做什么**：用 LLM 从文档抽取 `(实体, 关系, 实体)` 三元组 → MERGE 进 Neo4j → 查询时用 GraphCypherQAChain 把自然语言转 Cypher 做多跳查询。

**为什么**：向量检索只能找"语义相似"的块，找不到**跨文档的实体关联**（如"A部门负责的产品由哪个供应商供货"需要跨3个文档跳转）。图谱显式存关系，支持多跳推理。

**怎么讲**：
- "向量检索是'模糊匹配'，图谱是'精确关系推理'，互补。"
- "三元组抽取我用 LLM + `with_structured_output(Pydantic Schema)` 强制结构化输出。"
- 追问"为什么不做微软的社区发现"→ "Leiden社区发现适合超大规模全局摘要，我的场景是企业知识库的局部多跳，朴素图RAG性价比更高，且我能讲透每一步"。（**诚实承认边界 = 加分**）

### 3. 三路融合检索 + 检索增强四件套

**做什么**：
- **Query Rewrite**：多轮对话指代消解（"它多少钱"→"iPhone15多少钱"）
- **HyDE**：先让 LLM 生成假设答案，用假设答案的向量去检索（解决"问题和答案表述差异大"）
- **Step-Back**：把具体问题抽象成更宏观的问题再检索（提升复杂问题召回）
- **三路融合**：Dense(向量) + BM25(关键词) + Graph(图谱) 三路召回 → RRF 融合 → Rerank

**为什么**：单路召回不稳定。Dense懂语义但漏专有名词，BM25抓关键词但不懂语义，Graph补关系。三路 RRF 取长补短，降低幻觉。

**怎么讲**：
- HyDE："假设文档嵌入——用'假答案'代替'问题'去匹配'真答案'，因为答案和答案更像。"
- RRF："Reciprocal Rank Fusion，按排名倒数加权融合，`score = Σ 1/(k+rank)`，不依赖各路分数量纲。"
- Step-Back："先退一步问宏观问题，再回到细节，类似人先看全局再看局部。"

### 4. 自纠错闭环 + Human-in-the-Loop

**做什么**：
- **Critique 节点**：检索融合后，LLM 自评"上下文是否足够回答"，输出 `{passed, reason, gaps}`
- **Replan 节点**：不通过则带着 gaps 反思、重新规划检索（最多 N 次防死循环）
- **HITL 计划审核**：Supervisor 生成执行计划后用 `interrupt` **暂停**，前端展示计划，用户确认/修改后再执行；状态存 PostgreSQL，可恢复

**为什么**：Agent 容易"自信地答错"。Critique 让它先自查；HITL 让关键决策有人把关，提升可信度。

**怎么讲**：
- "Critique/Replan 是 Agent 的'反思-重试'闭环，类似 Self-RAG 思想。"
- "HITL 用 LangGraph 的 `interrupt` + checkpointer 实现，中断时整个图状态持久化到 PG，用户审核后从断点恢复——这也是为什么必须用 checkpointer 而不是内存。"
- 追问"怎么防死循环"→ "replan_count 计数，超阈值强制走 Synthesizer 输出当前最佳答案"。

### 5. 全 MCP 工具架构

**做什么**：所有工具（RAG检索、图谱查询、Web搜索、工具类）封装为 FastMCP Server 独立进程，Agent 通过 `MultiServerMCPClient` 调用。

**为什么**：工具与 Agent 解耦，可独立部署/复用/被其他系统调用（MCP 是 Anthropic 提出的开放标准）。

**怎么讲**：
- "MCP 是模型上下文协议，把工具标准化成独立服务，好处是解耦 + 跨系统复用。"
- "Agent 主进程通过 stdio 和 MCP Server 通信，工具的增删不影响 Agent 代码。"
- 追问"和直接 @tool 比"→ "@tool 是进程内函数耦合，MCP 是跨进程标准协议，代价是多一层通信开销，换来可扩展性"。

### 6. 两级记忆系统

**做什么**：
- **短期**：Redis 存会话历史，key=`mem:short:{user}:{session}`，TTL 30分钟，超长自动压缩
- **长期**：LLM 从对话抽取用户偏好（`category:value`）→ 向量化存 Milvus → 每次对话注入相关偏好

**怎么讲**："短期记忆解决多轮上下文，长期记忆解决跨会话个性化。长期偏好用向量存，靠语义检索召回相关偏好。"

### 7. 降本增效（语义缓存 + 动态模型路由 + 熔断）

**做什么**：
- **语义缓存**：查询向量化，相似度 > 阈值(如0.95)直接返回缓存答案（Milvus 存 QA 缓存）
- **动态模型路由**：Supervisor 判断的 complexity 联动——simple 走便宜模型，complex 走强模型
- **熔断降级**：LLM/工具调用失败时熔断，降级到备用方案（如图谱失败→纯向量）

**怎么讲**："这三个都是'降本增效'。语义缓存省重复推理；模型路由按需分配算力；熔断保证一个组件挂了系统不崩。"

### 8. 轻量可观测

**做什么**：结构化日志（loguru）+ 关键指标统计（延迟、Token、缓存命中率、各 Worker 耗时）+ 完整 trace（State.trace 累加每步）。前端追踪面板可视化。

**怎么讲**："我做了轻量可观测——结构化日志 + 指标 + 全链路 trace。没上 Grafana 全套是因为我的焦点在 AI 链路，可观测做到'能定位问题、能展示推理过程'即可。"（**有意识的取舍 = 加分**）

---

## 评测体系（中等偏上）

| 评测层 | 指标 | 方法 |
|--------|------|------|
| 检索层 | Context Precision/Recall | Ragas |
| 生成层 | Faithfulness, Answer Relevance | Ragas |
| Agent层 | 路由准确率（编排器分类对不对） | 预期 vs 实际 |
| Agent层 | 工具选择准确率 | 预期工具链 vs 实际调用 |
| E2E | 任务完成率、平均跳数、耗时 | 统计 |

- **Golden Dataset**：50-80 题，标注 complexity + 预期工具链 + ground truth
- 自动生成测试集（复用现有 QAGenerator）+ 人工校准
- 输出 Markdown 评测报告，支持不同配置对比

---

## 文件变更计划（7 个 Phase）

> 基线 = 原版 `ragPdfSystem`。标注 🆕新建 / 🔧扩展已有 / 📦从简化版搬运。

### Phase 0：基线对齐（搬运 + 准备，约 0.5-1 天）
- 📦 从简化版搬 **DeepSeek provider** 进原版 `src/llm/llm_client.py`，主力切 DeepSeek（Qwen/Ollama 备）
- 📦 从简化版搬 **BM25 + RRF 混合检索** 进 `src/retrieval/hybrid_retriever.py`
- 📦 从简化版搬 **本地 CrossEncoder reranker**（可选，原版用 DashScope rerank）
- 验证：原版能用 DeepSeek 跑通 + 混合检索可用

### Phase 1：LLM 工具调用 + 配置（约 1 天）
- 🔧 `src/llm/llm_client.py`：新增 `chat(messages)` / `chat_with_tools(messages, tools)`；DeepSeek 原生 FC + prompt-based 降级 + 动态模型路由
- 🔧 `src/settings.py`：新增 Neo4j、Bocha、PostgreSQL checkpointer、MCP、缓存阈值配置
- 🆕 `requirements.txt`：加 `langgraph-checkpoint-postgres`, `fastmcp`, `neo4j`（langgraph/ragas/redis 已有）
- 验证：messages API + function calling 通

### Phase 2：MCP 工具服务（全 MCP）
- `src/mcp/rag_server.py`：search_kb, hybrid_search, get_doc
- `src/mcp/graph_server.py`：search_knowledge_graph (Cypher)
- `src/mcp/web_server.py`：web_search (Bocha)
- `src/mcp/utility_server.py`：calculator, get_time
- `src/mcp/mcp_config.json` + `MultiServerMCPClient` 封装
- 验证：各 MCP Server 独立启动、工具可调

### Phase 3：GraphRAG
- `src/knowledge_graph/build_kg.py`：LLM 三元组抽取 → Neo4j MERGE
- `src/knowledge_graph/graph_tool.py`：GraphCypherQAChain 封装
- `src/knowledge_graph/schema.py`：灵活实体/关系（LLM 自动抽取，不预设）
- 验证：示例文档建图、多跳 Cypher 查询正确

### Phase 4：检索增强
- `src/retrieval/query_rewriter.py`：Query Rewrite + Step-Back
- `src/retrieval/hyde.py`：HyDE 假设文档嵌入
- 扩展 `src/retrieval/hybrid_retriever.py`：三路融合（加 Graph 通道）
- 验证：每个增强单独消融测试，对比召回提升

### Phase 5：Agent 核心（LangGraph 图）
- `src/agent/state.py`：AgentState
- `src/agent/graph.py`：StateGraph 组装、Send 并行、条件边、interrupt、编译
- `src/agent/nodes/`：supervisor, rag_worker, graph_worker, web_worker, general_worker, critique, replan, synthesizer
- `src/agent/prompts.py`：各节点 System Prompt
- `src/agent/checkpointer.py`：PostgresSaver 初始化
- 验证：simple/medium/complex 三条路径 + 自纠错 + HITL 中断恢复

### Phase 6：记忆 + 降本增效 + 集成
- 升级 `src/services/memory_service.py`：Redis异步短期 + Milvus长期偏好
- `src/services/cache_service.py`：语义缓存
- `src/agent/resilience.py`：熔断降级装饰器
- `src/services/agent_service.py`：AgentService 单例（图+checkpointer+MCP+记忆+缓存）
- 改造 `src/services/rag_service.py`：agent_ids 存在时委托 AgentService
- 验证：端到端 + 缓存命中 + 熔断降级

### Phase 7：评测 + 前端 + 可观测 + Docker
- 🔧 扩展现有评测框架：`src/services/agent_evaluator.py`（路由/工具选择维度）+ 复用现有 evaluation 路由与数据集上传
- 🔧 改造 `src/api/routers/chat.py`：SSE 新增 agent_route/thought/tool_call/critique/hitl 事件
- 🔧 前端（基于现有 Vue3 SPA）：加 Agent 追踪面板（路由卡片 + 思考时间线 + 工具调用 + HITL 审核UI + 来源引用）
- 🆕 轻量可观测：指标统计中间件（prometheus_client 已装，可选接 /metrics 端点）
- 🔧 `docker/docker-compose.yml`：新增 Neo4j + PostgreSQL（Redis/Milvus/RabbitMQ/MinIO 已有）
- 验证：完整演示 + 评测报告 + Docker 一键起

---

## 1 个月实施路线 + 最小可演示核心(MVP)

> 范围较大，按**关键路径优先**。先打通 MVP 能演示，再逐步加深。

### 周 1：地基（Phase 0-2）
- Phase 0 基线对齐：搬 DeepSeek + BM25 混合检索进原版
- LLM Messages API + Function Calling
- MCP 工具服务（先 RAG + Web 两个）
- 🎯 里程碑：Agent 能通过 MCP 调用检索工具
- 💡 原版已有 Milvus/评测/前端/记忆，省去大量地基工作

### 周 2：检索深度 + 图谱（Phase 3-4）
- GraphRAG 建图 + 查询
- 检索增强四件套
- 🎯 里程碑：三路融合检索 + HyDE/Step-Back 可消融对比

### 周 3：Agent 核心（Phase 5）← **最关键**
- LangGraph 图：并行 + 自纠错 + HITL
- 🎯 里程碑：**MVP 完成** = 复杂查询走完 Supervisor→并行Worker→Critique→Synthesizer，HITL 计划审核可演示

### 周 4：工程化 + 评测 + 前端（Phase 6-7）
- 记忆、缓存、熔断、评测、前端追踪面板、Docker
- 🎯 里程碑：完整可答辩版本

### 🔴 最小可演示核心（若时间紧，保这条线）
`Phase 1 → 2(RAG+Web) → 5(Supervisor+并行Worker+Critique+HITL) → 7(前端追踪+SSE)`
即使砍掉 GraphRAG / 部分检索增强 / 降本增效，这条线已是一个完整的"多Agent并行+自纠错+HITL"系统，能讲能演示。GraphRAG 和工程化作为**加分项**叠加。

---

## 验收标准

| # | 标准 |
|---|------|
| 1 | 向后兼容：未绑 Agent 的 Assistant 走原 RAG，行为不变 |
| 2 | Supervisor 正确分类复杂度并动态路由（路由准确率 > 80%） |
| 3 | 并行 Worker（Send API）正确 fan-out + Reduce 融合 |
| 4 | GraphRAG 多跳查询返回正确实体关系 |
| 5 | 三路融合 + 检索增强可消融对比，召回有提升 |
| 6 | Critique/Replan 自纠错闭环工作，不死循环 |
| 7 | HITL 计划审核：interrupt 暂停 → 前端审核 → 断点恢复 |
| 8 | 全 MCP：工具独立进程，Agent 跨进程调用成功 |
| 9 | 两级记忆 + 语义缓存命中 + 熔断降级生效 |
| 10 | 评测报告：检索/生成/路由/工具选择多维指标 |
| 11 | 前端完整追踪面板可视化推理全过程 |
| 12 | Docker 一键部署全链路通 |

---

## 项目名 + 简历描述（对标 Ragent-KOS）

**项目名建议**：`MARK` — Multi-Agent RAG Knowledge-base（备选：`GraphMind`、`AtlasRAG`）

**核心技术栈**：LangGraph | GraphRAG | MCP | FastAPI | Milvus | Neo4j | DeepSeek | Redis | PostgreSQL | Docker | Vue3

**项目描述**：
> 基于 LangGraph 构建的企业级 Multi-Agent 知识库问答平台，采用 Supervisor-Worker 多智能体**并行**架构，融合 GraphRAG、三路融合检索、MCP 工具调用、Human-in-the-Loop 与 Self-Correction 自纠错闭环，实现复杂查询自动拆解、多智能体并行协同推理与多跳知识检索，支持企业级知识问答场景。

**核心内容**（5 条）：
1. **多Agent并行编排**：针对传统 RAG 复杂问题推理不足，设计 Supervisor-Worker 架构，基于 LangGraph Send API 实现 Worker 并行调度与动态路由，构建 RAG/Graph/Web 多类 Worker，实现复杂查询自动拆解与 map-reduce 协同推理。
2. **GraphRAG 跨文档检索**：针对跨文档关联检索效果有限，基于 Neo4j + LLM 自动抽取实体关系三元组构建知识图谱，通过 GraphCypherQAChain 实现自然语言到 Cypher 的多跳推理，提升复杂关联问答准确性。
3. **三路融合检索**：构建 Dense + BM25 + Graph 三路 RRF 融合检索体系，引入 Query Rewrite、HyDE、Step-Back Prompting 与 Rerank 流程，提升检索相关性、降低模型幻觉。
4. **可靠性保障**：设计 Planner/Critique/Replan 自纠错闭环，基于 LangGraph Interrupt 实现 Human-in-the-Loop 计划审核，通过 PostgreSQL Checkpointer 实现工作流持久化与状态恢复，提升复杂任务可信度。
5. **工程化与评测**：集成语义缓存、动态模型路由、熔断降级降低推理成本，构建结构化日志+指标+trace 可观测体系；基于 Ragas 构建 50-80 题 Golden Dataset 实现检索/生成/路由准确率多维评测，形成持续优化闭环。

---

## 风险与对策

| 风险 | 对策 |
|------|------|
| 1个月范围大 | 保 MVP 关键路径（周3完成核心），GraphRAG/工程化作加分项叠加 |
| LangGraph Send 并行 + interrupt 学习曲线 | 周1-2先在 demo 里跑通最小并行图，再接业务 |
| DeepSeek Function Calling 偶发不稳 | prompt-based 降级解析（ReAct 格式 JSON） |
| Neo4j + 三元组抽取质量 | 先小规模文档建图，GraphCypherQAChain 自带 keyword fallback |
| 全 MCP 调试复杂 | 先单 Server 跑通，逐个加；保留直调测试脚本 |
| 8+ Docker 服务部署重 | 提供 `docker-compose.light.yml`（Chroma+SQLite+内存）轻量降级 |
| 演示领域未定 | 先用 repo 现有技术文档兜底，正式演示前再定领域+准备 Golden Dataset |

---

## 待确认（实现阶段再定）
- 演示知识库领域（影响 Golden Dataset 与图谱 schema）— 用户选"后续再定"，先用现有技术文档
- 项目最终命名（MARK / GraphMind / AtlasRAG / 用户自定）
