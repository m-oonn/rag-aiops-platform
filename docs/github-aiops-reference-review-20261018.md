# GitHub AIOps 项目参考与本项目差距

调研日期：2026-10-18。方式：通过 GitHub API 读取仓库元数据、固定提交目录、关键文档和源码，与本地实现对照。未安装或运行上游项目，未调用付费模型，未修改业务代码或常驻服务。源码快照与提交记录保存在 `runtime/github-aiops-review-20261018-111038/`。原始文件域名连接失败后改用 API；后续触发匿名 API 限流，因此 ITBench 的具体 groundtruth 文件未读到，相关结论仅依据已读取的 README 和场景文档。

## 结论

最值得主参考的是 HolmesGPT 的现场调查方式和 AIOpsLab 的独立验收方式。K8sGPT 提供确定性检查的思路，Pi 提供运行循环与上下文设计，Kagent 提供审批暂停与恢复契约。Termcp 继续承担终端连接和操作审批。

保持 Python + LangGraph、Windows Probe、SQLite 证据账本和独立 Termcp。当前单机 Windows 范围不需要引入 Kubernetes 平台或重写 Agent 框架。参考这些项目并不代表它们的能力已经集成，也不代表我们的真实故障诊断已经通过。

## 已核对的项目

### HolmesGPT：优先学习怎么调查

固定提交：`2b9140c266f1a879afe295a3bc2465bbcc55ab00`，Apache-2.0。

