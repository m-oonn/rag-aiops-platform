# Agent 交接：错端口场景与评测入口（2026-11-05）

## 一句话结论

本轮最新评测没有进入模型：正式目标解析在模型调用前把输入判为 `unlocated`。触发原因是用户症状指向业务入口 `edge`，但评测配置的业务目录只登记了 `localapp`（别名“测试应用”）。免费验收测试手工构造了 `target_resolution.service=edge`，绕过正式解析，所以漏掉了这个接入缺口。当前证据指向**测试/业务目标目录接线与回归覆盖错误**；不能据此归因模型或诊断节点。

## 按时间整理的工作

### 1. 请求 719–732：受控停止场真实诊断

- 真实模型完成流程并定位到 downstream 故障层；读取了 edge 日志，但其 `503 / upstream connection failed` 只说明传播链症状，不能解释更深原因。
- downstream 日志有 `shutdown_requested / controlled_stop`，但停止发起者为 `unknown`；没有文件创建者历史、完整生命周期日志，也没有配置独立事件通道。现有来源无法回答谁停止了服务、为何停止。
- 机械审核通过不等于语义诊断通过；人工审核仍待完成。恢复和业务复测由控制器完成，不是 Agent 按报告修复的验收。
- 账本当时为 732 条、累计预留 23.632064 元；结果及细节见 [续测结果](question-check-live-continuation-result-20261105.md) 和 [证据能力审计](investigation-evidence-capacity-audit-20261105.md)。

### 2. 错误下游地址场：搭建并通过免费环境验收

- 建立 edge → localapp → downstream 的真实本机 HTTP 拓扑，预设故障为 localapp 启动时加载错误下游端口；正确下游仍健康。隔离答案不进入普通知识材料或 Agent 输入。
- 免费验收实际采集 19 条观测，核验配置、日志、端口、进程、请求 ID、证据窗口、答案隔离、修复后重启和恢复清理；通过。
- 这个验收证明了现场证据可产生、可采集、可隔离和业务可恢复；**没有证明正式目标目录能解析该用户症状，也没有证明模型自主诊断**。
- 报告与复现命令见 [环境验收](wrong-endpoint-environment-acceptance-20261105.md)。

### 3. 请求 733–750：一次真实自主诊断

- 模型文字上识别了“localapp 实际加载端口 11751，而登记的 downstream 在 11750”，并主动选择了关键日志、依赖、端口和服务对照检查。
- 最终结构化提议没有填写主 `supporting_evidence` 和 `root_cause`；系统按现有规则只输出故障层与泛化建议。因此不能判完整根因诊断通过。
- 当时另发现并离线修正了证据交接问题：`read_run_evidence` 是只读证据工具，却被按 Probe 工具校验；控制器首次日志快照在业务请求之前；保存检查自动延续可能重复执行相同查询。离线定向回归为 13 个文件 388 passed，另一次聚焦调度 181 passed。修复没有真实复测模型效果。
- 报告和问题细节见 [真实诊断结果](wrong-endpoint-live-result-20261105.md) 及 [交接修复](wrong-endpoint-handoff-closeout-20261105.md)。

### 4. 最新一次真实评测入口尝试：模型请求为零

- 第一次启动因授权文件与输出目录冲突，在启动场景前终止，材料保留在 `runtime/wrong-endpoint-model-integration-live-20261105-a/`。
- 第二次场景自身启动、运行及恢复清理通过，但评测器只采集到 inventory，随后因目标解析失败结束：症状原文是“edge 的 `/api/availability` 业务请求失败”；本轮目录仅登记 `localapp`，别名为“测试应用”。正式解析要求精确匹配登记服务、别名或完整入口 URL。
- 第二次诊断结果是 `unlocated`，`model_requests` 仍为 750（历史总数），`new_request_count=0`，本轮预留费用 0。结果见 `runtime/wrong-endpoint-model-integration-live-20261105-b/report.json`、`runtime/wrong-endpoint-model-integration-live-20261105-b/model/cost.json` 及 [结果文档](wrong-endpoint-live-result-20261105.md)。
- 这是评测前置接线失败，不是模型诊断失败；本次不能用于评价模型、调查节点或取证工具。

## 已确认的测试缺口

`scripts/verify_competing_hypothesis_scenario.py::verify_endpoint_round` 手工构造了：

```python
'target_resolution': {'status': 'resolved', 'service': 'edge', ...}
```

而真实业务目标由 `src/agent/aiops/target_catalog.py::resolve_target` 解析，调用链在 `src/agent/aiops/planner.py`。因此免费验收从“已解析”状态开始，未覆盖评测配置、用户症状到正式目标解析的路径。相关测试 `tests/test_competing_scenario_preflight.py` 也只断言这个手工注入状态能进入决策输入。最新失败说明该回归范围不完整，不代表所有先前工具、环境回归均无效。

目标语义需要谨慎处理：用户报的是 edge 业务入口失败，预设直接故障位于 localapp 的下游地址配置。不要为了让解析通过而把故障对象偷偷改成 localapp。应先确认正式目录是否应该登记 edge 入口，并将 edge 映射到 localapp/下游检查范围；若现有产品设计明确要求用户指定内部服务，再修改症状文案并说明诊断对象变化。两种做法都必须通过正式 `resolve_target` 验证。

## 交给下一位 Agent 的唯一下一步

先做免费修复和回归，不调用真实模型：

1. 检查本轮业务目录生成位置、入口 URL 与 `target_catalog` 配置，确定 edge 作为用户业务入口应如何映射到 Probe 白名单内的服务和依赖。
2. 回归必须调用正式 `resolve_target`（最好经正式 planner 前置路径），覆盖 edge 入口可唯一解析、未登记目标在模型调用前失败，以及别名/完整 URL 的既有行为；禁止测试伪造 `target_resolution` 来证明解析成功。
3. 免费跑完整环境预检，确认场景可以进入模型决策输入且答案隔离、预算守卫和恢复清理仍通过。若只能验证到解析而不能证明请求已到模型边界，应如实标成部分验收。
4. 真实模型调用另行等待用户明确授权。本轮一次性历史超时例外已绑定本次尝试，不得复用；不要自动重试、改账本或回填失败记录。

完成免费修复后，再基于新证据判断是否值得申请一次模型验证；不要改调查节点或报告规则来处理这次 `unlocated`。

## 工作区注意事项

当前工作区存在大量跨模块已修改/未跟踪文件，包含用户已有工作和前序阶段产物。本交接没有对它们做归属推断、回滚、清理或暂存。接手者应先查看 `git status --short` 和具体 diff，只修改目标目录解析接入及相应回归。
