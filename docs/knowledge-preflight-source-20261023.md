# 故障预检知识源接线与来源核验

日期：2026-10-23。范围为免费预检入口修复、离线回归和当前 MCP 只读检索，不是自主诊断或新一轮故障注入。

## 发现及处理

原 preflight 写死库 14、查询 localapp availability 和片段 localapp-guide。源码核对发现，这是隔离故障控制器自己的旧夹具，不是可以直接改成主库 15 的错误数据。现保留旧默认库和查询，取消对固定片段名的依赖，增加 --knowledge-kb-id、--knowledge-query、--knowledge-source 三项免费预检参数。main 将参数实际转交 preflight；自定义参数没有 MCP、被知识关闭覆盖或用于付费模式时直接拒绝，防止参数被默默忽略。

预检通过实际返回检查：非空片段、来源文件名、片段 ID、正整数页码、返回库 ID 与请求库一致；若给出期望文件名，还必须至少命中该文件。成功、空结果、错库、缺来源或服务异常都保存 knowledge-preflight.json；失败继续抛错，不把失败写为成功。来源核验不证明语义相关性或因果正确。

当前 RAG MCP 同时列出 search_knowledge_base、list_knowledge_bases、get_document_info。旧工具装配拒绝完整目录，现允许这三个已知知识工具存在，但仅装配和使用 search_knowledge_base；未知工具仍拒绝，库列表和文档信息不会被预检调用。

knowledge_preflight 是同一来源核验函数，可独立只读检查知识工具；完整 preflight 继续先核对知识再读取 Probe 清单、依赖和允许日志。知识结果不计入现场证据数量，仍标记 autonomously_selected=false。没有扩展跨用户权限，也没有更改主服务知识工具。

## 使用方式与范围

在已有、经核实允许查询的 Probe 配置下，免费入口可使用以下参数；本报告没有执行这条完整命令：

```powershell
& ./.venv/Scripts/python.exe scripts/evaluate_windows_probe.py --knowledge-mcp-url http://127.0.0.1:8105/mcp --knowledge-kb-id 15 --knowledge-query '应用内部异常' --knowledge-source 02-application-errors.pdf
```

默认省略 --run-model 即免费预检，不发模型请求。命令依赖已有 Probe 配置与在线状态；知识服务是否使用收费检索仍由其实际实现决定。本项目当前库 15 已核实为本地 BM25。新参数仅用于预检，不会替付费调查配置候选、修改模型提示或强制知识调用。旧控制器不传参数时继续使用隔离库 14。

## 实际验证

首轮两个相关文件 101 项通过。补强正整数页码及旧默认入口后，五个相关文件 189 项通过：test_windows_probe_evaluation、test_windows_local_faults、test_agent_knowledge_consumption、test_knowledge_bm25_pipeline、test_probe_investigation_flow。覆盖参数拒绝与透传、真实 PDF/SQL 到完整预检函数、来源和错库失败、失败产物、完整/最小工具目录及控制器兼容。四条既有 PyMilvus 弃用提醒；无本轮测试失败。结果 runtime/knowledge-preflight-20261023-final.xml。

本轮实际通过现有 8105 HTTP MCP 只读查询主库 15。最终代码正向查询“应用内部异常”命中三片段，首条为 02-application-errors.pdf 第 2 页，主文档 ID35，实际片段 doc_9eac2f97-9499-4ad6-99fb-d37dac5a51a4_chunk_1；无关查询 quantum entanglement 返回空，来源核验按预期失败并保存记录。两次均无模型调用、无现场证据入账。独立产物：runtime/knowledge-preflight-final-6bb06c11fc8340e9965d09ec736cedbb/matched 与 empty，各保留 knowledge-preflight.json 和 tool_trace.json。

离线完整 preflight 用真实 PDF/SQL 和固定 Probe inventory 验证编排；实际常驻服务核验只覆盖知识部分，没有执行完整 Probe/故障控制器。因此不能声称真实故障已联合使用新 PDF 或模型会自主检索。

## 进度和下一步

免费知识预检入口和主知识服务来源验证完成。下一步免费核对故障控制器如何为每次运行固定并保存语料版本、知识入口和配置，避免各场样本实际知识条件变化却只比较机制标签；先补缺口及离线回归，再确定真实故障联合预检范围。正式模型复验与四组效果实验仍未启动。

本轮只修改脚本、测试和记录，未改 .env、主数据库、前端或服务配置，未重启常驻进程、提交或推送。未重复上轮全仓回归和前端测试；相关控制器与接线回归通过。此前新增 planner 仍未重新加载至常驻 API，主知识检索通过不能等同主诊断已启用新规划路径。
