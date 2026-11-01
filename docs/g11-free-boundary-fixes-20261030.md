# G11 免费边界修复与核对（2026-10-30）

本轮只做源码修复、离线回归和历史材料审计，没有发送模型请求、没有新增现场观测，也没有修改旧账本。修复针对上一轮 G11 失败暴露的三个边界：原文引用必须连续、候选文字必须绑定结构化条件、自由文本矛盾不能覆盖已经独立核实的故障层。

## 当前账本边界

最新 G11 账本是 `runtime/windows-local-faults-8cb1f5c48486489faa80ffbf0dfdf698/model-d775dd96ddc141f5b65f2e850ba2e755/cost.json`：累计 26 条，其中 23 条返回、3 条 `ConnectError`；这 3 条没有 HTTP 响应和 usage。费用和供应商计价仍未知，不能把 `reserved_cny=0` 当作免费，也不能用旧额度继续发送。

旧报告 `docs/deepseek-g11-result-20261030.md` 描述的是另一场 19 请求 DeepSeek 场景，保留为历史材料，不代表最新 G11 结果。

## 代码修复

- `src/agent/aiops/strategies/investigation.py`
  - 模型只选择 `snippet_id`，程序依据证据账本回取原文；无效 ID、伪造片段和跨字段拼接不会被接受。
  - 候选必须绑定可验证的操作、对象、字段和期望值；只有绑定通过才参与假设保护或矛盾触发。
  - 保留候选已有预期、证据历史和反证记录，避免模型用自然语言悄悄改写身份条件。
  - Windows 路径比较统一词法格式，区分大小写、斜杠和 `.` 造成的同一日志重复读取。
  - 计划项已经实际执行时，停止原因记录为“计划检查已执行”，不再误报成“模型未提出检查”。
  - 现场同一谓词冲突只阻断受影响事实，普通 `contradictions` 自由文本不会整体抹掉独立核实的入口 503、依赖 TCP 失败等故障层。

- `scripts/mechanism_behavior.py`
  - 支持 `tracking.version=2`，审计时重新验证片段引用和条件绑定，防止只改事件计数伪造机制效果。

- `scripts/audit_historical_replay_boundary.py`
  - 只读记录历史重放的边界：如果新策略仍有可执行检查，审计明确拒绝把历史状态伪装成最终报告。

## 免费验证结果

- 后端全量：`1377 passed, 99 deselected`。
- 边界、机制及相关策略专项：`273 passed`。
- 旧定向交付审计输入：`223 passed`。
- 仅保留既有 PyMilvus 弃用警告；没有新增失败。
- `runtime/deepseek-g11-direct-20261030-a/delivery-audit.json` 已重新生成，确认历史材料 hash 不变、人工审核仍为 `pending`、本轮新模型请求为 0。
- 历史只读重放仍被以下门槛阻止：`historical proposal still requires an executable check; not a final replay`。这表示新版策略发现还有后续检查，不能把未完成调查包装成最终结论。审计结果见 `runtime/g11-free-boundaries-replay-audit-20261030/replay-boundary-audit.json`。

## 结论与限制

这些修复证明程序边界和离线回归成立，不证明新版代码已经通过真实模型复验，也不证明假设保护或矛盾触发已经带来诊断收益。最新 G11 的 26 条请求、3 条无 usage 的事实保持原样；人工诊断、引用支持和建议适用性审核仍待真实审核人填写。下一步仍先做免费历史语义核对，任何新增付费模型复验都必须另行授权。
