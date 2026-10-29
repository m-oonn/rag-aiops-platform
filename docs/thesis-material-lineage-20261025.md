# 论文材料来源与可用结论

2026-10-25。来源核对完成；来源一致不代表语义判断正确或自主诊断有效。

## 已核实的来源

报告链：runtime/windows-local-faults-87750cb6d3f34bc6b55ff26319f19e9e/evidence.json → tests/fixtures/matching503-probe-20261024.json → runtime/pytest-manual-advice-20261024-final/ 的24份 output-audit → runtime/diagnostic-review-20261024-complete/ 的24份审核包。

两类故障各三条原始观测，共6条；两类×三档证据×四组构成24次固定决策API重放。48个重新入账的 evidence ID 仍对应这6条观测，不能计作48次独立采集或24次独立故障实验。

机制链：runtime/windows-local-faults-08d47a93e78a4e09949ca628832b055e/ 的12场原轨迹、checkpoint和现场文件 → runtime/mechanism-behavior-history-20261024-final/ → runtime/mechanism-run-summary-20261025-final/summary.json。三类固定决策场景×四组，共36条现场观测。两批没有相同的完整观测，但观测不同也不证明试验独立，不能合称36个自主实验。

新增 scripts/audit_thesis_materials.py 核对源hash、控制器原文、各档重放证据前缀、审核包报告与结构化诊断、现场事件与证据文件。按完整观测（含目标、操作、采集时间、payload/hash）去重，不按重新分配的ledger ID计数。控制器场景带controller-前缀，夹具不带，显式匹配既有关系，不修改旧记录。人工审核复用diagnostic_review.check，24份仍pending；旧机械总结果未放行的状态保留。

## 论文能写什么

| 材料 | 能支撑 | 不能支撑 |
| --- | --- | --- |
| 两类真实503现场、6条观测 | 场景可制造、采集和恢复，响应相同而下游及日志事实不同 | Agent已自主区分原因、覆盖生产业务 |
| 24次API/图/SSE/刷新重放 | 固定输入下结论边界、报告及建议一致性 | 24次独立故障、自主选工具、定位准确率 |
| 24份hash绑定审核包 | 引用和意见可追溯，待审不记正确 | 人工语义审核完成、引用字符匹配证明因果 |
| 12场固定决策现场 | 机制改变计划并执行对应对象工具，阻塞单列 | 保护了正确原因、提高自主诊断效果 |
| 工具次数及部分耗时 | 本批每场5次调用、3/5计时覆盖 | 完整耗时、因果开销、真实模型成本收益 |

仍缺真实模型自主复验、未参与调参样本的正式四组实验、真实人工语义审核、完整耗时与本场模型usage/费用，以及用户亲手复现和独立讲解记录。不自动补成绩。

## 实际验证与失败

最终3个相关测试文件52项通过，新来源测试9项；覆盖缺包、重复包、错源、hash错误、审核包变化、现场缺件、采集时间身份及重绑定后诊断被替换。结果runtime/thesis-lineage-20261025-final.xml。有4条既有PyMilvus弃用警告；公共conftest导入应用有既有向量库初始化，没有执行索引或入库。不宣称全仓或外部集成通过。

首次实际来源核对未通过：脚本误按完全相同场景标签查询，六条原文虽相同却因controller-前缀查不到。修正显式映射并补反例后，第二次核对通过，最终再核对包含诊断正文的链路。首轮失败保留。一次补丁因换行格式失败未落地；一次工具脚本语法错误未执行，随后修正，未影响源数据。

最终输出runtime/thesis-material-lineage-20261025-final/lineage.json与lineage.md，含逐份来源、观测关联及源hash。无新模型或现场观测，未改审核意见、生产调查/API/前端、费用账本或旧数据，未启动停止服务、提交推送。未运行浏览器或真实故障。

复现：在项目根目录用 .venv/Scripts/python.exe -m scripts.audit_thesis_materials，传入 --reviews runtime/diagnostic-review-20261024-complete、--mechanism-summary runtime/mechanism-run-summary-20261025-final/summary.json、--fixture tests/fixtures/matching503-probe-20261024.json 和 --output 新的独立目录。

## 下一入口

免费核对现有论文方法与实验草稿，按实现和证据修正不一致处；自主效果表保留待实验，不用重放或旧策略数据补成绩。仍不启动模型或新故障。需要理解：原始观测、重新入账记录、流程执行次数、独立试验是不同统计单位，本轮不据此宣称用户已独立掌握。
