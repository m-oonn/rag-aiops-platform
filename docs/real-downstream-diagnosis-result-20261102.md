# 真实下游故障诊断结果（2026-11-02）

## 结果

- 单场 `downstream_unreachable/G11`，模型为 DeepSeek `deepseek-v4-flash`；GLM 未调用。
- 本场新增 10 次请求，全部 HTTP 200 且 usage 完整；输入 211,946、输出 24,548 Token。
- 本场峰值费用估算 **0.540358 CNY**，供应商账单未核；累计账本 318 条，累计峰值预留 **9.96939 CNY**。旧 308 条逐项保留。
- workflow、机械审计和恢复清理通过；临时进程停止、端口释放、清理错误均为 0。

运行材料：`runtime/windows-local-faults-05470499e792485181a07e44e811555c/`

子场目录：`runtime/windows-local-faults-05470499e792485181a07e44e811555c/model-8d138cd570a0471bbeee7d6ae934b009/`

## Agent 实际查到的内容

Agent 从现场 Probe 取得并引用了：

- localapp `127.0.0.1:9632` TCP 可连，但 HTTP 返回 503；
- downstream `127.0.0.1:9633` TCP 被拒绝、无监听；
- 完整进程查询枚举 386 个进程，downstream 匹配 0、跳过 0；
- 保存的日志证据 `ev-096a14f35afa4048ad15aceb19ac15b4` 包含 `shutdown_requested / controlled_stop`。

因此 Agent 正确定位到“配置下游当前不可达”这一故障层，并明确写出更深原因尚未确认，也没有把停止触发者或控制器答案冒充成 Agent 证据。

## 控制器真值与边界

事后控制器记录表明，本场下游进程是被测试控制器主动终止的；这属于盲测控制器真值，不属于 Agent 可见证据。Agent 仍不能仅凭现场日志区分人工停止、编排停止、启动失败或自然退出。

本场假设保护和矛盾触发均为 0 次机会、0 次执行、0 次改向，不能据此宣称机制有效。服务状态检查对进程型应用不适用，报告已明确这不代表所有可能检查均已穷尽。

## 免费一致性核对

已核对控制器、账本、报告、证据文件和生命周期记录：

- 账本 318 条，新增编号 309–318，共 10 条，均有 HTTP 200 和完整 usage；
- 本场费用在 `blind-controller.json` 的 `this_run_cost` 和 `summary.json` 的 `cost_scope.this_run` 中均为 0.540358 CNY；
- `summary.json` 顶层累计费用为 `null` 是预期行为，因为历史账本仍有 61 条价格未核实记录；
- 报告引用的证据 ID 均能在子场 `evidence/` 中找到；
- `process-lifecycle.json` 记录了控制器停止、退出码和清理状态；
- 原始运行材料、历史账本和生产代码未被回填或覆盖。

语义人审仍待完成。本结果不构成四组对比，也不证明两项机制的效果。
