# 定向 G11 真实复验结果（2026-11-01）

## 执行边界

用户授权新一轮最多增加 5 CNY，沿用 DeepSeek `deepseek-v4-flash`，账本不重置。继承账本为 `runtime/windows-local-faults-7da9d77cfadf4f319199ba3fb29494c0/model-c5c42947590d4308b3a5b49a87a75929/cost.json`，执行前 194 条、峰值预留 4.922880 CNY、原累计上限 8 CNY；历史 52 条价格未知。

第一次控制器尝试误用系统 Miniconda Python，在模型模块导入前因缺少 `langgraph.checkpoint.sqlite` 退出，未产生请求或费用。随后确认项目 `.venv` 可导入该模块，并使用正确解释器完成本次唯一模型场景。失败尝试目录 `runtime/windows-local-faults-65426aebc3a341798dbb65e300723a42` 保留；其控制器恢复正常，所属进程停止、端口释放、清理错误为 0。

真实执行为单场 `downstream_unreachable/G11`，症状模板 `candidate-opportunity`，关闭 SDK/Agent 自动重试，每请求最多 4096 输出 Token。有效预留上限设为继承金额加本轮 5 CNY，即累计 9.922880 CNY；累计请求上限 206 条，因此最多新增 12 次。没有执行四组实验。注意：控制器 smoke 分支没有把 `--run-budget-cny` 传入子进程，执行材料中的 `run_budget_cny` 为 null；本场的 5 CNY 上限由累计预留上限（9.922880 - 4.922880）实施，而不是由单场预算字段实施。

## 结果

- 有效调查新增 8 次 DeepSeek 请求，均 HTTP 200 且 usage 完整；累计 202/206 条。
- 本轮输入 113,213、输出 12,694、合计 125,907 tokens；峰值预留 0.327978 CNY。累计峰值预留 5.250858/9.922880 CNY，供应商账单未核。旧 52 条仍为费用未知，不把峰值预留称为实际账单。
- 调查正常完成，最终报告 `localized_fault`。现场核实到入口 503 并记录 `upstream connection failed`；downstream TCP 连接被拒、4886 无监听、配置进程快照匹配数为 0。downstream 日志为空。报告没有确定“未启动、启动失败退出或端口冲突后退出”中的具体原因，仍属有限故障层定位，不等于根因确认。
- 记录完整性、报告机械检查、G11 配置和机制行为审计均通过。用户随后完成三维人工审核：诊断 `correct_localization`、引用支持 `supported`、建议适用性 `appropriate`；用户仅选择 verdict，未提交额外理由或自选证据 ID。登记时明确区分原始选择与记录者索引的相关证据。机制审计记录保护机会 0、矛盾机会 0、两种实际改向 0；第三步存在候选身份拒绝后延续已保存检查，不计机制收益。因此本场不能证明两项机制有效或无效。
- 本场控制器 `ok=true`、38 条控制器证据、最终状态 `normal_restored`；临时进程已停止、端口已释放、清理错误 0。知识条件前后 hash 相同，但未验证远程向量索引。

有效运行目录：`runtime/windows-local-faults-618a85d94d9f4959ba6bdea202c10eed`。模型材料位于 `model-4687b6680f074924883103fc458f37bb`；账本 SHA-256 为 `6dbbe76fe036adc15a897ec47bc8abd11b065469cc7f2ed17d4ed868dfaf822a`。前缀 194 条原样继承。

人工审核包：`runtime/g11-semantic-review-20261101-a/`。`diagnostic_review.py check` 返回 `recorded`，三项 verdict 如上；审核包 SHA-256 为 `8a8ca4fb0f46eba96cc9a3f83d64dfaa7f864b62a1b68b880a71ed00ffa7c26e`，`manual-review.json` SHA-256 为 `64474cd11c9d79e14f106007a65243e2c9f0cd3b00ba06ab4fbd61335f676022`，二者均与独立[审核回执](../runtime/g11-semantic-review-20261101-a/human-decision.json)相符，校验器同时确认所有绑定来源 hash 未变化。回执只表示用户意见已记录，不是自动正确性证明；未回写模型报告或账本。

## 下一步

E1 的工程闭环及本场三维人工审核已记录完成。用户提交 verdict 但未提供理由，故保留该限制；审核结论仍是人工判断，不代表因果正确性由工具证实。E2 四组自主预实验尚未授权；不得因本场预算余量自动启动。首次零调用失败属于启动器选错 Python，后续控制器命令应显式用项目 `.venv/Scripts/python.exe`。
