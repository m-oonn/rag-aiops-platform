# 相同503完整输出链路的免费验收

日期：2026-10-24，分支main。沿上轮正式结论边界修复，核验实时输出与持久化刷新一致性。本轮没有修改生产代码。

## 实际经过的流程

tests/test_matching503_output_flow.py 通过内存ASGI请求调用正式POST /api/v1/aiops，再进入AIOpsService.execute、原LangGraph、真实executor工具执行、Probe校验与入账、InvestigationStrategy及共享裁决，返回实际EventSourceResponse序列化的SSE。

替换项明确限定为初始计划、模型工具调用建议、模型调查决策，以及两个StructuredTool返回。返回值来自上轮六条真实Probe原文。没有连接MCP或制造新故障，因此不称为自主模型调查或现场端到端。历史数据校验的时钟仅在测试中固定到各场采集窗口；原始collected_at、payload及raw_hash均不改，正式API的证据列表仍按当前时间返回fresh=false。没有加入生产历史时钟开关。

每次使用独立SQLite运行库、checkpoint与证据目录。通过HTTP消费结束事件后关闭服务、释放checkpointer，创建新的服务对象，再调用正式GET /runs/{thread_id}、证据列表、受保护原文、steps接口。没有重启本机常驻服务或使用主业务数据库。

## 验收结果

24次固定输入流程 = 2种历史现场 × 3档证据（入口；入口+下游；再加日志）× 4组机制开关。共48条历史证据记录，是六条原文在独立流程内重复入账，不是48条新增现场观测。model_calls=0、new_observations=0。

- SSE report/complete的诊断、报告、调查摘要一致；重开后GET返回同样内容，运行状态completed仅表示流程结束。
- 全部正式结论为localized_fault，保留因果解释未验证的提示，不泄露固定建议“下游进程崩溃导致入口503”到正式结论/报告。
- 两类入口503都定位入口HTTP失败；只有实际下游TCP failed场景增加下游连通故障层。下游正常场景不产生TCP故障结论。缺日志时没有配置原文，有日志时仍保持原文引用。
- 48条证据的采集时间/hash/原文逐项保持，所有结论引用ID都能经正式证据API读回原文。证据列表在当前时间显示历史过期，保持结论与证据时效的不同含义。
- 三步流程真实通过executor两轮固定ReAct调用；调查器每步一轮固定决策。关闭/重开及刷新不再次调用工具或决策；checkpoint最终无待执行节点。
- 普通用户可看摘要和结果，不能读raw/raw_ref；另一用户读取结果/证据返回404。原始模型建议只保留在内部checkpoint，不进入investigation摘要。

最终产物在runtime/pytest-matching503-output-20261024-final/，每次保存output-audit.json、runs.sqlite、checkpoints.sqlite及证据原文。汇总runtime/matching503-output-summary-20261024.json保存24份审计文件hash、四组及48条记录计数。

## 前端实际消费

从最终G11六次API结果提取frontend/src/views/__fixtures__/matching503-api-20261024.json，保留对应输出文件SHA256、历史时间、实际SSE事件、刷新结果和真实普通用户证据列表。夹具为离线验证数据，未接入页面运行入口。

frontend/src/views/AIOps.matching503.test.js 挂载真实Vue/ElementPlus组件，输入症状并点击开始，用127字节分片回放UTF-8 SSE内容，再卸载和重挂载模拟刷新。六类结果逐项核对：实时/刷新结论和报告相同；“故障层已定位，深层原因未明”及判断校验可见；两类现场差异正确；配置日志只在有日志档出现；引用按钮展开证据，普通用户不请求原文接口。这是jsdom组件验证，没有浏览器与真实HTTP服务连接，不宣称主5273已在线加载新版。

## 检查、失败与限制

最终14个后端文件444项通过，1条既有PyMilvus弃用警告，结果runtime/matching503-output-20261024-final.xml。前端全量18文件107项通过；最后夹具更新为最终普通用户接口后，两个相关文件18项通过。Python编译及本轮文件diff检查通过。

首轮测试用了不存在的ENABLE_HYPOTHESIS_PROTECTION配置名，在流程开始前失败。已改成真实INVESTIGATION_HYPOTHESIS_PROTECTION/INVESTIGATION_CONTRADICTION_TRIGGER。异常展开Settings对象，本轮XML已将该对象替换为[REDACTED]，保留失败类型与不存在属性的原因；后续不输出完整配置。第二轮24项通过但SSE库shutdown watcher未退出；测试增加仅清理本次创建watcher的fixture，后续24项及最终回归未再出现该提醒，不修改第三方库或生产关闭流程。

未运行全仓后端、生产构建、真实浏览器、真实模型或MCP现场。测试新增文件不会改变生产构建入口，未重复构建。未改.env、主数据库、机制实现和API/前端契约，未启动停止服务，未提交推送；此前未提交工作保留。当前仍没有自动验证自由文本因果能力，不能输出自动确认根因的能力声明。

## 下一步与掌握情况

本轮完成实际输出链路验收，没有新增用户操作/复述记录，不宣称用户已独立掌握代码。

源码复核发现下一项直接对应毕设必达目标的缺口：InvestigationDecision及正式报告没有明确的人工修复建议字段或受证据约束的输出。下一步先追踪调用者，补最小建议与前提/风险/验证步骤，将“建议”与现场事实、未确认原因区分，沿同一报告与刷新链路免费回归；不自动修复、不调用真实模型。建议是否正确仍需人工审核，不能借建议补写未知根因。
