# 四点修复后的单场真实模型验证

2026-11-04。本次模型找对被停掉的 downstream，诊断流程、机械审核、行为重建与关闭后读取通过；候选消费和报告收束仍有具体不足。因此是工程链路通过、语义收束部分完成，不把它写成四点效果全部通过或机制有效。

用户授权“用真实模型测试”。本轮只执行一场 G11，沿用原 edge → localapp → downstream 拓扑、正常部署 runbook 与 candidate-opportunity 输入，固定原场的 downstream 停止故障层，供修复后定向验证。没有向模型提供控制器答案、指定候选或检查顺序。独立业务、数据库、checkpoint 和观测窗口，费用连续继承。单场上限0.75元，累计24.453038元，无新增请求数上限，无自动补跑。

## 实际发生了什么

控制器停止 downstream 后，edge、localapp 均返回503；downstream TCP拒绝、13980端口无监听、配置身份进程匹配0。模型取得上述现场证据，还成功读取 localapp 与 edge 的 upstream connection failed 日志。最终 localized_fault，与注入的直接故障层相符。没有证明谁停止进程、为何退出或是否崩溃。

7轮决策，13次工具尝试全部返回有效证据。顺序为 inventory、三个进程快照、三个依赖探测 → downstream监听 → downstream日志 → localapp日志 → edge日志 → 资源快照 → inventory复核。downstream空日志没有被重复读取；inventory以显式复核理由再读一次。无身份冲突、无预算停止、无调查异常。

| 本次关注点 | 真实观察 | 判断 |
|---|---|---|
| 本轮窗口与知识材料 | reset返回边界用于评测；三份日志均通过窗口校验；本地材料前后基线与完整机械审核通过 | 本场通过；旧轮次拒绝及材料篡改由此前免费回归覆盖，本次未故意注入 |
| 停止审计 | 当轮保存7—13条观测历史；末轮检查拒绝与无可执行检查的停止结果经同一守卫重建，behavior passed | 本场通过，不修改旧场失败 |
| 最新结果消费 | 实际请求664含downstream日志line_count=0及“空日志不能证明进程不存在”；665含localapp日志line_count=4及证据ID；有限主条件process_present=false获支持 | 传递链路通过，结果精简仍不完整，见下文；本场未出现监听反驳无监听的有限条件机会 |
| 报告与刷新 | 主报告按约定顺序生成，引用、处理和未知均保留；关闭后重开、重复读取与summary诊断相同 | 记录一致通过；处理对象和优先级的语义收束仍不足 |

## 尚未解决到位的两处

**报告仍把故障对象和受影响对象混在一起。** 首行列出downstream、localapp、edge和端口，随后对localapp、edge分别给出泛化的配置/代码核查建议。现场支持优先恢复downstream；localapp、edge的503及日志属于受影响链路。报告没有清楚突出这一处理优先级，也不应因为HTTP503就给三个对象同等的处理权重。当前没有新增通用因果识别能力，本轮没有顺手修改生成器或回填报告。

**并非所有检查结果都被精简成可读内容。** 下一请求确实收到日志行数、进程有限条件、状态与证据ID，但inventory的candidate_check_progress.observation仍为 `{}`。原始配置内容在完整输入里存在，模型却在第6步称“此前inventory结果未在记忆中保留可读内容”并以复核理由再次执行。守卫允许这次有目的复核，不是无限重复；但这说明不能把“结果状态已传入”当成“结果表达已经充分”。资源结果的精简observation也为空，模型仍从原始证据读取了数值。

此外，最终部分纯文字替代解释继续neutral，因未声明合法有限条件，不能自动按文字猜测反证。主条件有支持不等于已区分所有深层原因。保护/矛盾机会及实际改向仍均0，不证明两项机制收益，也不能把与上一场的自主轨迹差异直接归因于本轮修复。

## 费用、清理与证据

本次新增11次请求，全部阿里云 deepseek-v4.1-flash-1017、HTTP200、usage完整，官方兜底未实际调用；模型流程约51.8秒。峰值费率估算新增 **0.394398元**，不是供应商已核账单。账本从657条/20.886226元续到 **668条/21.280624元**，累计边界估算余3.172414元；61条历史未知价继续保留。单场未达0.75元，不自动使用余额续跑。

控制器恢复后，直连与Probe的三个接口均200，所属进程停止、端口释放、清理错误0。恢复由控制器完成，不算人工照报告修复成功。运行源码及旧场文件哈希均未改变，旧付费场failed保留；新场人工诊断、引用支持、建议适用性均pending，AI按控制器核对不代替人审。

- [实际主报告](../runtime/four-fixes-live-20261104-a/model/report.txt)、[原始摘要](../runtime/four-fixes-live-20261104-a/model/summary.json)。
- [本场核对与具体限制](../runtime/four-fixes-live-20261104-a/assessment.json)、[实际请求中的结果反馈](../runtime/four-fixes-live-20261104-a/consumed-results.json)。
- [机械审核](../runtime/four-fixes-live-20261104-a/mechanical-audit.json)、[行为轨迹](../runtime/four-fixes-live-20261104-a/model/mechanism_trace.json)、[关闭后读取](../runtime/four-fixes-live-20261104-a/refresh-readback.json)。
- [授权范围与费用边界](../runtime/four-fixes-live-20261104-a/execution-scope.json)、[最新账本](../runtime/four-fixes-live-20261104-a/model/cost.json)、[恢复清理记录](../runtime/four-fixes-live-20261104-a/controller-result.json)。

本轮交付为一次真实验证及结果分析，仅新增运行材料与文档；没有生产代码修改、第二场付费、四组比较、系统审计开启或前端改版。没有重跑全量测试。下一处值得处理的是已有结果的可读投影和报告的主处理对象，不是继续增加场景或花钱重跑。
