# 面向 ragPdfSystem 的 pi-agent 架构与 GitHub 源码调研

调研日期：2026-10-20。范围：结合本项目的 PDF/RAG 与 AIOps Agent，核对 Pi agent runtime 和相关 AIOps 开源实现。源码快照存于 `runtime/github-aiops-review-20261018-111038/`；Pi 固定提交 `482c1381a00d8d00bc81697e4a980c593db6803e`（MIT）。本次只新增调研文档，不改业务代码、不运行上游项目。

## 结论

Pi 是通用的事件驱动 Agent runtime，不是面向运维的诊断系统。它提供模型流式调用、工具调度、事件生命周期、用户 steering/follow-up、上下文转换和 coding-agent 会话压缩。ragPdfSystem 的 AIOps Agent 使用 LangGraph 的 Plan-Execute-Replan 图，另有证据来源校验、假设/反证裁决、目标白名单与审批状态；两者解决的问题不同。

本项目已采用了 Pi 的部分工程思想：工具调用前后事件、执行时间记录、重试与历史压缩、调查记忆以及持久化步骤快照。适合继续吸收的是运行轨迹的一致性、长任务恢复和上下文管理；不建议为了“像 Pi”而替换 LangGraph，也不能把会话摘要当作原始运维证据。

## Pi 的分层结构

Pi 仓库（`earendil-works/pi`）采用 TypeScript monorepo。与本项目最相关的两个层面：

1. **Agent runtime（`packages/agent`）**：定义 Agent 消息、工具、上下文和配置；以 `agentLoop` / `agentLoopContinue` 暴露流式事件流。具体模型协议由 `@earendil-works/pi-ai` 适配，工具实现由调用方提供。
2. **Coding agent（`packages/coding-agent`）**：在 runtime 上增加会话条目、分支、扩展、自动压缩、文件操作工具和交互界面。Pi 的 coding-agent 功能不是底层 agent loop 必需部分。

```text
应用 / Extensions
  ├─ AgentContext: transcript + 可执行 tools
  ├─ AgentLoopConfig: model、stream、context transform、hooks、steering/follow-up
  └─ agentLoop / agentLoopContinue
       ├─ prepareNextTurn / prepareRequest
       ├─ 调用模型并流式发出 assistant message 事件
       ├─ 校验并准备 tool call
       ├─ beforeToolCall → 执行（并发或顺序）→ afterToolCall
       ├─ 写入 toolResult 到 transcript
       └─ finishTurn + steering/follow-up → 下一轮或 agent_end
```

这不是“模型直接执行工具”的黑盒：loop 维护规范 transcript，模型的消息经过 `convertToLlm` 才成为供应商请求；runtime 的 `context.tools` 是实际可执行工具集，工具声明变化也会同步记录到 system transcript。工具并发由默认策略决定，但工具可声明 `executionMode: sequential`；工具结果仍按原调用顺序合并进上下文。

## Agent loop 的关键机制

固定源码：[agent-loop.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)。本地快照：`runtime/github-aiops-review-20261018-111038/earendil-works__pi/sources/packages/agent/src/agent-loop.ts`。

| 阶段 | 源码行为 | 对系统的意义 |
| --- | --- | --- |
| 启动/续跑 | `agentLoop` 接收新 prompts；`agentLoopContinue` 要求已有上下文末条是 user/toolResult | 新对话与工具结果后的延续共用同一主循环 |
| 下一轮准备 | `prepareNextTurn` 可替换 context、追加消息、更新模型/推理级别；`prepareRequest` 在每次模型请求前调整请求上下文 | 压缩、模型切换等逻辑是可插拔生命周期钩子 |
| 模型流 | assistant 的 text/thinking/tool-call delta 转成 `message_update`；最终消息写回 context | UI、日志和中间层消费统一事件，而不是等待最终文本 |
| 工具调用 | token 截断的 tool call 一律拒绝执行；参数验证和 `beforeToolCall` 在实际调用前；有 `afterToolCall` 整理结果 | 降低不完整参数执行风险，并提供策略/观测扩展点 |
| 调度 | 工具批可顺序或并行；tool result 与 tool-call ID 关联并追加；支持 `terminate` 结束本轮 | 工具执行结果构成下一次模型输入，失败也有结构化结果 |
| 队列 | steering 消息尽快进入当前任务；follow-up 消息在 Agent 自然停止后开启后续轮；`finishTurn` 可 end/continue | 区分“打断当前工作”和“排在当前工作之后” |
| 事件 | agent/turn/message/tool 各自有开始、更新、结束事件，Agent event stream 以 `agent_end` 收束 | 运行生命周期可以被 UI、存储和扩展订阅 |

