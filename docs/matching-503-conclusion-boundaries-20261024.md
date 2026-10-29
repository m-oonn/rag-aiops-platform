# 相同503的正式结论边界修复与免费重放

日期：2026-10-24。分支 main；未调用模型、在线embedding或重排，未注入新故障。

## 查到的实际错误

正式路径是 InvestigationStrategy.decide → evidence_index → decide_from_evidence → diagnosis_result。历史重放也调用同一个 decide_from_evidence；Vue AIOps 页面最终结论读取 diagnosis.conclusion。

原代码拒绝仅引用状态/连接快照确认深层根因，但只要支持引用中加入日志，该限制就失效。使用上轮真实入口503、下游TCP failed和应用连接失败日志，提交过度自信建议“下游进程崩溃导致入口503”，再用入口TCP ok排除“入口TCP失败”，G00实际返回 confirmed_cause。现场证据没有解释进程为何退出；排除一个有限条件也没有证明该因果解释。

新增回归首次运行1失败、4通过，真实失败保留在 runtime/conclusion-boundaries-20261024-before.xml。不是原系统已有失败，也不是模型实验的错误率，是本轮新增反例揭露的裁决漏洞。

## 最小修复及能力限制

共享裁决将模型提出的 confirmed_cause 因果建议保留为未核实假设，清空待执行决策的 root_cause，并记录 validation_issues。原始建议完整保存在 model_suggestion，不改写现场证据或模型原文。结束时只从确定性观察生成 localized_fault，并将记忆中的结论等级同步为 localized_fault；没有已验证故障观察则报告 unlocated。有效后续检查仍继续，范围健康结论仍走原有门槛。提示词也写明当前因果验证限制。

**这是实质性限制：当前自主调查裁决没有验证自由文本因果的实现，不能自动输出 confirmed_cause。** 真实配置日志可以作为原文引用展示，仍不足以让程序验证任意因果描述。没有添加关键词匹配、第二个模型裁判或controller答案白名单来假装解决因果判断。后续如果要恢复自动根因确认，必须明确受支持的因果证据契约并独立验证；本轮没有实现该能力。毕设当前可交付深度仍是定位对象/故障层、解释证据、保留未知原因和人工修复建议。

调用者影响：实时调查与旧历史重放共用修复；四组门槛相同；API/SSE/前端字段结构未变。未修改LangGraph图、机制开关、工具权限、知识条件和数据表。

## 真实证据夹具与可复现检查

tests/fixtures/matching503-probe-20261024.json 从上轮受ACL保护的产物复制六条测试业务Probe原文，保留ev ID、采集时间、raw_hash、目标、日志路径/PID。没有复制控制器故障答案到调查state。源文件SHA256同时记录；最后只读核对六条原文及两个源文件hash全部一致，源产物未改写。审计见 runtime/matching503-boundaries-20261024-a/source-audit.json。

scripts/verify_matching503_conclusions.py 复用 evidence_index(now=历史采集窗口) 与正式 decide_from_evidence。两场分开构造状态，不把前一场故障残留合并到后一场；不修改采集时间来冒充当前证据。报告同时记录 checked_at 与 historical_validation_time，model_calls=0、new_observations=0、autonomous_model_success_proven=false。脚本自身只核验夹具，original_runtime_revalidated=false；原runtime核对由独立source-audit记录承担。

72项检查 = 2种现场 × 3档证据（入口；入口+下游；入口+下游+日志）× 3种建议（下游崩溃；配置解析；无关数据库磁盘损坏）× 4组独立开关。这是规则反例检查数，不是72次自主调查或机制效果实验。所有建议为有意过度自信的验证输入，不由模型生成，不据此统计诊断准确率。

| 输入证据 | 允许报告的现场事实 | 拒绝的扩展结论 |
| --- | --- | --- |
| 仅入口503，两场分别核验 | localapp入口HTTP失败 | 下游不可达、配置错误、进程崩溃等因果确认 |
| 入口503+下游TCP failed | 入口HTTP失败、下游连通层异常 | 下游为何退出或崩溃 |
| 入口503+下游TCP ok/HTTP200 | 入口HTTP失败，下游本次探测正常 | 下游TCP不可达；无日志时配置原因 |
| 再加真实入口日志 | 上述故障层与可追溯日志原文 | 原文存在就认定自由文本因果已验证 |

运行：

```powershell
& ./.venv/Scripts/python.exe scripts/verify_matching503_conclusions.py --output runtime/matching503-boundaries-<独立新目录>
```

已完成输出 runtime/matching503-boundaries-20261024-a/report.json：72项通过，所有正式结论为localized_fault，夹具未改写。前端读取的正式结论不含过度自信根因；这轮未用浏览器检查页面。

## 回归与尚未验证的部分

直接相关四文件176项通过。最终12文件413项通过，1条既有PyMilvus弃用警告，记录 runtime/conclusion-boundaries-20261024-final.xml。范围包括调查裁决、机制、历史重放、真实图替身流程、事件、知识消费、现场机制脚本、Windows评测与故障控制器。新增检查还核验：历史证据到期失效；篡改hash/目标/时间被拒绝；另一场日志不能提供不存在的配置原文；未确认建议仍能继续有效日志检查；健康范围结论仍可通过。

未运行全仓、前端构建/浏览器、真实模型或新现场故障。没有启动/停止常驻服务，没有重载主API；本轮源码通过不代表页面正在运行新版。未改.env或主数据库、未提交推送。既有工作树修改及删除保留。

## 计划与下次入口

本轮完成两类现场原文经过正式裁决的边界检查，尚未完成自主模型能力或阶段B整体验收。系统能力推进已有验证；没有新增用户带读/亲手验证记录，不宣称用户独立掌握裁决代码。

下一步免费把这两类历史证据送入正式service/graph/SSE输出的完整回归，核对证据引用、降级限制及最终结果在事件流和刷新读取中一致。复用现有固定决策测试模式，保持model_calls=0；不启动业务注入、不把重放称为自主现场诊断。如果源码已有完整覆盖，先确认再补缺口，不额外造页面功能。

2026-10-24 后续已完成该步骤，见[完整输出链路验收](matching-503-output-flow-20261024.md)：24次固定历史输入流程、48条重复入账原文、SQLite重开/API/Vue消费一致性通过；最终444项后端回归通过。仍未进行自主模型或真实浏览器验收。
