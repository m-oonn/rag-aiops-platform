# 四组机制与真实 Probe/MCP 联合核验

日期：2026-10-23。免费工程验收，固定模型决策，真实现场工具；不是自主诊断或效果实验。

## 实现与范围

新增 scripts/verify_probe_mechanisms.py，复用正式 service.execute、planner、executor、replanner、机制规则与证据写入；仅替换模型响应，不替换生产图节点或制造机制事件。verify_windows_local_faults.py 在 --evaluation-preflight 且没有 --run-model 时调用它。普通入口及付费入口保持既有行为，不新增依赖。

三类固定决策条件各运行 G00/G10/G01/G11：候选遗漏、下游健康反驳 failed 预期、尚无现场反证。模型替身不读取组别；四组仅保护与矛盾开关不同。每组独立 SQLite 账本、证据目录、checkpoint 和随机 thread，关闭重开后核对调查记忆及原始证据。工具包装仅记录调用，返回原始 MCP 结果。网络只允许回环 HTTP。

本次机制核验在控制器恢复正常业务后运行，因此入口与下游均真实健康。候选与遗漏由固定决策构造，只证明机制接线；不能声称保护了真实正确根因，不能作为未知答案故障样本。其他真实故障与恢复仍由完整控制器分别验证。

## 实际现场结果

成功目录：runtime/windows-local-faults-08d47a93e78a4e09949ca628832b055e/。live-mechanism-groups.json 保存十二次调查比较，各组有 events.json、calls.json、mechanism_trace.json、planner-context.txt、知识审计和数据库。

| 固定条件下的第三步实际检查对象 | G00 | G10 | G01 | G11 |
| --- | --- | --- | --- | --- |
| 已保存入口候选随后遗漏 | 下游 | 入口 | 下游 | 入口 |
| 第二步下游 TCP ok 反驳 failed | 下游 | 下游 | 入口 | 入口 |
| 第二步只有日志，尚无 TCP 反证 | 下游 | 下游 | 下游 | 下游 |

十二次调查共36条互不重复现场证据，知识不入现场账本；三类各组规划手册指纹和调查知识指纹一致。完整规划输入含实时 inventory 的时间与证据ID，因此逐场保存但不要求整段逐字一致。24份知识前后审计均通过、同一指纹，未生成 cost.json；仍是自有 Markdown/BM25 库14，remote_index_verified=false，不代表主 PDF 库15完整索引验收。

流式机制摘要与最终事件一致。两个 contradiction_triggered 事件的 ev ID 已从每组 SQLite 追到证据文件，operation=dependency_probe、dependency=downstream、tcp=ok。无现场反证场景在第二轮之前没有 contradiction_triggered 或 contradiction_blocked；第三步实际获得下游健康反证后，开启触发的组记录 contradiction_blocked，因为已无可执行替代检查。这与“没有反证也触发”不同，不能忽略最终事件。保护场景也保留保护到期及后续反证停止事件。全部最终报告为未定位，不把正常探测上升为根因。

完整控制器 summary.json：ok=true，25个检查条目（其中1项汇总十二次机制调查），控制器原有44条证据与机制36条证据分别记录，不能把44当总数。model_calls=0、errors=[]、owned_processes_stopped=true、ports_released=true。六个常驻监听PID与此前一致：5273=31072、8200=33000、8105=19412、8103=34456、8104=34312、8106=35216。

## 回归与失败保留

新增 tests/test_live_probe_mechanisms.py：替身工具完整验证十二次调查，并用错误TCP结果验证脚本失败，错误分支要求明确的观测断言，防止因别的错误偶然通过。最终六个相关文件200项通过，4条既有PyMilvus弃用警告；记录 runtime/live-mechanisms-20261023-final2.xml。最终补强事件轮次与反证对象断言后重跑该回归；现场产物另外只读核对两条反证引用通过，未为断言补强重复故障注入。

早期离线a/b/c失败分别暴露夹具inventory缺已配置对象、text_log与正式text_logs协议不符、把含动态现场信息的整个规划输入误作知识指纹。均已修正，日志保留。首轮现场因断言漏计planner的probe_list_evidence失败，目录runtime/windows-local-faults-ba0baf6785434e589ad2b08b87f67f38/；已纳入规划读取断言及离线夹具，第二轮通过。两轮现场日志为runtime/live-mechanism-controller-20261023-a.log和b.log；首轮失败也完成临时进程与端口清理。没有放宽生产守卫。

## 当前边界与下一步

本轮只新增验证脚本、测试和控制器免费接线，没有修改生产机制、主数据库、.env或前端，没有重启常驻服务、提交或推送。未重复全仓测试、浏览器或真实模型。此前planner改动仍未加载到常驻API。

下一步先免费核对真实故障的场景可区分性：现下游故障503与应用错误500并不构成严格相似症状；复用控制器最小构造同样入口503而下游事实不同的两类故障，独立核对恢复和日志，不预写真实模型候选、不保证机制触发。随后再评估是否仍有免费必修缺口。正式四组效果和自主行为继续暂缓，付费需另行授权。

学习要点：同一工具名也可检查不同对象，必须一起看参数、原始证据和事件轮次。系统已验证此链路，用户独立掌握程度没有本轮复述记录，保持未验收。
