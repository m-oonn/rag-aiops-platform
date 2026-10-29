# 机制行为评分与历史现场核对

2026-10-24。结论：免费机械核对已完成，实际执行与事件标签分开；尚未证明自主诊断或机制收益。

## 本轮改动与调用链

`evaluate_windows_probe.save_mechanism_audit` → 图的决策 checkpoint → `behavior_snapshot` → `audit_behavior` → 保存结果。新增 `scripts/mechanism_behavior.py`，记录当轮模型原提议、可校验现场证据、候选、计划、工具目录、业务范围和已完成步骤；从最终 `raw_evidence` 提取既有 `tool_execution`，核对成功状态、工具名及候选对象参数。

核对对象包括：候选被遗漏或被无依据排除时的有限保护机会；此前领先候选遭到可靠新反证的机会；保护候选是否保留；选中检查是否对应当轮计划；下一步是否实际执行了对应对象的工具；反证后是否缺少可执行替代检查而阻塞。累积事件去重，重复读取不重复记改向。

选中检查与模型原提议相同，可以记录成功执行，但 `executed_changes` 为零；同名步骤没有成功工具记录、工具对象不符或执行失败，不能作为已执行。`contradiction_blocked` 单列，不能当改向成功。开启机制却漏掉应有的选择或反证记录时核对失败。

原配置审计的 `passed` 保留兼容口径，新增 `behavior.status` 区分 passed、failed、not_assessed；旧轨迹缺少上下文时为 not_assessed。四组模型实验入口必须配置与行为均通过，不能把 not_assessed 当四组验收通过。免费固定决策控制器同样显式检查行为结果，并保存到逐场汇总。

本轮修改评测脚本、夹具和回归检查，没有修改生产调查机制、API、图结构或前端。旧图测试使用模拟 executor，已补其测试专用工具执行记录；不是新增真实工具观测，也不能证明该模拟工具现场执行。

## 只读历史核对

输入：`runtime/windows-local-faults-08d47a93e78a4e09949ca628832b055e/` 中三类场景乘四组，共12份原 `mechanism_trace.json` 与对应 `checkpoints.sqlite`。

命令（输出目录必须不存在）：

```powershell
& ./.venv/Scripts/python.exe -m scripts.verify_historical_mechanism_behavior --source runtime/windows-local-faults-08d47a93e78a4e09949ca628832b055e --output runtime/mechanism-behavior-history-20261024-final
```

仅以 SQLite `mode=ro` 打开可信本地数据库，匹配旧轨迹 step、plan、tracking、next_tools 的决策边界；缺边界不能通过。使用原 checkpoint 时间重新校验历史证据，不改原采集时间或原文。新结果与源 SHA256 另存，原24个源文件前后 hash 一致。旧JSON自身全部 not_assessed；从 checkpoint 重建后12份行为核对均 passed。

| 历史场景 | G00 实际改查 | G10 实际改查 | G01 实际改查 | G11 实际改查 | 阻塞事件合计 |
| --- | --- | --- | --- | --- | --- |
| protection | 0 | 保护1 | 0 | 保护1 | 2 |
| contradiction | 0 | 0 | 矛盾1 | 矛盾1 | 2 |
| no_live_refutation | 0 | 0 | 0 | 0 | 2 |

合计：4次保护机会、14次反证机会；成功执行的保护改查2次、矛盾改查2次，阻塞6次。机会数包含关闭组，且后续调查分支不同，不能把合计直接作四组效果分母。每场完成3个 executor 步骤，未估算相对基线费用或收益。

`no_live_refutation` 前两轮没有现场反证；第三轮实际检查下游 TCP 成功才出现反证，开启触发的组记录阻塞。不得依据场景名称把整场当作无触发机会。真正无机会及模型原已选同一检查的情况另有机械回归反例，不能伪装为新的现场样本。

完整结果：`runtime/mechanism-behavior-history-20261024-final/summary.json` 与12份逐场JSON。`model_calls=0`、`new_observations=0`，没有重跑故障或采集工具。

## 验证及限制

最终9个相关测试文件362项通过，1项 `real_disposable` 真实故障测试按本轮范围排除，1条既有 PyMilvus 弃用警告。结果：`runtime/mechanism-behavior-20261024-final.xml`。覆盖四组机会/执行、错对象、过期/截断/伪造反证、执行失败、缺记录、漏选择、同检查无额外改向、重复事件、阻塞、历史缺边界、源不变和禁止覆盖输出目录；四组入口拒绝 not_assessed 的测试没有发模型请求。

开发失败保留：`red.xml` 为新模块未实现的15项红灯；`first.xml` 为17项新夹具/审核器漏必填 status 的失败，修正后 `second.xml` 103项通过；`third.xml` 21项、`fourth.xml` 115项、`broad.xml` 350项、`history-test.xml` 29项通过。文件均在 runtime 下以 `mechanism-behavior-20261024-` 开头。这些失败不是17个生产机制漏洞，也没有删除旧运行。

机械核对复用生产的有限谓词、候选ID及可执行检查校验；能够发现记录之间不一致，不能独立证明算法或检查语义正确。历史证据视图按 checkpoint 时刻重建，并非生产裁决瞬间原视图；证据恰好跨过时效边界时可能产生差异，应保留差异而非修改原时间。成功工具状态和对象参数不等于最终证明因果，候选正确性仍为 `pending_manual_review`，`mechanism_effectiveness_verified=false`。

当前带条件候选的对象绑定只覆盖与预期操作一致的 Probe 检查；例如用日志检查来调查 TCP 失败的跨操作语义关联，不能靠这一参数规则自动放行。没有有限条件的候选只能核对计划、工具与成功状态，检查内容是否有鉴别力仍需人工判断。

未调用模型、在线 embedding/重排；未启动停止服务、重载主API、修改知识库或费用账本；未运行前端或外部集成（无相关改动），未提交推送。用户尚未填写真实语义审核，不宣称用户已独立掌握代码。

## 下一入口

按路线继续免费汇总四组逐场结果与实际工具次数、耗时和检查代价，保留未完成、阻塞与待审；人工审核未填不生成准确率或有效性结论。当前关键理解点：事件出现、选中检查、实际工具执行、定位正确是四个不同的判断。仍不启动真实模型或新故障。
