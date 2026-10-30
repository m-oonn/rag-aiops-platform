# 新策略 G11 单场真实复验协议（2026-10-29）

本轮完成免费准备与入口修正，**没有发送模型请求，真实执行尚未授权**。目标是验证新策略能否通过真实模型执行器完成下游监听、映射进程和允许日志的补查，并保留未查清原因；不是正式四组实验，也不替代已有 G11 的人工审核。

## 1. 本次要解决的问题

旧完整 G11 场来自监听补查策略加入前的源码，不能证明新策略实际执行；后续尝试只新增了3次请求就碰到累计上限16，亦未完成新策略闭环。免费固定决策、SSE与浏览器链路已通过，但真实模型是否按策略指定参数调用工具尚待复验。

本次只选择 `downstream_unreachable` 一场、G11 双开，不追加正常模型场、其他模型、四组或自动修复。控制器仍会进行正常与故障现场预检；这些预检、固定决策检查的证据和模型自主工具轨迹分别记账。

## 2. 已核实的配置与账本

| 项目 | 准备结果与拟用值 |
| --- | --- |
| 模型 | 私有 `.env.agent-test`，主/简单/证据角色均为 `glm-5.3-flash` |
| 端点 | `https://www.rightapi.ai/v1`；通过既有专用启动器加载，不改日常 `.env` |
| 调查入口 | `verify_windows_local_faults.py → evaluate_blind_cases → evaluate_model_case → evaluate_windows_probe.py → AIOpsService` |
| 单请求 | 输出最多4096 Token；HTTPX超时60秒，未将独立诊断用的120秒移入Agent |
| 重试 | SDK自动重试0、Agent重试关闭；结构化格式fallback仍可能另发请求，每次真实HTTP尝试均计数 |
| 最新续接账本 | `runtime/windows-local-faults-4e8ab583cb3e4235888948c9f42652ba/model-f2778ab5890b4527b818ae4ad1237a37/cost.json` |
| 账本 SHA256 | `9f7e595bf12030f4ac038bafa130b0983623e4ffc056816d12195cb9dba14d10` |
| 已有请求 | 16条，HTTP200且usage完整；累计输入100510、输出8108 Token，续跑校验通过 |
| 前缀 | 前13条与旧完整场逐项相同；后3条均保留，不重置或重复计为新增 |
| 拟新增上限 | **24次HTTP请求**，所以命令中的累计 `--max-model-requests` 必须为 **40** |
| 金额 | GLM费率仍未核实，`pricing_verified=false`；5 CNY参数只是现有预留口径，对未定价GLM不能构成实际金额封顶 |

旧完整场账本为 `runtime/windows-local-faults-955bb85e160542169fce5327419fdb9f/model-d44b9808125444d59a2e1651359ac6af/cost.json`，SHA256为 `b6c50b63768adaa44177c6dbf40813bd2f60c6a8930a6953c74b2793e60e945a`。该13条账本不能作为本次续接起点。

这条16请求链也不等于账户累计消费：最早超时链、独立请求重放及其他连通测试继续保留原记录；已有账户截图估算见 [费用核对](rightapi-cost-audit-20261028.md)，不能覆盖后来新增请求。预留0不代表免费。24次是待授权的工程复验上限，参考旧完整场13次与新增补查交互留出余量，不能保证24次内完成或保证金额。若用户要求人民币硬封顶，应先取得可核验计价或平台额度限制后另定方案。

## 3. 本轮发现并修正的入口缺口

单场控制器原会重新启动专用业务、清空两份日志，但未传本场观测起点，也未禁用共享 `probe_list_evidence`。四组入口已有这两项支持；本轮复用其子进程参数，没有新增运行框架。

- `evaluate_blind_cases` 在每场重置开始前记录带时区的 `observation_not_before`，存入控制器记录并传给子进程。它约束Probe证据及专用JSON日志行的采集时间，不把旧时间改新。
- 显式传 `isolate_history=True`；`evaluate_model_case` 将其变为已有的 `--isolate-history`，与金额预留参数解耦。模型工具集中去掉共享历史列表，本场数据库、thread和证据目录继续独立生成。
- 子进程返回后，除原有记录审计外，控制器核对实际记录中的共享历史开关及观测起点。子进程丢参或改参均拒绝放行。四组原有通过金额参数启用隔离的行为保持兼容。
- 发现单场控制器原先只在抛异常时停止，收到返回的失败机械检查结果仍可进入下一场；现先保存该结果，再停止并执行恢复，不丢掉失败场。

本轮新场隔离条件与旧完整场不同，旧场只能证明曾完成闭环，不能将新旧单场差异归因于两机制或计算机制提升。`knowledge-control`独立路径不在本轮修改范围，不把这次修复推广为所有历史入口均验收。

## 4. 执行流程与可观察验收

