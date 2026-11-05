# 报告核心排序与固定内容保留

2026-11-04。本阶段仅修复报告编排遗漏：**模型只排列核心事实，日志及采集说明由程序完整输出。** 默认规则报告、完整报告包和既有布局校验保留。本轮没有真实模型请求、新现场观测或费用。

## 实现范围

- [reporting.py](../src/agent/aiops/reporting.py)：以 `objects[*].facts` 的成员关系确定核心事实，生成只含允许ID、对象标签和现有事实文字的模型投影。没有依据名称前缀或自然语言重新分类，也没有重建上游证据。
- 输出仅接受 `CoreFactOrder.core_fact_order`，禁止额外字段；核心ID必须各出现一次。程序从规则布局出发，仅替换核心事实顺序，再按原顺序追加固定说明，对象、解释及行动顺序仍用规则结果。最终仍通过完整 `ReportLayout` 校验及既有渲染。
- 缺项、重复、陌生ID、额外字段均规则回退并记录 `degraded` 及错误；不补齐答案、不发纠正请求。零条或一条核心事实直接规则出稿，不创建请求或尝试标记。既有超时、预算、取消和防重放行为保留。
- [evaluation_record.py](../scripts/evaluation_record.py)：新记录增加内部 `model_contract=core-facts-v1` 和模型投影 `model_input_sha256`。读取方核对投影哈希、实际保存的HTTP用户输入、解析输出与最终完整布局。即使跳过模型，完整包也必须保留。旧记录按原契约读取，不补字段或回写。

原 `input_sha256` 仍指完整bundle，版本仍为1；公开API、事件和摘要字段不变。完整包继续供审计、保存和刷新使用；调查策略、对象归并、根因判断、建议规则、页面均未修改。

## 同一保存输入对照

使用请求669的原bundle和解析提议，原始文件保持只读。复核脚本：[compare_saved_input.py](../runtime/report-core-order-closeout-20261104-a/compare_saved_input.py)；机器结果：[comparison.json](../runtime/report-core-order-closeout-20261104-a/comparison.json)。

| 检查 | 旧契约与原提议 | 新契约离线构造输出 |
|---|---|---|
| 核心事实 | 返回5项 | 同5个ID，顺序为0、1、4、2、3 |
| 日志与采集说明 | 缺少note-4至note-8，完整性校验拒绝 | 程序追加2条日志、3条采集说明，顺序不变 |
| 结果 | 原 `degraded/rules` 保留 | 构造输出通过核心及完整布局校验 |
| 对象、解释、行动 | 原规则结果 | 与规则结果相同 |
| 引用与未知 | 规则回退保留 | 全部9个正文证据ID及原有未知、停止理由保留 |
| 保存后读取 | 原结果不改 | JSON往返渲染、建议顺序一致 |

[修前规则报告](../runtime/report-core-order-closeout-20261104-a/before-report.txt)、[修后离线报告](../runtime/report-core-order-closeout-20261104-a/after-report.txt)、[模型投影](../runtime/report-core-order-closeout-20261104-a/model-projection.json)、[最终布局](../runtime/report-core-order-closeout-20261104-a/final-layout.json)均已保存。

**新契约输出是将原5个ID显式包装后的离线构造，不是真实模型返回。** 没有把请求669补写为成功，也没有据此判断真实模型改善或额外付费价值。

## 验证

新增分支先暴露失败：报告初始7项、记录读取初始8项；另补“跳过排序但完整包缺失”的反例，先失败再修读取方。专门的5+5回归通过已验证的构造证据生成，避免测试依赖忽略目录里的历史数据。

最终关联检查覆盖以下8个文件：`test_reporting.py`、`test_evaluation_record_consumption.py`、`test_evaluation_record.py`、`test_priced_experiment_budget.py`、`test_windows_probe_evaluation.py`、`test_aiops_structured.py`、`test_probe_persistence.py`、`test_report_text.py`。**325 passed，0 failed，1条既有PyMilvus弃用警告**，不累加开发中重复运行的数量。JUnit见 [final.xml](../runtime/report-core-order-closeout-20261104-a/final.xml)。

- 合法排序、5核心+5固定说明、全部引用、ID不依赖前缀；非法核心排序均回退，单次尝试无新增纠正。
- 零/一核心零请求；多个独立故障、缺对象映射、未知和冲突保留；知识附录与完整布局校验沿用。
- MockTransport覆盖真实SDK结构化解析路径及预算计费守卫；超时、预算拒绝、取消、防重放不变。所有响应均为替代输出，没有外部模型请求。
- 新旧记录消费、投影hash及实际输入篡改、输出/布局错配、固定说明调序、契约缺失、完整包缺失均有回归。
- 既有图流程的report事件、最终response、诊断建议、SQLite检查点及关闭重开后 `run_details` 一致，重复读取零新增请求。

| 状态 | 范围 |
|---|---|
| 通过 | 本次报告、读取、预算及持久化关联检查325项 |
| 既有失败保留 | 此前4项停止审计失败，本轮未修改调查/审计调度，也未重跑该组 |
| 未处理 | `inventory/resources`空投影，不属于本次报告输入排序 |
| 未运行 | 真实模型、现场故障、付费复测、前端构建与浏览器、全仓测试 |

201份历史来源文件哈希全部不变。真实账本仍为669条、峰值估算21.298042元、累计上限24.453038元，61条历史未知价格记录保留。账本和请求669的原失败结论均未修改。本阶段完成标准限于离线完整性与持久化一致性。
