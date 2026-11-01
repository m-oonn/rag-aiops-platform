# E2 两故障四组预实验准备（2026-11-01）

## 范围与前置检查

本批针对 E2 的候选机会预实验，只覆盖 `downstream_unreachable` 与 `application_config_error`，各运行 G00/G10/G01/G11 一次，共 8 场。新增版本化套件 `e2-fault-pair-v1`，避免沿用包含正常场景的 12 场 `mechanism-v1`。症状统一使用 `candidate-opportunity`，四组仅切换假设保护与矛盾触发机制；候选、工具权限、知识、证据规则和结论门槛保持不变。

免费现场预检由项目 `.venv` 执行，结果保存在 `runtime/windows-local-faults-f1af7b7deeb24dc7b5be15c65603da71/four-group-scenario-preflight.json`。两故障顺序随机化，8 轮、32 条真实 Probe 窗口观测，状态 `passed`，`model_calls=0`。恢复状态为入口与下游 HTTP 200，临时所属进程停止、端口 6086-6089 已释放，清理错误为空。该检查验证场景切换和 Probe 窗口，不代表 Agent 调查或机制效果。

定向回归：`tests/test_four_group_controller.py` 与 `tests/test_evaluation_record_consumption.py`，113 passed；仅有既有 PyMilvus 弃用警告。

## 本批上限

- 账本从 `runtime/windows-local-faults-618a85d94d9f4959ba6bdea202c10eed/model-4687b6680f074924883103fc458f37bb/cost.json` 续接：202 条，峰值预留 5.250858 CNY，原累计上限 9.922880 CNY；SHA-256 `6dbbe76fe036adc15a897ec47bc8abd11b065469cc7f2ed17d4ed868dfaf822a`。
- 本次新授权最多 5 CNY。按已核定 DeepSeek Flash 峰值输入 2 / 输出 8 CNY 每百万 Token，八场每场设置 0.60 CNY 上限，整批预留上限 4.80 CNY，余下 0.20 CNY 不进入执行预算。
- DeepSeek 官方定价页在本批日期重新核对；程序 profile 自检只确认模型角色和凭据配置，返回 `pricing_verified=false`、`connectivity_verified=false`，不将其冒充定价或联网验证。预算器记费率核验日期为 2026-11-01，保留峰值费率作上限，不计入时段折扣。
- 每场最多 12 次请求，因此最多新增 96 次；账本累计请求硬上限 298。每请求最多 4096 输出 Token，模型/SDK 自动重试关闭。
- 累计费用账本上限设为原上限加本次授权，即 14.922880 CNY。旧账本的 52 条未知费用保持未知；不回退请求数、不清零余额、不将估算写成供应商实扣。
- GLM 价格未核实，本批用隔离 `.env.deepseek-agent-test` profile 指向已核价 DeepSeek；日常 GLM 配置不变。
- 任一场失败、缺 usage、非 200、账本链断裂、审计不通过、预算达到门槛或现场恢复失败，立即停止后续场次并保存失败状态；不补跑。

这份准备记录只说明经批准批次的范围与免费前置结果。真实结果、汇总、人工待审状态及最终账本另记，不以场景预检代替自主效果或语义正确性。
