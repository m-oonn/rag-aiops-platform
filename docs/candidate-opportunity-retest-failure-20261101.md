# 候选机会提示修复后定向复验（2026-11-01）

## 执行范围

继承 `runtime/windows-local-faults-78fe20187f3741b0be9872856083b210/model-f19dacdb445e40a9b006118f882c70e9/cost.json` 的 188 条账本，累计预算上限 8 CNY、累计请求硬上限 195；使用 DeepSeek、`downstream_unreachable/G11`、`candidate-opportunity` 提示及每次最多 1024 输出 Token。运行目录为 `runtime/windows-local-faults-7da9d77cfadf4f319199ba3fb29494c0`。

此前失败暴露 JSON 降级重建 Prompt 时丢失 `partial_variables`。已修复 `ainvoke_structured` 并增加 partial prompt 的 JSON fallback 回归；结构化输出、调查策略和机制测试合计 202 项通过，仅有既有 PyMilvus 弃用警告。

## 结果

- 本场新增 6 次 DeepSeek 请求，全部 HTTP 200 且 usage 完整；峰值估算 0.125432 CNY。累计 194 次、已计价行峰值预留 4.922880 CNY，供应商账单未核；历史 52 条价格未知，累计真实金额仍为 `null`。
- 控制器事实检查确认 `localapp` TCP 可达但 HTTP 返回 503。Agent 只执行 inventory 与入口探测，随后因结构化决策失败停止；没有完成调查，报告为 `unlocated`，不得据此评估诊断能力。
- 机制轨迹识别到 1 次矛盾机会，但没有记录改向或阻塞；保护机会为 0，实际机制改变为 0。行为审计因此失败，不能把这场计为机制通过或失败效果样本。
- `finish_reason=length` 且 completion usage 达到配置上限 1024；JSON fallback 报 `JSONDecodeError`。function-calling 结果同时未通过 Pydantic 验证（`model_type`）。这是本场停止的直接原因。审计中的 `diagnosis_tracking=false` 是未形成有效最终诊断后的伴随失败项，不是首发故障。
- 控制器恢复正常；所属临时进程均已停止，端口释放，清理错误为 0。

## 后续边界

本次不再重跑。已授权 8 CNY 上限下，账面已计价峰值余量约 3.077120 CNY；但累计请求上限 195 已用 194 条，仅余 1 条，旧 52 条价格仍未知。再次真实验证前需免费处理输出截断/结构化降级边界，并单独确认新的请求上限；不得把当前余额视为自动续跑授权。