- [调查提示词](https://github.com/HolmesGPT/holmesgpt/blob/2b9140c266f1a879afe295a3bc2465bbcc55ab00/holmes/plugins/prompts/generic_ask.jinja2)：追查下游、核实数据所属目标、区分事实与假设、查看应用日志，并追踪任务进展。这里一部分约束由提示词表达，不应理解为确定性的因果验证。
- [工具集管理](https://github.com/HolmesGPT/holmesgpt/blob/2b9140c266f1a879afe295a3bc2465bbcc55ab00/holmes/core/toolset_manager.py)：检查工具集前置条件和可用状态，检查自身有超时与错误状态。工具注册不等于工具可用。
- [大结果处理](https://github.com/HolmesGPT/holmesgpt/blob/2b9140c266f1a879afe295a3bc2465bbcc55ab00/holmes/core/tools_utils/tool_context_window_limiter.py)：过大结果落盘，返回预览和后续读取指引；存储失败时提示缩小查询。
- [评测格式](https://github.com/HolmesGPT/holmesgpt/blob/2b9140c266f1a879afe295a3bc2465bbcc55ab00/docs/development/evaluations/adding-evals.md)：场景输入、期望输出和工具数据组织为评测样例。文档也明确模型间表现有差异，不能照搬其测试结果。

适配：把现有服务目录、允许的依赖和 Probe 工具连起来，让每个检查回答一个具体假设；工具上线前验证权限和连通性。保留受保护原始证据，用受限检索读取片段。不要照搬它的通用 shell 或文件路径读取示例，更不能扩大本项目 Windows 权限。

### K8sGPT：确定性异常先由程序识别

固定提交：`bd42af70d3ba55eb328241b59555949ef49450fa`，Apache-2.0。

[Service analyzer](https://github.com/k8sgpt-ai/k8sgpt/blob/bd42af70d3ba55eb328241b59555949ef49450fa/pkg/analyzer/service.go) 直接检查无 endpoint、未就绪 endpoint 和相关事件，生成结构化失败项。也读取了 Pod analyzer。此部分证明的是资源规则检查，并非任意故障的自主调查。

适配：在 Probe 事实之上识别配置服务停止、指定进程缺失、期望端口未监听、依赖 TCP 失败等确定性现象。现象仍需要结合目标和时间解释；例如 TCP 失败不能直接等同于数据库崩溃，服务 running 不能直接等同于业务正常。规则应提供调查线索，不替代开放调查或直接生成最终根因。

### Kagent：审批必须属于运行状态

固定提交：`a0ad6cb98b02bf4a3537a2b6fdc04e71f315bdf3`，Apache-2.0。

- [人机交互契约](https://github.com/kagent-dev/kagent/blob/a0ad6cb98b02bf4a3537a2b6fdc04e71f315bdf3/docs/architecture/human-in-the-loop.md)：持久化暂停事件，绑定待审工具调用，在对应边界恢复。
- [审批 callback](https://github.com/kagent-dev/kagent/blob/a0ad6cb98b02bf4a3537a2b6fdc04e71f315bdf3/python/packages/kagent-adk/src/kagent/adk/_approval.py)：标记需确认的工具先阻止执行，再根据确认结果处理。

文档同时说明当前公共 MCP binding API 尚不能通用配置每工具审批；callback 的存在不能据此推断所有入口都能配置启用。

适配：继续复用现有 Termcp approval request ID、目标、原始参数、截止时间和 checkpoint 的绑定；验证真实审批不重放。本项目已有测试替身下的跨进程待审恢复，无需为参考 Kagent 改用 ADK 或 Kubernetes。

### Pi：保持调查循环小而清晰

旧 `badlogic/pi-mono` 在本次 GitHub API 查询中重定向到 `earendil-works/pi`。固定提交：`482c1381a00d8d00bc81697e4a980c593db6803e`，MIT。

- [Agent loop](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)：工具执行、事件、用户 steering、后续消息、工具前后 hooks、上下文转换都有明确入口。
- [上下文压缩](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/compaction.md)：保存摘要与保留边界，维护工具调用及结果的关系。

适配：在现有 LangGraph 中延续明确的工具前校验、工具后取证和事件输出；调查记忆记录已排除解释、未决问题、证据 ID 和时间。模型摘要不能替换原始证据。Pi 是通用 Agent 工具包，不能直接补足运维知识和业务拓扑。

### AIOpsLab：优先学习怎么考试

固定提交：`ccf08d0d1d5fa5b30f120e2e8549662d44411b35`，MIT。

- [项目与 Agent 接入](https://github.com/microsoft/AIOpsLab/blob/ccf08d0d1d5fa5b30f120e2e8549662d44411b35/README.md)：环境、故障、负载、遥测和 Agent 交互由编排器管理。
- [Task 评测入口](https://github.com/microsoft/AIOpsLab/blob/ccf08d0d1d5fa5b30f120e2e8549662d44411b35/aiopslab/orchestrator/tasks/base.py) 与 [量化函数](https://github.com/microsoft/AIOpsLab/blob/ccf08d0d1d5fa5b30f120e2e8549662d44411b35/aiopslab/orchestrator/evaluators/quantitative.py)：记录轨迹、步骤和 token，提供匹配、范围等判断；还可选用模型评价。量化文件里的 token 是近似口径，不是供应商实际账单。

适配：复用本机独立测试应用，把答案留给控制器，Agent 只接收症状及允许对象。按正常、进程退出、下游不可达、应用自身 5xx、端口冲突和关键证据缺失分场报告。定位正确、引用可追溯、边界合规、费用和环境恢复分别计分。无需为了学习评测方法而在当前机器安装整套云原生故障平台。

### ITBench：场景应像业务事故

固定提交：`b510385c83c06cc4851bdb7a919352c72ba197a1`，Apache-2.0。

[场景说明](https://github.com/itbench-hub/ITBench/blob/b510385c83c06cc4851bdb7a919352c72ba197a1/scenarios/README.md) 和主 README 将测试对象组织为隔离的运行环境、业务症状、可观测设施与故障机制。重点是“checkout 错误率高”这类业务问题，而非只检查工具返回成功。

适配：同一个访问失败症状对应多个不同原因，并加入恢复、正常和无法取证反例。当前没有运行其基准，也未核实其全部评分器或排行榜，因此不引用其分数作为本项目预期。

### Termcp：保留为连接与审批层

固定提交：`34a1cb533959c90f8d4b8ca51fb709f83ceb70b6`，MIT。

已读 [审批队列](https://github.com/open-mcp-ai/Termcp/blob/34a1cb533959c90f8d4b8ca51fb709f83ceb70b6/internal/approval/queue.go) 和 MCP approval gate。当前 `Approve` 在锁内检查 pending，但未直接核对 `ExpiresAt`；过期转换由 `Wait/expire` 等路径处理。单看本次文件不能宣称最新上游所有入口都已修复过期裁决问题，也未对其新版本运行复现。

继续使用本项目固定提交和最小修复镜像，升级前必须重新跑过期及并发裁决测试。新上游增加的文件、转发等能力不属于本次授权工具面。Termcp 本身不能提供根因调查策略。

## 与本项目代码的具体对应

| 优先级 | 建议 | 当前入口与差距 | 可观察验收 |
| --- | --- | --- | --- |
| P0 | 结论分级与因果约束 | `src/agent/aiops/strategies/investigation.py` 已做 target、时间、hash 与引用校验，但 `sufficient` 允许替代解释 unavailable 且仅有 limitation 时进入根因报告；引用存在不能证明相关性或因果。需复核哪些缺失检查会阻断确定结论 | 只有入口 503、下游证据缺失时，不得确认数据库为根因；事实、候选原因、已定位故障层分别表述 |
| P0 | 同症状不同原因盲测 | `scripts/verify_windows_local_faults.py` 与 `scripts/evaluate_windows_probe.py` 已有正常/下游不可达编排，免费采集覆盖更广；尚未全部变成真实模型未知答案测试 | 每场保存隐藏答案、模型实际输入、工具轨迹、判定、费用与失败；不以 workflow completed 充当定位正确 |
| P1 | 业务对象和依赖关联 | 复用已有服务目录、`planner.py` 及 Probe 本地配置；将入口、服务、进程、期望端口、日志和允许依赖现场交叉核实 | 用户只给 URL/服务别名能定位允许对象；名称相似、配置与现场不符时明确提示，不扩大主机/依赖权限 |
| P1 | 按假设选检查 | `strategies/investigation.py` 已有 next_check、替代解释及重复检查保护；增强检查目的与结果如何支持/推翻假设的表达 | 先查入口，再依据证据查应用或依赖；同一稳定检查不反复调用，不把无权限当正常 |
| P1 | 证据按需检索 | `executor.py`、`src/probe/storage.py` 和 `mcp_servers/probe_gateway.py` 已有留存与限制；核对调查上下文压缩后旧证据能否受限回读，避免只靠摘要或截断前缀 | 精确按 evidence ID/时间/字段读取允许片段，检查运行归属、脱敏、hash；不开放任意本机路径读取 |
| P2 | 工具真实就绪检查 | `tools.py`、`evidence_sources.py` 已报告工具缺失；进一步区分已注册、在线、认证失败、权限不足和数据陈旧 | 工具存在但 Probe 离线时显示不可用，不能把旧快照当实时事实 |
| P2 | 真实部署与审批验收 | 已有 checkpoint、Termcp gateway 和页面；测试替身下恢复已通过，真实 UI/Compose 仍待验收 | 真实批准仅执行一次，拒绝/过期不执行，进程重启后仍可核验；不与普通调查崩溃恢复混同 |

这些是调研建议，尚未实施。优先在现有授权与权限边界内完成 P0，再做业务关联；真实模型验收仍须对应费用授权。遵守用户此前决定，不引入总体调查预算或把固定步数耗尽视为调查成功；记录步骤、耗时和费用不等于新增运行上限。

## 不建议现在做

- 不因上游支持多 Agent 就增加多 Agent；先证明单调查器能正确使用数据。
- 不为 Kubernetes 项目重建本项目运行平台；保留 Windows 单目标边界。
- 不先加自动修复、无限制 shell 或更多管理权限；当前缺口主要在正确调查与验收。
- 不把 runbook 检索命中等同于知识改善根因判断；需要同场景对照并保留模型输入和证据。
- 不把确定性 analyzer 的异常提示或模型自评当最终根因裁决。

公开免费源码可参考；如实际复制代码，应保留对应 MIT/Apache-2.0 许可和必要声明。本轮未复制上游实现到业务代码。
