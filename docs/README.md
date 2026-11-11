# 项目文档导航

- [真实前端诊断链路进度](aiops-product-goal-progress-20261106.md)：endpoint、stopped 已有通过场次；normal 未通过，目标暂停，保留各轮失败与费用未知项。

- [诊断测试环境与启用方法](aiops-test-environment.md)：持续三服务场景、真实请求日志、正式页面与独立数据库；默认免费，真实模型单独显式开启。

- [错误下游地址诊断交接修复](wrong-endpoint-handoff-closeout-20261105.md)：修复证据读取误拒、采证前业务请求缺失及自动保存检查重复；388项定向回归通过。未新增真实模型调用，根因判定与修复建议规则仍保持原限制。

- [错误下游地址单次真实诊断](wrong-endpoint-live-result-20261105.md)：模型主动查出11751与正常11750的错配；证据读取工具被调查守卫误拒、业务日志生成晚于旧证据、重复检查与报告收束问题已登记。18请求估算1.022968元，机械及刷新通过，语义待审，不补跑。

- [错误下游地址环境与免费验收](wrong-endpoint-environment-acceptance-20261105.md)：真实启动加载配置、请求转发与正式工具取证；只改文件仍失败、重启应用后恢复。19条观测、176项回归通过，0模型调用。

- [运维 Agent 测试反馈循环](aiops-investigation-test-loop-20261104.md)：按场景、证据、模型决策、执行、证据消费、报告和人审找最早断点，只做最小修复与离线回归；真实调用单独授权。

- [一次获批续测：自主补查与执行交接缺口](question-check-live-continuation-result-20261104.md)：模型读停止日志后主动查应用报错与监听，末轮想查入口日志却漏交执行字段；流程和机械通过，调查仍有缺口、人审pending。8请求估算0.264546元，最新718条/累计预留23.058792元；710未知及全额预留保持，单次例外已使用，不自动补跑。

- [问题与检查交接后真实验证](question-check-live-result-20261104.md)：模型主动取得停止日志，随后请求710等响应头超时、未知用量守卫阻断兜底与后续决策；本场未完成，新交接输入未实际发送，问题与失败保留。最新710条/累计预留22.794246元，新增1条未知用量，不自动补跑。

- [未决问题与检查结果交接](question-check-closeout-20261104.md)：请求前集中呈现问题、查询结果与限制、可用来源和守卫拒绝原因；544项相关回归，零真实调用，模型自主效果仍未验证。

- [候选交接修复后单场真实验证](candidate-handoff-live-result-20261104.md)：正常收尾、无依据重复日志被拦住；模型仍提重复检查，自主原因收束未证明。12次请求估算0.423652元，人审待完成，原失败保留。

- [候选判断与节点交接修复](candidate-handoff-closeout-20261104.md)：下轮决策明确看到条件裁决和未知限制，无新依据不重读相同日志；保存输入两处对照、526项相关回归，零真实模型，预算终止审计缺陷仍保留。

- [两原因环境真实验证：首场中断](causal-pair-live-result-20261104.md)：原因日志进入模型输入，但候选和复核未收束，单场预算终止且终止行审计失败；14次新增估算0.537610元，第二场未执行，失败保留。

- [能区分原因的测试环境免费收尾](causal-environment-closeout-20261104.md)：修复中间排查误当停止、日志别名契约及8份原文后路径丢失；两种同503、同进程/监听表象的真实原因日志经正式Probe链路可达，686项回归通过，0新增模型。

- [原因证据可达性与自主调查复验](causal-evidence-followup-20261104.md)：免费确认停止日志可被 Probe 取得并进入决策；真实单场读到线索但审计重建失败，保留失败及费用，不补跑。

- [核心事实排序单次真实复测](report-core-order-live-result-20261104.md)：请求670新契约通过，5核心及5固定说明、9引用、关闭重开一致；排序与规则相同，新增估算0.001996元，无额外收益证据。
- [报告核心排序与固定内容保留](report-core-order-closeout-20261104.md)：模型只排核心事实，程序保留日志和采集说明；请求669同输入离线对照、记录哈希与保存后读取回归，零真实模型调用。
- [运维Agent报告改造调研](ops-agent-report-redesign-research-20261104.md)：结合Datadog、Microsoft、HolmesGPT、Dynatrace官方资料，明确完整报告与模型投影分工；本轮仅方案，无新模型或生产修改。
- [单次真实报告编排验收](report-model-acceptance-20261104.md)：真实模型漏5项日志/采集说明，被完整性守卫拒绝；规则回退和关闭重开读取通过，新增估算0.017418元，不追加重跑。
- [证据约束报告模块实施](evidence-grounded-report-closeout-20261104.md)：内部模块、受限编排与规则回退、预算和刷新一致性；离线对照已交付，真实模型效果未验收，已有停止审计失败单列。
- [证据约束的报告模块方案](evidence-grounded-report-design-20261104.md)：官方技术调研及设计时点记录；实施结果见上一项。

- [四点修复后真实模型结果](four-fixes-live-result-20261104.md)：单场定位、日志、审计与刷新通过；结果投影和报告主处理对象仍有不足，新增估算0.394398元。

- [本次四点修复收尾](four-issue-closeout-20261104.md)：修编排窗口、历史审计、候选结果反馈和报告收束；离线回归与原场同输入对照，原失败保留。

- [候选契约单场真实验证](candidate-contract-live-validation-20261104.md)：候选自然出现但条件与身份仍有缺口；单场预算停止、最终状态丢失、无补跑。

- [候选契约与执行链收尾](candidate-contract-closeout-20261104.md)：修复候选检查丢失，补解析前后留痕、结果消费和刷新回归；真实自然候选与机制收益仍待验证。

