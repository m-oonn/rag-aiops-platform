# 四组真实预实验结果（2026-11-01）

本次在当前修复版本上直接执行了有限四组真实预实验。用户授权本批最多 5 CNY；由于 GLM 价格未核定，按授权条件切换到已核价的 DeepSeek `deepseek-v4-flash`，不使用 GLM。

## 执行范围

- 场景：`mechanism-v1` 的 `normal`、`application_config_error`、`downstream_unreachable`，每个场景运行 G00/G10/G01/G11 各 1 次，共 12 场。
- 账本：继承 2026-10-30 的 73 条 DeepSeek 账本，不清零、不回退。
- 限制：每场最多新增 12 次请求，累计上限 217 次，单请求输出上限 4096 Token；失败、缺 usage、超预算或恢复失败应停止。
- 真实模型请求：全部使用 `deepseek-v4-flash`，关闭 SDK 和 Agent 自动重试。

## 结果

| 场景 | 完成场次 | 新增请求 | 本场峰值费用（CNY） | 报告类型 |
|---|---:|---:|---:|---|
| `normal` | 4/4 | 30 | 0.910000 | 4 × `unlocated` |
| `application_config_error` | 4/4 | 34 | 1.170000 | 4 × `localized_fault` |
| `downstream_unreachable` | 4/4 | 42 | 1.890000 | 4 × `localized_fault` |
| **合计** | **12/12** | **106** | **3.970672** | — |

本批最后一条账本累计为 179 条请求，峰值预留为 4.660508 CNY，低于 5 CNY 上限。179 条请求均返回 HTTP 200 并带完整 usage；没有缺 usage、非 200 响应或预算停止。账本中保留 1 条历史的 `sent=false` 上限拦截记录，本批没有新增拦截。

四组机制审计均通过结构和配置门槛，但 12 场的保护机会和矛盾机会均为 0，实际保护改向和矛盾改向均为 0。因此本批只能说明机制接线和审计正常，不能据此判断两项机制有效或无效。12 场人工语义审核仍为 `pending`；`localized_fault` 表示故障层已被报告并通过机械证据门槛，不等于根因因果解释已经确认。

现场控制器状态为 `completed` / `normal_restored`。最终临时进程已停止、测试端口已释放、清理错误为空；完整控制器检查记录 38 条，未修改生产代码、常驻服务或历史账本。

## 记录与复核

- 控制器：[four-group-controller.json](../runtime/windows-local-faults-f51fecb4a33940a5a14af1b75ebe1ee0/four-group-controller.json)
- 工程汇总：[summary.json](../runtime/four-group-5cny-20261101-summary/summary.json)
- 运行总览：[summary.json](../runtime/windows-local-faults-f51fecb4a33940a5a14af1b75ebe1ee0/summary.json)
- 最终账本：[cost.json](../runtime/windows-local-faults-f51fecb4a33940a5a14af1b75ebe1ee0/model-e4a531f8196f4f97b5d6d05e05b6e878/cost.json)，SHA-256 `4e97a78cfa76b2fb28a1395d5e8cba09dd9297efd4ea58523c63fa09d3df75da`
- 授权记录：[human-smoke-review.json](../runtime/four-group-5cny-20261101-a/human-smoke-review.json)

`scripts.summarize_evaluations` 对 12 个结果返回 `passed=true`。该汇总是工程一致性核验，不是独立统计实验，也没有替代人工诊断正确性审核。
