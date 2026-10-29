# 模型预算拦截原因区分（2026-10-29）

## 问题

G11 复验沿用13条旧请求，累计请求上限为16，因此第4条新增请求被本地拦截。拦截没有发送到供应商，但 Probe 评测返回的通用错误却称“累计5 CNY预算”，把请求数上限误报为金额上限；自主隔离评测也没有稳定的机器可读停止原因。

## 修正

- `PaidRequestBudget` 为拒绝提供稳定原因码：`unpriced_model`、`max_requests`、`per_run_cost_limit`、`cumulative_cost_limit`。
- 被拦截的请求另存于 `cost.json.blocked_requests`，记录序号、模型、拒绝原因和 `sent=false`；不追加到实际发送的 `requests`，也不增加费用预留。
- Windows Probe 评测的本地 402 响应返回具体拒绝码；运行记录和摘要分别保存原因码与可读说明。旧累计账本中的拦截记录在续跑时保留。
- 隔离自主评测在场次摘要写入停止原因码。未发送的请求不会被算成模型调用。

## 验证与边界

- 相关离线回归：`tests/test_windows_probe_evaluation.py`、`tests/test_four_group_controller.py`、`tests/test_model_request_diagnostics.py`、`tests/test_evaluation_record_consumption.py`，175项通过，保留1条既有 PyMilvus 弃用警告。
- `git diff --check` 通过。
- 本轮未运行模型、未发送HTTP请求、未启动服务、未触发故障；没有改动或重算旧运行结果与费用账本。
- 全量后端回归仍待完成；此次测试证明本地预算分类与账本不变量，不证明供应商费用或模型诊断能力。

## 下一步

完成全量后端离线回归，复核差异后在 `main` 本地分批提交；不推送。之后再回到已授权真实G11产物做报告与工具轨迹审核；如需新付费调用，必须重新取得明确授权。