Pi 的“工具前后”并不自动等于安全审批：权限、审批和工具实际能力仍由宿主应用/extension 实现。Agent runtime 负责调用生命周期，不提供本项目所需的现场目标白名单与证据因果判定。

## 会话持久化与上下文压缩

Pi coding-agent 的压缩说明见固定版本文档 [compaction.md](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/compaction.md)。它把 transcript 保存为有 parent/entry ID 的持久会话条目，压缩条目带摘要、保留边界 `firstKeptEntryId`、压缩前 token 数、摘要 token 使用量与扩展 details。上下文投影由摘要加保留边界后的原始消息组成；历史原始条目并不因此删除。

自动压缩按 `contextTokens > contextWindow - reserveTokens` 触发，优先从完整 user-message span 边界切分；不能切在 tool result 上，避免孤立 tool call 与 result。超长单轮可拆分为历史摘要与当前轮前缀摘要。Coding-agent 还支持分支切换摘要，将另一条会话路径的进度带入当前路径。

对 ragPdfSystem 的重要边界：摘要可以压缩“调查做过什么、当前假设和下一步”，但必须保留可追溯的 evidence ID、来源、采集时间和原始证据回读能力。Pi 的摘要机制不能代替本项目的 `evidence_reader`，也不证明摘要内容仍然真实或新鲜。

## 与本项目的架构对照

本项目实现位置：`src/agent/aiops/graph.py`、`state.py`、`planner.py`、`executor.py`、`replanner.py`、`run_store.py`、`events.py`、`evidence_reader.py`。

```text
HTTP /api/v1/aiops (SSE)
        │
        ▼
LangGraph StateGraph (thread_id + checkpoint)
  planner → executor → replanner ──continue/replan──┐
      ▲                    │                         │
      └────────────────────┘                         └─ respond → end
           │
           ├─ MCP / Probe tools + argument guards
           ├─ evidence validation / raw evidence ledger
           ├─ investigation strategy / hypothesis judgment
           └─ optional terminal review / human approval interrupt
        │
        ├─ SSE event stream
        ├─ SQLite run/step snapshots
        └─ final structured diagnosis + citations
```

| 维度 | Pi | ragPdfSystem | 判断 |
| --- | --- | --- | --- |
| 控制流 | 通用循环，模型可连续提出多个工具调用并由调度器执行 | 业务图节点显式定义规划、执行、重规划、裁决与结束 | Pi loop 更适合通用聊天/coding runtime；本项目图更适合可审计诊断阶段 |
| 状态 | AgentMessage transcript + runtime context；coding-agent 会话条目提供持久历史/分支 | `PlanExecuteState` 保存计划、步骤、原始证据、调查记忆、假设空间、结论；LangGraph checkpoint 按 thread 保存 | 本项目业务状态更丰富，Pi transcript 更通用 |
| 工具 | 工具 schema/handler、参数验证、hooks、顺序/并发调度 | MCP 工具装载、确定性参数守卫、目标与来源校验、敏感命令审批 | 两者都把执行置于 runtime 控制；本项目安全与运维语义更强 |
| 事件 | message delta 与 tool 生命周期事件组成 AgentEvent 流 | LangGraph 节点状态映射成 SSE 事件；步骤快照落 SQLite | Pi 可参考事件连续性；本项目已有 API 契约和持久快照 |
| 人工介入 | steering/follow-up 队列与扩展钩子 | LangGraph `interrupt` + checkpoint + Termcp approval ID/过期信息 | steering 是插入消息，不等同于具备业务审批授权 |
| 压缩 | coding-agent 有 token-aware transcript projection、边界与 summary entry | executor 使用 `compress_history`；另保存 `investigation_memory`、证据文件及 run snapshots | 值得学习摘要/边界组织；证据必须继续独立留存 |
| 领域判断 | 通用工具 Agent，不知道本项目目标服务、Windows Probe 或根因标准 | 目标目录、现场证据校验、假设与反证策略、结论分级 | 不可直接互换 |

