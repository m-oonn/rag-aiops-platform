# 核心事实排序的单次真实复测

2026-11-04。**新报告契约真实复测通过：模型返回全部5个核心ID，程序保留2条日志、3条采集说明及全部9个正文证据引用。** 本次排序与规则完全相同，尚无额外编排收益证据；默认仍使用规则报告。

## 实际范围

用户确认下一步是一次真实报告复测后回复“做”。复用请求669的同一份历史bundle，完整输入hash仍为 `8939c4b66453b0e6af6c24ad4e3e64a60128d54c102a7dd342c6dfa22221223b`。模型实际只接收5条核心事实的投影，投影hash为 `6fa7147acd86b43a6159ae25b64a8141d9a44efd051ee7e38596b3098dcc1887`。

没有注入故障、采集当前现场、运行完整调查或四组；历史证据没有被当作当前状态。只使用已有报告模块及预算器、SDK、解析校验和专用SQLite保存读取链路；本轮没有生产代码修改。

执行前扫描实际账本，最新为669条、累计峰值估算21.298042元；单场沿用0.75元、累计24.453038元，额度足够。预算与旧账本连续继承，没有清零历史未知价格用量。所有旧账本及失败记录保持原样。

## 结果

| 检查 | 真实观察 |
|---|---|
| 请求 | 北京时间15:05:29—15:05:30，请求670；阿里云 `deepseek-v4.1-flash-1017`，HTTP200、usage完整 |
| 模型返回 | `core_fact_order=[fact-0,fact-1,fact-2,fact-3,fact-4]`，没有遗漏、重复、陌生ID或额外字段 |
| 最终布局 | 核心排序后追加note-4至note-8；完整ReportLayout校验通过，`status=ready/mode=model` |
| 固定说明 | 2条日志、3条采集范围说明，原文字及原顺序全部保留 |
| 引用与判断 | 全部9个正文证据ID保留；对象、解释、行动顺序沿规则，未改根因判断或建议规则 |
| 与规则比较 | 顺序、报告正文均完全相同；本次没有新增报告内容或更好的排序 |
| 保存刷新 | report、diagnosis建议、完整布局在SQLite关闭重开及两次既有 `run_details` 读取后相同，刷新0请求 |
| 留痕 | 保存的HTTP输入hash、实际投影、解析输出与最终布局一致；继承669条账本逐行一致 |
| 历史保护 | 211份历史材料hash前后相同，原请求669仍为degraded/rules，未回填成功 |

完整 [报告](../runtime/report-core-order-acceptance-20261104-a/live/report.txt)、[结果摘要](../runtime/report-core-order-acceptance-20261104-a/live/result.json)、[内部报告记录](../runtime/report-core-order-acceptance-20261104-a/live/report-generation.json)、[刷新读取结果](../runtime/report-core-order-acceptance-20261104-a/live/refreshed-details.json)已保存。解析输出来自本次真实响应，未使用上阶段的离线构造答案。

请求输入734 Token、输出66 Token，按已有核定峰值费率估算新增 **0.001996元**，不是供应商账单。最新 [实际账本](../runtime/report-core-order-acceptance-20261104-a/live/cost.json)为 **670条、21.300038元**，距累计边界余3.153000元；61条历史未知价格记录继续保留。官方备用通道未实际调用，没有新增重试或第二次付费复测。

## 免费预检与限制

先用同一验证脚本的MockTransport检查新契约、预算、SDK解析及关闭重开。初次免费预检因脚本在预算规范化前只识别 `max_tokens`，未兼容SDK的 `max_completion_tokens` 而在发送前失败，真实请求0；修正脚本检查后免费预检通过。失败材料保存在 `offline-failed-1`，替代账本均命名 `mock-cost.json`，不混入真实账本。专用脚本见 [accept_report.py](../runtime/report-core-order-acceptance-20261104-a/accept_report.py)，独占目录和尝试标记阻止原位重复执行。

本次免费预检和真实结果的断言均通过。上阶段325项离线回归保持原成绩，本轮未重跑全仓、前端或浏览器。此前4项停止审计失败与 `inventory/resources` 空投影仍未处理，人工语义审核仍pending；不将这次报告契约通过等同于完整诊断能力、因果归因或机制效果提升。

本次已完成授权的单次验证。当前可以确认报告遗漏防护在这一次真实返回上工作正常，**没有理由仅为追求不同排序继续付费重跑**。