1. 付费授权后，先免费复核本机 `runtime/g11-retest-preparation-20261029-a/plan.json` 中选定源码、账本hash、模型、请求计数和命令；若源码或账本变更，更新准备记录并重新计算余量，不沿用旧的40。计划JSON用于审核，不是自动执行授权或强制拦截器。
2. 复用控制器创建唯一runtime目录与动态端口，启动本人专用业务、Probe/网关和本地知识夹具，核对状态、日志身份及允许范围。正常/故障预检失败即不进入模型阶段。既有常驻服务不操作。
3. 重置单场，记录观测起点；模型只接收中性症状“只读检查配置中的 localapp 是否可用”，和允许业务目录。故障答案与控制器停止动作不进入模型上下文。不得预写错误候选或诱导机制事件。
4. 真实调查若取得有效loopback依赖失败证据，核对正式策略的 `policy_selected_check`、原始 `model_suggestion` 与实际 `tool_trace`：

| 补查 | 要核对的实际工具参数与解释 |
| --- | --- |
| 依赖监听 | `probe_port_snapshot(local_port=本轮依赖端口, listening_only=True)`；端口从本轮配置读取，不固定6989 |
| 映射进程 | `probe_process_snapshot(service='downstream')`；核对允许的精确进程身份，未发现不等于已证实崩溃 |
| 独立日志 | `probe_text_log(service='downstream', path=本轮允许的downstream.log, ...)`；区分读到内容、空记录、失败及是否解释退出原因 |

5. 核对最终报告、结构化未决问题及建议均引用本场有效证据；没有监听、没有匹配进程只能支持当前状态。若日志未证实退出因果、事件通道未配置，应分别说明；不得称检查穷尽、编造退出原因或将控制器答案泄给模型。
6. 核对G11两个开关实际双开、保护/矛盾机会及实际动作。监听→进程→日志是四组共用补查规则，不计为创新机制事件；无矛盾机会则明确未覆盖，不强制触发。
7. 保存完整产物、恢复专用业务到正常、独立核对恢复状态，清理本轮所属进程与端口。提交用户逐条审核，不代填三个语义维度。

主验收是“真实模型执行器确实按精确参数完成补查，并诚实报告边界”。没有获得失败依赖证据、工具拒绝指定参数、检查未执行、采集失败、未产出报告分别记未覆盖或失败，不通过追加运行修饰结果。`localized_fault`或诚实`unlocated`可以接受，流程完成、定位是否正确、引用支持、建议适用性、机制行为单列；不能强求`confirmed_cause`。旧审批或机械检查pending不自动变通过。

## 5. 停止条件和产物

触及累计40次、超时/连接/鉴权/解析错误导致调查失败、usage缺失、记录或隔离门槛不通过，均保留失败和已发送请求；不自动另起一场、换模型或提高上限。自动网络重试关闭，原有结构化fallback只可在本场次数内发生，不承诺所有可恢复格式问题都立即结束。下一次发送前会继承这次最新账本，缺usage按原门槛拒绝续跑。

输出至少包括控制器`summary.json`/`blind-controller.json`/`model-attempt-*.json`、子场`events.json`、`tool_trace.json`、`mechanism_trace.json`、`report.txt`、`summary.json`、`evaluation-record.json`及选定源码快照、`cost.json`/`model-inputs`、SQLite和证据原文。运行失败时部分最终文件可能尚未生成，应列明缺件，不能补造；请求拦截单列`blocked_requests(sent=false)`。最后核对旧账本未变及清理结果。

## 6. 待授权执行命令（本轮没有运行）

工作目录为 `D:\ragPdfSystem++agent`。命令只有一场模型调查，控制器预检不缩减：

```powershell
$g11Args = @(
  'scripts/verify_windows_local_faults.py', '--run-model',
  '--model-stage', 'smoke', '--smoke-case', 'downstream_unreachable',
  '--mechanism-group', 'G11', '--allow-unpriced-model',
  '--max-model-requests', '40', '--max-output-tokens', '4096',
  '--budget-limit-cny', '5', '--previous-cost',
  'runtime/windows-local-faults-4e8ab583cb3e4235888948c9f42652ba/model-f2778ab5890b4527b818ae4ad1237a37/cost.json'
)
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py -- @g11Args
```

实际执行前需新确认“单场G11、最多新增24次、4096输出Token/请求、费用未定价且失败停止”，依据是根目录AGENTS.md的“新付费调用单独确认”。本轮准备不消费历史剩余授权。

## 7. 免费验证记录

最终六文件离线回归 **317 passed、1项真实故障单测按范围排除**，保留1条既有PyMilvus弃用警告。覆盖单场正反顺序/账本继承/恢复、独立隔离参数、实际记录审计拒绝共享历史或观测起点失配、失败返回停止后续，以及既有四组和窗口消费。先运行的7个缺口反例全部失败；后续新增实际记录用例因夹具缺少target与有效Probe返回有3项失败，补齐夹具后通过，没有降低生产审核门槛。中间309、315项不与最终结果累加。

没有重跑后端全量、前端、浏览器或真实连续重置；此次不涉及页面和Agent决策算法，免费验证到参数传递与记录审核，不宣称新单场已现场通过。本机准备目录仅保存脱敏配置、选定源码及账本hash、拟执行参数和免费核验记录；不保存凭据或私有profile内容/hash，不冒充真实场次。
