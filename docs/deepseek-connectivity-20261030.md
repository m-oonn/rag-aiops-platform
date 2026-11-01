# DeepSeek 单次连通复验（2026-10-30）

用户要求“用dp”，本轮沿用历史 DeepSeek 官方配置，执行一条独立连通和最小结构化输出请求。没有续接 GLM 的失败调查账本。

## 实际结果

- 北京时间 2026-10-30 10:31:09—10:31:11；一次发送，无重试或重定向，HTTP 200，耗时 1387.47 ms。
- 请求模型 `deepseek-v4-flash`，响应自报 `deepseek-flash`；别名对应关系未独立核实。
- `finish_reason=tool_calls`，返回一个 `InvestigationDecision` 工具调用，参数 JSON 可解析，`hypothesis` 为字符串。仅检查历史最小 schema，未校验完整诊断 schema。
- 输入 6402、输出 128、合计 6530 Token；供应商报告输入缓存 6268 Token。实际费用未知，未套用其他模型费率。
- 没有执行返回的工具，没有启动服务、故障或完整 Agent 调查，不能算自主诊断效果。

## 复用与留痕

沿用 `runtime/deepseek-single-comparison-20261028-a/run.py` 的一次请求实现及历史最小请求。正文传输 SHA256 与该历史成功请求相同；输出上限 256 Token，HTTP 操作超时 120 秒，关闭 thinking。运行前四类离线自检通过：成功、超时、HTTP 401、无效 JSON；重复执行已消耗的目录会被独占文件拒绝。

本轮产物位于 `runtime/deepseek-connectivity-20261030-a/`：

- `plan.json`：范围、请求条件及来源 hash。
- `request.json`：不含鉴权头的请求正文。
- `attempt.json`：响应状态、时间、usage 和最小参数校验；不保存响应正文或凭据。
- `outcome.json`：实际请求结果及历史文件 hash 核对。
- `delivery-audit.json`：交付前来源完整性与凭据泄漏检查。

凭据从 Git 忽略的 `.env.deepseek-test` 读取。未修改日常 `.env` 或 GLM 专用 `.env.agent-test`。旧 GLM 26 条请求链及旧 DeepSeek 结果保持原样；新增一次 DeepSeek 请求独立记账，费用仍未知。

## 当前结论与下一入口

本机本次可以通过 DeepSeek 官方通道取得响应及最小结构化输出；这不能定位 RightAPI/GLM 的失败原因，也不能保证完整调查兼容。

下一步先免费核对 DeepSeek 在现有正式实验入口中的模型选择、thinking 参数、端点许可、结构化解析和预算隔离；准备完整 schema/单场复验条件。本轮一次请求额度已用完，不自动追加付费调查，不回退或重置 GLM 旧账本。四组自主实验及已有报告人工审核仍未完成。
