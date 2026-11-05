# 一次诊断的合理结束与人工处理验收

2026-11-03。本阶段实现、唯一配置错误场真实诊断、用户改值后的业务复测均已完成；正式三维人工语义审核仍 pending，不自动生成能力通过结论。

## 实现

- 调查策略在模型建议停止、首选检查受阻或已完成时，复用已有保存候选复核，保留范围、身份、参数、失败记录、反证、保护期限与重复查询守卫。已有通用补查的一项被拒绝后继续检查后续策略；没有无条件模型重试或新调查框架。
- 停止理由记录有限复核范围、候选数量和具体拒绝原因，检查点与报告保持一致。配置历史缺口进入既有 unresolved_questions；无法获得的历史写入者不阻止形成可用故障处理建议，不声称全局穷尽。
- 报告按故障对象/范围、关键事实、解释、人工处理与验证、剩余未知和停止原因组织。配置快照与异常日志同源同值后，建议明确字段、当前值、错误类型和人工改为有效整数的要求，不猜具体业务值。下游停止请求按应用日志来源陈述，发起者 unknown 不提升为独立因果证明。
- 主文使用简短事实与证据 ID；完整引用、JSON、哈希和采集口径仍保留在结构化记录和证据详情。页面先展示处理建议，再展示未知与停止理由；旧记录可继续读取。
- 控制器输出 workflow_status、result_level_status、mechanical_status、semantic_status，增加 capability_explanation 解释 pending 时的 capability_passed=false；布尔字段、历史判定与人审门槛保留。前端没有既有能力审核数据源，因此未虚构新的 API 或审核面板。
- 增加单个配置场可选的有限人工处理窗口；观察外部编辑后独立请求两个接口。超时保持待验收并始终清理，不替人修改配置，也不把文件变化自动归因给人。默认行为兼容原控制器。

## 同一输入的修前/修后

先运行能复现缺口的最小回归：原实现 3 failed / 2 passed，分别暴露模型停止遗漏保存检查、缺少配置建议、缺少能力状态解释。修复后的对应检查通过。另验证事件通道不可用时替代检查确实经执行器执行、结果进入候选及故障事实，执行器没有额外模型请求。

对历史两场最后一步的相同 records、模型提议和前轮状态分别调用修前源码快照与当前实现；输出只写入新目录，不改历史文件。

| 输入 | 修前 | 修后 |
| --- | --- | --- |
| 配置错误 | 主文7462字符，只有HTTP泛化建议 | 主文2271字符，针对max_attempts非法值及ValueError给出人工处理和双接口复测要求 |
| 下游不可达 | 主文5875字符，大量JSON遮盖停止请求 | 主文2907字符，连接/监听/进程事实与shutdown_requested、controlled_stop、unknown按来源陈述 |
| 模型不提下一检查，前轮仍有合法检查 | 停止 | 继续保存的具体检查；真实执行与行为审计回归通过 |
| 通用监听补查被拒，映射进程检查仍合法 | 后续策略被遮蔽 | 继续既有映射进程检查 |

比较材料：`runtime/diagnosis-closeout-20261103-a/comparison.json`、`config-{input,before,after}.json`、`downstream-{input,before,after}.json` 及对应txt。两场原报告、summary、账本和mechanism_trace前后hash一致。离线重放model_calls/tool_calls/new_observations均0，不等于新自主实测。

## 唯一真实配置错误场

运行目录：`runtime/windows-local-faults-0ba0e3f0f85d47ab8f2fd3003c2afc5e/`；模型子目录：`model-b4ecfb594ff546fb8ab955b37a87dc2b/`。通过正式AIOpsService入口执行，取得8份有效现场返回；入口503、下游200、max_attempts=invalid、ValueError日志与独立配置快照同源同值。报告localized_fault；流程、结果层、机械、记录完整性及行为审计通过。

最新账本实际从562条/17.923064 CNY继承到568条/18.041946 CNY；新增6次均DashScope deepseek-v4.1-flash-1017、HTTP200、usage完整，新增峰值预估0.118882 CNY。单场5 CNY，累计24.453038 CNY，估算余量6.411092 CNY；旧562行完全一致，历史未知价格继续保留，供应商账单未核。官方兜底未调用。本阶段没有第二场付费复跑。

通过正式持久化run_details重复读取，本场结构化结论与summary一致；SQLite报告、文件报告、checkpoint response一致，stop_reason与checkpoint blocked_reason一致。证据8条。记录在`runtime/diagnosis-closeout-20261103-a/live-refresh-check.json`。组件刷新读取测试与构建通过；未做实际浏览器交互验收。

## 诊断—人工处理—业务复测

1. 14:37:52开始保留专用业务，人工窗口300秒；14:42:52未观察到修改而到期，原记录为pending_manual_acceptance_timeout，控制器随后恢复并清理。原记录不回填。
2. 用户实际回复“改成5了”；核实原app.mode内容为max_attempts=5，修改时间14:44:17，在原现场清理之后。
3. 14:45:44重新启动同一专用业务，以用户保存的配置、同一入口14751和下游14752做免费处理后复测；没有再次注入故障或调用模型。分别请求下游、入口均200 healthy，新应用日志status=200且无error_type。
4. 复测没有改写配置，付费账本hash未变；两次现场所属进程均停止、端口释放、清理错误0。

这证明用户所选配置能使同一业务恢复，但不是原进程保持运行期间的热修复验收。完整时间线、用户原话、请求结果和清理记录：`runtime/diagnosis-closeout-20261103-a/manual-treatment-and-retest.json`。原窗口超时与控制器恢复只见原`manual-repair.json`和`blind-controller.json`，不得算作用户修复。

## 验收状态与限制

最终相关后端回归676 passed（策略、报告、审核、执行器证据消费、刷新/重开、控制器、记录完整性与账本调用方），仅既有PyMilvus弃用警告。前端AIOps组件15 passed，生产构建通过；git diff --check通过。新增控制器窗口测试最初因错误替换共享time.monotonic造成事件循环夹具失败，已改为仅替换控制器局部时钟并通过最终回归；该失败不是产品运行失败。未运行本轮后端全量或实际浏览器。

正式诊断/引用支持/建议适用性三维人审均pending，审核包`runtime/diagnosis-closeout-20261103-a/human-review/`已生成校验。用户改值与业务恢复不代填三维意见，也不自动将capability_passed改为true。

未开启Windows审计、未新增模型/工具/依赖、未开展四组比较，未追查缺少历史记录的操作者；本轮通过不证明机制效果。工作树已有修改保留，未提交推送。
