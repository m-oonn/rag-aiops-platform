# AIOps 多 Agent 智能诊断平台

**角色**：独立设计并实现 · **状态**：核心设计完成，实现中（预计 2026.08 完成端到端集成与 Benchmark）

> 面向毕业设计 / AIOps 岗位面试的深度项目介绍。简历缩写版可裁剪为 300 字 + 5 个技术点。

## 一句话定位

基于 LangGraph 的三 Agent 协作平台，核心创新是**动态分类（旁开式）故障诊断机制**——区别于市面"预定义分类+步骤失败触发掉头"的静态范式。

---

## 技术栈

- **Agent 编排**: LangGraph 1.0.7 (StateGraph + Send API 并行 fan-out + HITL interrupt + checkpointer)
- **大模型**: API 兼容层 (deepseek-v3 / qwen-max)，原生 bind_tools function calling，ReAct / Plan-Execute 双范式
- **RAG**: Milvus 向量库 + BGE 重排 + Celery 异步任务队列
- **MCP 工具**: fastmcp 自建 mock 服务 (指标采集/日志检索)，MultiServerMCPClient 多服务聚合
- **后端**: Python (FastAPI + SQLAlchemy + Alembic)，同步/异步混合架构
- **前端**: Vue3 + SSE 流式对话
- **基础设施**: Redis 会话缓存 + RabbitMQ 消息队列 + MinIO 对象存储 + Docker Compose 一键部署

---

## 项目规模与工程能力

### 一、完整基线系统（已建成）

一个**生产可用**的 RAG 智能问答平台，包含：

- **数据模型层** (15+ 表)：多租户 RBAC 权限体系、KB 知识库管理、Documents 文档分块 + 向量化流水线、Conversations 对话管理、Assistants 多 Agent 配置 (type/tools_config/reasoning_config/execution_config 全 JSON 字段)
- **RAG 管道**：文档解析 (PDF/Word/Markdown) → 分块策略 → BGE 向量化 → Milvus 存储 → 检索召回 → 重排序 → 大模型生成
- **评测框架**：Built-in 4 指标 (faithfulness/answer_relevancy/context_recall/context_precision)，支持自定义 prompt
- **MCP 工具服务**：自建 mock 指标服务 (8004) + 日志服务 (8003)，手搓完整 ReAct 闭环验证——模型自主从多服务聚合工具列表中选工具 → 真执行 → ToolMessage 按 tool_call_id 回填 → 人话总结
- **前端面板**：流式对话 + 知识库管理 + 评测 UI

### 二、核心创新机制（架构设计完成，实现中）

**问题驱动**：真实故障排查中，端口占用类故障**无 ERROR 日志、无指标峰值**（端口在 LISTENING、环境变量存 HTTP_PROXY——数据长得和健康态一模一样），市面主流 RCA 系统依赖异常信号驱动候选生成，对这类"信号外故障"存在**结构性盲区**。

**创新方案**：动态分类（旁开式）——不预穷举故障类别，边查边生成。

**机制闭环**：
1. **矛盾触发**（非步骤失败）：当查到的证据与当前分类假设矛盾时触发反思——"网络全通但应用全挂"是矛盾而非执行失败，让系统在第一个打脸事实处动念
2. **怀疑不杀、证伪才杀**：矛盾信号只调低分数、不停旧线；只有"逻辑排除"级证据（如"配置文件中压根没这个服务"）经两层确认后才关线。**焊进数据结构**——怀疑路径在代码层只能碰分数字段，碰不到状态字段
3. **旁开并行**：怀疑达到阈值时不停旧线，旁边新增一条最可疑方向并行，让事实竞争而非判断裁决
4. **收敛三旋钮**：N(并发上限，毕设 N=3) / floor(打分闸门，50→25→12→0 折半降) / 关线规则(证伪退场)
5. **多维打分体系**：四维度(矛盾强度/证据可信度/关联广度/旁开必要性) → LLM 出五档离散评级 → 固定系数映射(1.0/0.7/0.5/0.3/0.0) → 证据可信度自身当权重合成。骨架参照 AdaRubric (阿里·ACL 2026)，来源替换为用户设计
6. **双层分类**：上层 12 大类固定池保一致性 (PHM Society 2025: 86% 命中率)，下层池外自由兜底防僵死 (带结构化溯源字段)

**与人无我有的三点**：
- 触发信号是**矛盾**而非步骤失败（vs 普通 Replan）或异常信号（vs SpecRCA/ThinkFL/RCLAgent）
- 动作是**旁开加线**而非杀旧换新（vs 跳出式）或纵向加深（vs RCLAgent 的 Critical Reflection）
- 反思指向是**类别选对没**（横向）而非根因找全没（纵向）

**与最强对手 SpecRCA (ICSE 2026) 的定位**：它赌"一次铺够广就不用迭代"，我赌"第一张网会撒错、需中途重撒"。二者走相反路，针对不同故障类型。

### 三、研究深度

- 竞品分析：亲读 SpecRCA (ICSE 2026 NIER) / ThinkFL (arXiv 2504.18776v2) / RCLAgent (arXiv 2508.20370v1) 三篇全文，用三把尺子（触发维度/线间通信/HITL 定位）逐一量过，形成差异化论证
- 工程参考：调研 7 家生产级 Agent 架构 (Claude Code / OpenAI Codex / Cursor / Trae / Amazon Q / Replit / Manus)，提取 30 条可直接参考的工程实践，完成五点设计对比分析
- 答辩弹药建设：建立 72 条统一文献索引，覆盖 RCA 竞品 / LLM 打分框架 / Agent 工程实践 / 多 Agent 共识 / 假设生成 / LangGraph 官方 / 分类体系 / 方法论 6 个域
- 范式级论证闭环（答辩已备）：穷举不可能 → 必须迭代生成 → 迭代靠矛盾触发（非信号）→ 连扩大输入都救不了信号范式（信号外故障在数据里不显异常，只矛盾能定位）

### 四、工程决策记录

关键设计决策均有记录、说得出 why：

- **岔路 A (RAG 集成方式)**：选"检索即工具 (bind_tools)"而非固定检索步——各分类线按需调 RAG，Agent 自决何时检索
- **岔路 C (State Schema)**：不套用 LangGraph 官方 plan-execute 四字段模板 (线性步骤无法承载多线并行+打分+血缘)，自设计线级 6 字段 + 全局 5 字段，自定义 reducer 防并行写冲突
- **工具分配模式**：Replanner 方向分配 + Worker 自主微调（LangGraph 官方混合模式 + Microsoft StepFly 验证）
- **HITL 中断策略**：两处——预算收敛(系统走到头) + PROVEN 触发(诊断完成)，Planner 初始输出不中断（旁开机制本身是纠错）

---

## 面试可讲

| 面试官问 | 你有 |
|---------|------|
| "这个项目你做了什么" | 独立设计+搭建完整平台，从数据库 schema 到前端 UI 到 Agent 编排全链路 |
| "跟市面上的 AIOps 有什么不同" | 动态分类/旁开式 vs 静态预定义分类+步骤失败触发——三把尺子量过三篇竞品论文 |
| "为什么这么设计" | 不是拍脑袋——三条市面依据(Rasa 语义漂移 / ACH 分析师偏差 / AdaRubric 反等权)，均引自权威论文 |
| "遇到什么难点" | State schema 设计——官方模板装不下多线并行+打分+血缘，自设计数据结构 + reducer + 全场重算机制 |
| "怎么验证方案正确性" | Mock 两个场景（普通故障验证打分引擎 + 信号外故障验证旁开链路），PReMISE 四轴审计验证打分体系 |
