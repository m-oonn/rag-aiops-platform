# DeepSeek 计价预算修复（2026-11-02）

## 结论

真实复验 `runtime/windows-local-faults-26e881131bde4abc931bd11f9af927ce/model-2c8d03afbdf24f5aa6d4735bfdcf1d9a/` 中新增 9 条请求均有完整 usage，但因 `allow_unpriced_model=true`，已知型号 `deepseek-v4-flash` 被错误标成 `pricing_verified=false`，`reserved_cny=0`。事后按官方高峰费率估算为 0.372978 CNY；这是独立估算，不是供应商实扣，也不表示原运行时预算器成功执行了费用上限。

## 修复

`PaidRequestBudget.reserve()` 现在始终对已知 DeepSeek 型号应用已配置的费率。`allow_unpriced_models` 只允许明确放行未知型号，不会把已知型号降为未核价。历史账本不回填、不重写；新规则仅影响后续新请求的预留与结算。

## 验证

- `tests/test_evaluation_record.py` 与 `tests/test_four_group_controller.py`：100 passed。
- `tests/test_identity_followup.py` 与 `tests/test_investigation_strategy.py`：155 passed。
- 仅有既存 PyMilvus `connections.connect` 弃用警告。
- 本次未发起新模型请求。当前单场授权最多 12 次，已用 9 次；剩余 3 次不足以完成有效现场调查，故保留额度。

身份拒绝后的本场行为也已核对：依赖探测、日志读取、5047/5048 端口检查和 downstream 进程检查均已执行；剩余 Windows 事件日志检查因现场未配置而不可用。恢复策略拒绝重复已执行检查及不可用检查，轨迹没有显示存在可继续的保存候选。因此本场没有复现保存检查恢复，不构成已确认的代码故障；此前单场的直接成功记录仍单独保留。

原运行结果见 `docs/identity-log-expansion-retest-result-20261102-b.md`，其账本、报告和审计产物均未修改。
