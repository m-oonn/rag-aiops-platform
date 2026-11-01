# DeepSeek 正式调查入口免费核对（2026-10-30）

**独立配置、正式结构化请求及预算约束已完成离线核验；本轮新增真实模型请求为 0。正式调查仍受历史未知用量阻塞，不能直接续跑。**

## 本次改动与调用链

`scripts/with_agent_test_env.py` 新增 `--profile`，默认仍读取 `.env.agent-test`。本机新增 Git 忽略的 `.env.deepseek-agent-test`，从已有 DeepSeek 凭据构造，只供显式选择的子进程使用。主、简单、证据模型均为 `deepseek-v4-flash`，端点为 DeepSeek 官方接口，开启 `AGENT_DISABLE_THINKING=true`。专用凭据及 profile 内容不进入报告或源码快照，日常 GLM 配置文件未修改。

实际调用路径为：专用 profile → 新子进程首次导入 Settings → 本机控制器 → `evaluate_windows_probe.run_model` → `create_agent_llm` → `ainvoke_structured` → SDK → 预算 transport → HTTP。没有修改 LangGraph、候选生成、机制调度或结论门槛。

可以免费复核配置：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py --profile .env.deepseek-agent-test --check
```

此命令只输出脱敏配置，不能据此宣称模型已经完成诊断。

## 发现并修复的预算问题

原预算器按模型名称认可旧 DeepSeek 费率，即使传入 `--allow-unpriced-model`，仍可能标为已核实计价，并跳过请求数上限。先新增四项反例复现失败，再修复：

1. 显式未定价模式对 DeepSeek 同样生效，新请求 `pricing_verified=false`，费用保持未知。
2. 指定请求数上限时，已知和未知模型都必须遵守；拒绝项 `sent=false`，不并入已发送请求。
3. 保留既有未知 usage 拦截及旧账本只读兼容，不重算或覆盖历史。

本轮没有取得可核实的新费率，不把历史费率或模型别名当作当前账单依据。旧费率模式为兼容保留，拟议 DeepSeek 复验必须显式使用未定价模式；`5 CNY` 预留参数不能封顶未知实际金额。

## 结构化与失败验证

新增三项通过正式 `run_model`、真实工厂、SDK 和解析器的 MockTransport 回归：完整 Plan、含嵌套候选/条件/检查的 InvestigationDecision，以及非法决策。核对实际发出的完整 schema、强制 tool_choice、模型、thinking 参数、4096 输出上限、非流式及 SDK 重试 0。非法决策仍经既有 JSON fallback 校验，两条 HTTP 尝试分别记录，最终未完成；没有放宽模型字段校验。

这里替代的是 HTTP 返回和 Agent 服务外层；没有真实模型、真实 Probe 或因果正确性验证。完整调查仍可能暴露供应商兼容、模型规划或工具使用问题。正式入口当前 HTTP 操作超时为 **60 秒**，之前单次连通诊断的 **120 秒**不自动应用于调查；本轮未调整。

## 历史账本与待解决条件

最新 GLM 账本仍是 `windows-local-faults-8cb1f5c48486489faa80ffbf0dfdf698/model-d775dd96ddc141f5b65f2e850ba2e755/cost.json`，共26条，其中新增三条无HTTP响应、usage和费用。正式读取续接和控制器模型子场入口均应在启动子进程前拒绝该账本，免费准备包对这两个入口实际执行断言。

不回退23条、不用模拟账本、不通过清空账本消除阻塞。两次已知的 DeepSeek 单次成功记录独立保留，分别6498和6530 Token，费用未知；它们不是完整账户账单，也未伪装成正式调查账本。

下一场拟保持 `downstream_unreachable / G11`、同一调查实现、本地BM25夹具库14、4096输出上限、零SDK重试及失败恢复流程。最多新增24次只是待审范围，尚未获本轮付费授权。准备包的累计cap50仅是26+24的CLI解析检查，实际旧账本仍拒绝；没有产出可直接执行的付费方案。正式运行前必须先明确未知用量如何核对/保留，以及是否明确授权独立的DeepSeek预算范围。独立预算也不能被描述为清除了旧消费。

## 产物与验证结果

免费准备入口：`runtime/deepseek-formal-preparation-20261030-a/prepare.py`，仅支持准备及 `--verify`，没有模型执行分支。`plan.json` 状态为 `free_checks_passed_paid_run_blocked`，绑定选定源码、runbook夹具、旧账本与两次DeepSeek结果的hash；不保存私有配置内容/hash。

新增反例先4项失败，修复后4项通过。第一次六文件回归有324通过、3失败，原因是新增测试夹具漏传 `symptom_file`，补齐夹具后3项通过，没有降低生产要求。最终默认后端全量 **1343 passed、99 deselected、1 warning**，JUnit 为 `runtime/deepseek-prepare-backend-final-20261030.xml`；前述定向数包含于全量，不累加。全量包含专用临时业务故障/恢复单测，不是Agent自主实验或新的效果样本。

保留既有PyMilvus弃用警告，未复验前端/浏览器或重启常驻服务，未调用真实模型、在线embedding/重排。阶段E四组自主实验和已有报告人工语义审核仍未完成。本轮实现的是DeepSeek入口可离线核验及必要预算约束，不代表用户已独立掌握全部调用代码。
