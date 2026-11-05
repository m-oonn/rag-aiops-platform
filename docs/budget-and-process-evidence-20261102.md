# 预算范围与进程生命周期修复（2026-11-02）

## 结论

第二步和第三步已完成。单场请求上限与累计请求/人民币上限现在在 CLI、盲测控制器、子进程和报告中保持同一语义；预算停止报告增加 `budget_stop_scope`，可区分本场、累计、继承账本和请求校验。测试业务的每个临时进程同时保存启动命令、工作目录、输出文件、PID、启动/结束时间、退出码及是否由控制器主动停止。

## 代码变更

- `scripts/verify_windows_local_faults.py`
  - `--run-max-model-requests` 可用于单场 smoke/extended，也继续用于四组。
  - 盲测控制器完整转发 `max_model_requests` 与 `run_max_model_requests`。
  - 新增 `process-lifecycle.json`，启动失败也留痕。
  - 进程状态区分 `stopped_by_controller` 与 `exited_before_cleanup`，退出码不再单独承担原因解释。
- `scripts/evaluate_windows_probe.py`
  - 摘要新增 `budget_stop_scope`：`this_run`、`cumulative`、`inherited_ledger` 或 `request_validation`。
- 测试覆盖单场 cap 转发、预算范围字段和既有账本前缀保护。

## 验证

- 定向回归：329 passed，1 个既有 PyMilvus 弃用警告。
- 受影响控制器回归：185 passed，1 个既有 PyMilvus 弃用警告。
- 免费 E2 场景预检：`runtime/windows-local-faults-464748805ed34d9083f20aaa87f900a6/`，8 轮、32 条 Probe 证据、model_calls=0、`ok=true`、临时进程停止、端口释放、清理错误 0。
- 生命周期样例：`runtime/windows-local-faults-464748805ed34d9083f20aaa87f900a6/process-lifecycle.json`。

## 边界

本轮没有新增真实模型调用，也没有把历史账本回填或重置。真实诊断仍需人工审核；下游启动/退出原因现在具备可追溯证据，但尚未据此重新消耗模型额度。
