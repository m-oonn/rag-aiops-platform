# 身份拒绝后日志扩读真实复验（2026-11-02）

## 结论

修复后的真实链路观察到身份拒绝后保存检查继续执行，并实际读取映射下游日志 `lines=100`。本轮没有先读同一路径 20 行再读 100 行；“20 行观测后允许 100 行扩读、相同 100 行仍去重”由定向回归直接验证。真实场景只确认身份拒绝后的补查执行到了 100 行日志查询；本场在最终诊断前被 0.60 CNY 单场预留上限拦截，workflow 未完成，不能算完整诊断通过，也不用于 E2 四组比较。

## 范围与调用

- 单场 `downstream_unreachable/G01`，`candidate-opportunity`，DeepSeek `deepseek-v4-flash`；GLM 未调用。
- 继承失败 E2 账本 210 条。单场最多 12 次请求、0.60 CNY 峰值预留、每次最多 4096 输出 Token；自动重试关闭。此次新增 9 次，累计 219 次。
- 新增 9 次全部 HTTP 200 且 usage 完整，峰值费率预留 0.399804 CNY；累计峰值预留 5.931518 CNY。供应商实扣未核实，旧 52 条费用仍未知。
- 旧 210 条请求逐条前缀完全一致。继承账本 SHA-256 `7f3752a2e6682193a5a3884866bd86816190ef602240d839abde157ec5a85c71`；新账本 SHA-256 `290fe50c8f5f5687db7e1fba03a2121104e447132c6822926900fa2b25d6b1ae`。

## 行为证据与失败边界

- `mechanism_trace.json` 的第 2 步记为 `identity_rejected=true`、`independent_followup=true`、`saved_check_continued=true`；其行为审计状态为 `passed`。
- `tool_trace.json` 记录了对白名单映射文件 `downstream.log` 的 `lines=100` 查询，Probe 返回空日志；随后还读取 `app.log` 的 100 行。
- 先前失败场在两个日志路径上只记录了 `lines=20`。代码回归测试已验证同路径 20 行观测不会阻断 100 行补查，而相同 100 行查询仍被去重；本轮现场没有复现这组前后查询序列。
- 模型完成 7 个执行步骤后，下一次模型发送因 `per_run_cost_limit` 被预算器拒绝。子场 `workflow_completed=false`、报告为 `unlocated`，停止原因为预算门槛；机制配置审计因诊断未完成而失败，不能把子场或整场标成通过。
- 没有自动重试。控制器恢复到 `normal_restored`，本轮所属临时进程已停止，端口 9065-9068 已释放，清理错误为 0。原 E2 failed 记录、原报告及账本未回写。

## 产物

- 控制器运行目录：`runtime/windows-local-faults-95d8f7e24881443990f456490132f4a4/`
- 子场：`runtime/windows-local-faults-95d8f7e24881443990f456490132f4a4/model-51c7f1a25be242e39e82bdad37c48aa2/`
- 本次单场限制与用户授权依据：`runtime/e2-identity-log-expansion-retest-20261102-a/human-smoke-review.json`
- 免费回归：`tests/test_identity_followup.py` 54 passed；`tests/test_investigation_strategy.py` 101 passed；`git diff --check` 通过。仅既有 PyMilvus 弃用警告。

后续如需取得完整报告，须先解决单场 0.60 CNY 上限不足以预留最终模型请求的问题，并另行明确有限授权；本场失败即停，不自动追加调用。
