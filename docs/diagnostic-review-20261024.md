# 诊断评分与人工审核口径的免费核验

日期：2026-10-24，分支 main。本轮仅修改离线评测与审核记录，不改变诊断策略、图、API、前端或费用入口权限。

## 实际缺口与修复

既有 review_model_artifacts 已把机械检查与语义正确性分开，capability_passed 保持 false。但仍有以下缺口，本轮通过反例复现后修正：

- 没有 has_final_report 或完成事件、报告为空、事件中有 error 时，原 workflow_status 可能仍为 completed。现在同时要求明确报告标记、非空 complete.response、无预算中断/执行异常/错误事件。控制器调用者同步消费此结果，机械通过但未完成也不能标整场 passed。
- 人工建议的引用与结构原来未参与机械检查。现在检查建议引用属于本次运行且可匹配相应原文，必须具备对象、动作、人工核对状态、证据、前提、风险与后验步骤。检查通过只说明这些要素存在，不证明操作适用。
- 旧无 SQLite 兼容分支可能在整段工具输出中寻找引用。现在引用必须匹配相同证据 ID 的记录；空轨迹不能通过工具权限检查。已有 SQLite 的原文继续只读加载，校验路径、hash、目标和来源；历史证据在原采集时间核对完整性，不据此当成当前新鲜证据。

保留 passed 表示机械门槛的兼容字段，不用它当诊断成功率；workflow_status、result_level_status、semantic_status、recommendation_status 分别记录。localized_fault 与场景预期等级一致不代表对象正确，更不代表因果解释正确。当前目标固定 windows-local-01，审核工具不作为跨目标通用平台。

## 人工审核怎样进行

新增 scripts/diagnostic_review.py，无模型调用、服务启动或自动修复。使用新的独立输出目录，不覆盖已有审核。支持已保存的 output-audit.json 历史输出，或具有 summary.json、events.json、tool_trace.json、report.txt 的模型运行目录。

```powershell
& ./.venv/Scripts/python.exe scripts/diagnostic_review.py prepare <已有运行目录> --output <新的审核目录> --case downstream_unreachable
& ./.venv/Scripts/python.exe scripts/diagnostic_review.py check <审核目录>
```

历史 output-audit.json 自动读取场景与 historical_fixed_decision_api_check 标记；--case 不会把这类样本变成真实模型实验。输出三份文件：

1. review-packet.json：最终报告、结论、建议与相应脱敏原文。去掉结构化 mechanism_config/mechanisms；先评结果再看组别和机制过程。文本仍可能暴露调查行为，不能称严格盲审。
2. source-audit.json：源路径/hash、审核包 hash、场景、运行模式及机械检查。完整性按原文件字节计算，源改变应生成新审核。
3. manual-review.json：审核人、日期、三类意见、理由及证据 ID，初始均 pending。填写这份，不修改源结果。check 校验格式、绑定与引用，返回 recorded 仅表示意见已记录，不表示自动验证正确。

审核人需要另对照控制器独立事实与场景记录，不能只看报告自述。若引用不足，记录 insufficient；正面判断必须关联包内证据并说明理由，不能用建议的措辞替代现场事实。工具无法证明填写者身份或判断真实性；单人审核的限制仍需写入论文。

| 审核维度 | 可选结论 | 判断口径 |
| --- | --- | --- |
| diagnosis | correct_localization / correct_healthy_within_scope / honest_unlocated / wrong_cause_or_false_positive / incomplete | 对照控制器事实判断对象与故障层是否正确，是否额外编造因果；健康仅限已查范围；诚实未定位不能计为定位成功 |
| citation_support | supported / unsupported / insufficient | 逐条判断引用是否支持结论含义；字符匹配仅为机械条件 |
| recommendation | appropriate / inappropriate / insufficient / not_applicable | 前提是否成立、对象是否对应、操作风险和验证是否合理；存在建议时不能用 not_applicable 跳过审核 |

check 拒绝未知选项、已填结论却无审核人/日期/理由、外来证据 ID、无证据的正面判断、跳过已有建议以及源或审核包变化。所有维度 pending 时继续保持待审，不补填通过。本轮测试中的 synthetic test reviewer 仅验证记录格式，不是实际用户审核。

## 结果统计纪律

- 流程完成：明确完成事件和报告，无中断；单列 n/N。
- 定位正确、范围内健康、诚实未定位、误报/错误归因、未完成分别报告，不把前三项合成定位准确率。
- 引用支持和建议适用性单列，未审核项保留 pending，不默认正确或从分母静默删除。
- 真实模型、固定决策历史重放和机械单测分开报告；不把24份重复重放当独立故障样本，不把四组标签当机制有效证据。
- 本轮不生成准确率或效果提升统计，不把 AI 填写当独立人工真实答案。

## 实际核验与失败记录

最终8个相关测试文件288项通过，1项真实子进程故障测试按本轮范围明确排除，1条既有 PyMilvus 弃用警告。结果 runtime/diagnostic-review-20261024-complete.xml；不宣称全仓或外部集成通过。

先复现9项失败，保存 runtime/diagnostic-review-20261024-red.xml。首轮修复后92项通过，审核记录增加后111项通过。扩大回归首次265项通过、10项旧费用测试夹具失败：夹具只有报告标记却未写完成事件，已经补齐，并新增缺完成事件不能标工作流成功的检查，后续扩大回归285项通过；最终再补相同ID引用、空轨迹及人工记录反例后288项通过。相关失败XML均保留，不覆盖。

只读消费上轮 runtime/pytest-manual-advice-20261024-final/ 的24份 output-audit.json，生成 runtime/diagnostic-review-20261024-complete/sample-01 至 sample-24 和 summary.json。每份结论/建议引用、本次ID、建议结构与流程完成核对通过；缺完整工具调用轨迹，no_unapproved_tool 和 has_live_observation 为 false，因此机械总结果未放行。24份人工审核全部 pending，human_reviewed=0、model_calls=0、new_observations=0，原 output-audit 文件 SHA256 不变。该结果验证审核记录方式，不证明自主模型诊断能力。

## 当前状态与下一入口

未调用真实模型或在线检索、未制造新故障、未操作主库或费用账本、未启动停止服务；未运行浏览器或前端构建（未改前端）。未提交推送，原工作树修改保留。本轮没有用户填写实际语义意见，不宣称用户掌握代码或人工语义审核完成。

下一步先免费核对机制行为评分：当前 mechanism audit 主要校验配置和事件有无，需要把保护是否确实改变候选保留/下一检查、矛盾是否对应可靠反证并改变调查方向逐项落到实际轨迹；保留无触发机会、未触发和代价，不以事件数量代替效果，不启动模型或新故障。