- [候选全空的逻辑原因](candidate-representation-cause-analysis-20261104.md)：从实际输入、守卫前提议和条件身份追查表达断层，区分场景、契约与调度影响。
- [竞争解释场景设计与门槛](competing-hypothesis-scenario-design-20261104.md)：免费定义同一503下的两种故障层，并将自然候选生成作为付费比较前置门槛。

- [两故障四组收尾与原因分析](fault-pair-preexperiment-closeout-20261103.md)：场景辨别力、候选生成、条件表达和共用调度的限制；执行收尾完成，人审待完成。

- [两故障四组真实预实验结果](fault-pair-preexperiment-result-20261103.md)：八场完成、两机制零改向、费用与后续判断；新八场语义待审。

按用途浏览；当前路线与运行说明保留顶层，论文草稿归入 thesis/、相关工作归入 research/、历史验收归入 history/；引用随目录同步更新。日期记录描述当时的版本和验证，不代表当前版本已通过同样验收。

## 当前配置

- [阿里云 DeepSeek 主通道与官方兜底](aliyun-deepseek-switch-20261103.md)：当前模型选择、GLM 移除范围与瞬态失败兜底规则。

- [当前配置盘点与使用边界](configuration-current-20261027.md)：常规/实验配置、服务、Probe、Docker、知识与未验证项。
- [132个配置字段及直接环境消费者](configuration-fields-20261027.md)：本轮脱敏值、来源、默认值与源码位置。

## 当前路线与机制实现

- [本科毕设实施与学习路线](undergraduate-aiops-roadmap-20261020.md)：目标、阶段、验收与下一步。
- [两故障四组预实验免费阶段](fault-pair-preexperiment-20261103.md)：预设答案核对、机制机会证据、免费预检与真实批次门槛。
- [一次诊断的合理结束与人工处理验收](diagnosis-actionable-closeout-20261103.md)：报告修整和配置错误场人工处理复测。
- [第 1 天：真实诊断调用链](undergraduate-day01-diagnosis-call-chain-20261020.md)。
- [自主调查机制](aiops-investigation-mechanisms-20261022.md)。
- [候选身份延续](aiops-candidate-identity-20261022.md)。
- [免费运维知识与调查页面验收](ops-knowledge-free-verification-20261023.md)：真实 PDF、本地检索、原文追溯与隔离浏览器范围。
- [决策改进记录](aiops-decision-improvements-20261018.md)。
- [开源思路整合记录](aiops-open-source-fusion-implementation-20261018.md)。

## 架构、接口与运行说明

- [贡献指南](CONTRIBUTING.md)、[静态展示站](site/index.html)。

- [API](api.md)。架构与调用链说明以源码为准（`src/main.py`、`src/agent/aiops/graph.py`、`src/agent/aiops/strategies/investigation.py`）。
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

## 论文材料与审核记录

论文口径以导师版开题报告为准（题目《基于 LangGraph 的 AIOps 根因诊断 Agent 设计与实现》，五章结构与 36 条文献）。旧口径（旁开式动态分类／1B-2A-3C 三策略、含对数几率信念、孵化复活、两级裁判、双轨报告、本地降级证据源的一组草稿）已于 2026-11-11 从本仓库移除，不再作为写作依据，也不代表当前实现。

- [工程验证与演示材料](thesis/工程验证与演示材料-20261026.md)：免费演示的选定源码、产物与可复现实例清单。
- [材料来源与结论边界](thesis-material-lineage-20261025.md)：审核包与历史观测的来源对应，不得相加为独立实验。
- 人工语义审核底稿：[历史报告逐条审核](thesis/历史报告逐条审核-20261027.md)、[G11 完整场语义审读](thesis/G11完整场语义审读-20261029.md)、[本次真实 G11 调查语义审核](thesis/本次真实G11调查语义审核-20261029.md)。三份均为待审底稿，人工三维维度仍 pending，不代表诊断正确率。

### 论文正文（按导师版五章推进）

| 章 | 文件 | 状态 |
| --- | --- | --- |
| 二、相关技术介绍 | [论文-第2章-相关技术介绍.md](thesis/论文-第2章-相关技术介绍.md) | 初稿，四节齐全，含 36 条参考文献表 |
| 三、系统需求及总体设计 | [论文-第3章-系统需求及总体设计.md](thesis/论文-第3章-系统需求及总体设计.md) | 初稿，FR-01~27、NFR-01~07、五层架构与模块划分 |
| 一、绪论 | 未开始 | 待写 |
| 四、系统实现 | 未开始 | 待写（依赖现有源码，不依赖新实验） |
| 五、系统测试与结果分析 | 未开始 | 待写（依赖人工语义审核与补场次） |

- [参考文献对照-导师版36条.md](thesis/参考文献对照-导师版36条.md)：36 条逐条记录引用位置与核对状态（书目已核 36 / 全文未读 36）。

## 本机材料与清理边界

- 可再生缓存可删除；源码、测试、测试夹具、依赖锁文件、现用配置、数据库和实验原始记录需要保留。
- `logs/` 接收服务和运行脚本日志；`logs/legacy/` 保存从根目录归类的旧日志。后续运行可能重新生成缓存。
- 2026-10-23 的个人材料与一次性产物已分类保存在项目外的 `D:/ragPdfSystem++agent-archive/2026-10-23/`；各次迁移清单保存在对应归档目录中。此路径是本机位置，不是其他开发者的运行依赖。
- `local/` 保存被历史评审引用的本机 Code Wiki（`CODE_WIKI.md`）；此目录不进入 Git 提交，不能视为新验证结果。此处的选题材料 `毕设选题说明.md`（旧旁开式动态分类口径）已于 2026-11-11 随旧论文口径清理本机删除，论文口径改以导师版开题报告为准。
