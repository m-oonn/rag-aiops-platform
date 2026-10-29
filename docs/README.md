# 项目文档导航

按用途浏览；当前路线与运行说明保留顶层，论文草稿归入 thesis/、相关工作归入 research/、历史验收归入 history/；引用随目录同步更新。日期记录描述当时的版本和验证，不代表当前版本已通过同样验收。

## 当前配置

- [普通问答与Agent统一GLM](glm-default-switch-20261027.md)：最新模型选择、旧配置兼容与未验证项。

- [当前配置盘点与使用边界](configuration-current-20261027.md)：常规/实验配置、服务、Probe、Docker、知识与未验证项。
- [132个配置字段及直接环境消费者](configuration-fields-20261027.md)：本轮脱敏值、来源、默认值与源码位置。

## 当前路线与机制实现

- [本科毕设实施与学习路线](undergraduate-aiops-roadmap-20261020.md)：目标、阶段、验收与下一步。
- [第 1 天：真实诊断调用链](undergraduate-day01-diagnosis-call-chain-20261020.md)。
- [自主调查机制](aiops-investigation-mechanisms-20261022.md)。
- [候选身份延续](aiops-candidate-identity-20261022.md)。
- [免费运维知识与调查页面验收](ops-knowledge-free-verification-20261023.md)：真实 PDF、本地检索、原文追溯与隔离浏览器范围。
- [决策改进记录](aiops-decision-improvements-20261018.md)。
- [开源思路整合记录](aiops-open-source-fusion-implementation-20261018.md)。

## 架构、接口与运行说明

- [贡献指南](CONTRIBUTING.md)、[静态展示站](site/index.html)。

- [架构](architecture.md)、[API](api.md)。
- [调查事件](aiops-events.md)、[运行记录存储](aiops-run-store.md)。
- [Windows Probe](windows-probe.md)、[配置样例](windows-probe-config.example.toml)、[故障验收说明](windows-probe-fault-acceptance.md)。
- [TermCP 接入](termcp-aiops.md)。

## 历史验证与实验依据

- [同一现场四组编排](four-group-orchestration-20261025.md)：独立状态、固定条件、单场预算、历史隔离及失败恢复的免费离线验证。

- [记录消费与四组比较门槛](evaluation-record-consumption-20261025.md)：控制器放行、新自主只读汇总及历史不回填边界。

- [自主实验入口记录完整性](evaluation-record-integrity-20261025.md)：源码与配置、时间、失败、请求及费用口径的免费实现与离线验证。

- [机制第二阶段真实模型冒烟](history/aiops-stage2-real-model-smoke-20261018.md)、[修复复验](history/aiops-stage2-fix-retest-20261018.md)。
- Windows：[本机故障](history/windows-local-fault-verification-20261017.md)、[本机验证](history/windows-local-verification-20261018.md)、[Probe 服务](history/windows-probe-local-service-verification-20261017.md)、[模型验证](history/windows-probe-model-verification-20261017.md)、[页面验证](history/windows-probe-ui-verification-20261017.md)。
- 知识库：[10 月 15 日检查](history/knowledge-base-verification-20261015.md)、[10 月 15 日真实验证](history/knowledge-base-real-verification-20261015.md)、[10 月 16 日真实验证](history/knowledge-base-real-verification-20261016.md)。
- [TermCP 现场验证](history/termcp-aiops-live-verification-20261016.md)、[Windows 验证方案](windows-aiops-proof-plan-20261018.md)。
- [AIOps 能力补全记录](history/AIOps诊断能力补全记录.md)、[修复总结](history/修复工作总结报告.md)、[完成度历史存档](history/项目完成度存档.md)、[GitHub 同步历史核查](history/GitHub同步核查报告.md)。
- `fixtures/` 保存验证用资料，不作为可清理缓存。原始运行证据、失败记录与费用账本继续保存在项目的 `runtime/` 和 `data/`，不在本轮移动。

## 相关工作

- [GitHub AIOps 项目调研](research/github-aiops-reference-review-20261018.md)。
- [Pi-agent 架构与 GitHub 调研](research/pi-agent-architecture-and-github-review-20261020.md)。

## 论文与历史草稿

- 当前入口：[方法与实验草稿](thesis/当前方法与实验草稿-20261025.md)、[源码与草稿核对记录](thesis-method-experiment-audit-20261025.md)、[材料来源与结论边界](thesis-material-lineage-20261025.md)。当前稿区分工程核验与待执行自主实验，不代表论文已完成。

以下材料需要结合当前路线、源码与真实实验重新核实，不据此认定论文已完成或效果成立。保留旧版本供比较，不自动覆盖正文。

- [章节提纲](thesis/论文章节提纲.md)、[研究方案大纲](thesis/研究方案大纲.md)、[绪论写作指引](thesis/绪论写作指引.md)。
- 引言草稿：[原稿](thesis/引言.md)、[第二版](thesis/引言-第二版.md)、[第三版](thesis/引言-第三版.md)。
- [第二至四章草稿](thesis/论文正文-第二至四章.md)、[历史评审](thesis/毕设评审报告.md)。

## 本机材料与清理边界

- 可再生缓存可删除；源码、测试、测试夹具、依赖锁文件、现用配置、数据库和实验原始记录需要保留。
- `logs/` 接收服务和运行脚本日志；`logs/legacy/` 保存从根目录归类的旧日志。后续运行可能重新生成缓存。
- 2026-10-23 的个人材料与一次性产物已分类保存在项目外的 `D:/ragPdfSystem++agent-archive/2026-10-23/`；各次迁移清单保存在对应归档目录中。此路径是本机位置，不是其他开发者的运行依赖。
- `local/` 保存被历史评审引用的本机 Code Wiki 与选题材料；此目录不进入 Git 提交，不能视为新验证结果。
