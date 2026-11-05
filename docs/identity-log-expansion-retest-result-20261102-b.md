# 身份拒绝后日志扩读复验（5 元额度，2026-11-02）

## 结论

用户将本轮新增预算重置为 5 CNY 后，重新运行单场 `downstream_unreachable/G01`。控制器 `ok=true`，workflow 完成，报告为 `localized_fault`，机械审计与恢复清理通过。但本场第 6 步出现 `identity_rejected=true` 时，行为审计记录 `independent_followup=false`、`saved_check_continued=false`；因此本场没有再次验证身份拒绝后的保存检查延续。它完成了诊断流程，不等于重复验证了本次修复，也不用于 E2 四组效果比较。

## 范围和用量

- 只执行一个 `downstream_unreachable/G01`、`candidate-opportunity` 场景；DeepSeek `deepseek-v4-flash`，GLM 未调用。SDK/Agent 自动重试关闭，单场最多 12 个请求、输出上限 4096 Token。
- 继承 219 条 DeepSeek 账本，旧前缀 SHA-256 `290fe50c8f5f5687db7e1fba03a2121104e447132c6822926900fa2b25d6b1ae`；新账本共 228 条，旧 219 条保留。
- 新增 9 次 HTTP 200 且 usage 完整；输入 140,903 Token（缓存命中 16,512）、输出 15,442 Token。按本次执行时间 2026-11-02 17:01–17:03 北京时间处于工作日高峰时段，并按 DeepSeek 官方 Flash 高峰费率（缓存命中 0.04、未命中 2、输出 8 CNY/百万 Token）重算，本场峰值估算 0.372978 CNY。该值低于本次 5 CNY 授权上限，但不是供应商账单。
- 执行配置把累计请求上限设为 231、累计 CNY 上限设为 19.922880（继承上限 14.922880 加本次 5）。然而 `allow_unpriced_model=true` 使新 9 条记录仍标记 `pricing_verified=false`、`reserved_cny=0`；账本累计预留仍显示 5.931518，不能把运行时账本字段说成已按新费率执行预算扣算。上述 0.372978 是对完整 usage 的独立事后峰值估算，供应商实扣未核。

## 现场与机制审计

- 控制器结果 `ok=true`，38 条控制器证据；所属临时进程已停止、端口 5046–5049 已释放、剩余监听为空、清理错误 0。
- 子场报告有限定位 `localized_fault`，机械门通过、语义人审 pending。结论由入口 HTTP 503、downstream TCP 拒绝、5048 无监听，以及按配置身份完整进程查询未发现匹配（检查 376 个进程、跳过 0）支持；downstream 日志为空，启动或退出原因仍未知。
- 矛盾机制机会 1 次并实际改向 1 次；假设保护机会 0。机制有效性未验证。
- `mechanism_trace.json` 第 6 步身份拒绝后没有保存检查继续标记。虽然轨迹中存在 downstream.log 100 行读取，但该读取不能归因为拒绝后的恢复行为。此前 0.60 CNY 单场真实复验曾记录 `saved_check_continued=true` 并实际执行 100 行映射日志查询；本轮结果与此前结果分别保留。
- 本轮第一次启动参数被环境包装器拒绝，发生在控制器启动前，model/tool 调用 0；按其接受的项目脚本格式启动后才完成上述唯一场景。

## 产物

- 授权记录：`runtime/e2-identity-log-expansion-retest-20261102-b/human-smoke-review.json`
- 控制器：`runtime/windows-local-faults-26e881131bde4abc931bd11f9af927ce/`
- 子场与账本：`runtime/windows-local-faults-26e881131bde4abc931bd11f9af927ce/model-2c8d03afbdf24f5aa6d4735bfdcf1d9a/`
- 新增账本 SHA-256：`c8a41bc97b0c200995d07d9de6aaf10af9ebcfdb48f04c61338bd80af7927ce7`；此前 219 条记录保持不变。
- 费率来源：DeepSeek 官方模型与价格文档（2026-11-02 核对）：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/

后续不重跑整批 E2。若需要专门复现身份拒绝后保存检查延续，应先从本场轨迹确认为何没有触发该分支，再决定是否值得使用剩余额度；已有上一次直接触发成功的现场证据，不把本场未触发写成代码回归。