## GitHub 相关项目的适配排序

前次 GitHub API 源码核查固定版本和路径详见 [AIOps 开源参考评审](github-aiops-reference-review-20261018.md)。从 ragPdfSystem 的目标出发：

| 项目 | 最相关源码贡献 | 适配到本项目的用途 | 不应据此推断 |
| --- | --- | --- | --- |
| [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) | 调查提示词、工具集状态检查、大结果截断/回读、场景评测 | 目标和工具就绪校验、证据按需回读 | prompt 要求核对数据不等于程序保证因果 |
| [K8sGPT](https://github.com/k8sgpt-ai/k8sgpt) | 针对 K8s 资源的确定性 analyzer | 将确定性现象作为线索，而非直接根因 | Kubernetes analyzer 不适合直接移植到 Windows 单机 Probe |
| [Kagent](https://github.com/kagent-dev/kagent) | checkpoint 化人机审批、待批工具调用边界 | 对照审批请求与运行状态绑定、恢复语义 | 通用 MCP callback 不代表每个入口均有审批配置 |
| [AIOpsLab](https://github.com/microsoft/AIOpsLab) | 环境/故障/遥测编排与评测轨迹 | 隐藏答案、控制器和 Agent 分离、独立测量诊断质量 | mock 或单次成功不能代表准确率 |
| [ITBench](https://github.com/itbench-hub/ITBench) | 贴近业务事故的场景组织 | 同症状多根因、正常/缺证据反例 | 不应引用未运行基准的排行榜分数作为本项目结果 |
| [Termcp](https://github.com/open-mcp-ai/Termcp) | MCP 终端会话和审批/执行层 | 继续作为受控远程终端工具与审批边界 | 它不是诊断 planner，也不替代证据治理 |

对 PDF/RAG 主流程，已有源码比 Pi 更直接相关：PDF 解析与切分在 `src/processors/`，向量/BM25/混合检索在 `src/retrieval/`，知识库 MCP 在 `mcp_servers/rag_server.py`，AIOps 规划前参考检索和调查中知识检索分属不同调用点。知识库文档应作为 runbook 先验，现场 Probe/MCP 返回才是本次现场证据；两种来源不可混为同一级证据。

## 建议

1. **保留当前 LangGraph AIOps 拓扑。** 不以通用 loop 替换 planner/executor/replanner；后者承载策略状态、证据门槛和人工审批。
2. **用 Pi 的事件模型审视 SSE/快照契约。** 确保开始、增量、结束、工具拒绝/失败、取消和 checkpoint 恢复均可解释；事件可观测性不能代替持久化证据账本。
3. **继续加强长调查上下文治理。** 压缩时保留目标范围、关键证据引用及 hash/时间、被排除假设、待查问题、工具可用性；遗漏原始上下文时保留可回读证据 ID。不要只保存模型自由摘要。
4. **把恢复能力分开验收。** HTTP/SSE 客户端断线后的重连续读、LangGraph checkpoint 中断恢复、Termcp 审批恢复是三种语义，分别需要 cursor/事件 ID、thread checkpoint、审批 ID 与幂等执行验证。
5. **优先用盲测评估诊断，而非更换 agent 框架。** 同症状不同故障、健康对照、证据缺失和错误目标场景应分别报告定位正确、诚实未定位、错误根因、引用支持度、权限合规、耗时与实际费用。
6. **PDF/RAG 侧保持来源分层。** 文档 chunk 的引用应回到 PDF 页码/原文；RAG 命中仅给出“手册建议”，不能成为目标现场故障事实。评估检索召回和 Agent 根因判断时分开计分。

## 范围与限制

- Pi 源码取自固定提交的本地快照；快照包含 agent loop 和 compaction 文档，但不是所有 monorepo 文件的完整 clone，因此会话实现细节以该提交文档和已读取源码为准。上游 `main` 可能继续变化。
- GitHub AIOps 参考报告的固定提交、许可和已核验文件路径见链接报告；它记录的是源码静态阅读，不是安装运行或与本项目做同场 benchmark。
- 本文没有重新执行真实模型、外部服务、PDF 端到端或付费评测。已有本地测试/验收事实以各专项记录为准，不作为本次新验证结果。
- 上游 MIT/Apache 许可适用于遵守许可条件时的参考/复制；本次没有复制上游实现代码。
