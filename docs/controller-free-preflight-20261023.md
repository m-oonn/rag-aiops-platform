# 免费完整控制器预检验收

日期：2026-10-23。使用当前 main 工作树运行，不代表未提交改动已经集成发布。

## 范围与结果

运行 `.venv/Scripts/python.exe scripts/verify_windows_local_faults.py --evaluation-preflight`，真实启动本轮专用 HTTP 入口、下游、临时 Probe、网关与知识 MCP，仅停止本轮拥有的进程。结果目录：`runtime/windows-local-faults-17c01c89cf47492ba881302db440d2dd/`。

`summary.json`：ok=true，24 个检查条目全部通过，44 条正式现场证据，model_calls=0，errors=[]，owned_processes_stopped=true，ports_released=true，remaining_listeners=[]。覆盖正常、应用退出和恢复、下游不可达和恢复、HTTP 不健康、应用错误、专用端口冲突、最终恢复，以及工具权限拒绝、无效证据拒绝、Probe 重连和网关重启后历史基线读取。六类控制器场景另有独立现场快照，不作为 Agent 的输入或证据。

正常和下游不可达两次评测子进程均完成知识条件前后核对，共四份 knowledge-conditions-before/after.json，passed=true，指纹均为 `6f5ab10f7dbe8f3a066239fde02498b960cc035230db12cb130907251595568a`，地址均为本轮 `http://127.0.0.1:12000/mcp`。输出目录没有 cost.json。remote_index_verified=false，仍只核验控制器自有 Markdown/BM25 库14的本地构造条件，不代表主 PDF 库15或任意远程索引版本验收。

两次正式图调查使用固定模型响应、真实工具与证据写入，核对知识参考与现场事实分离、调查中检索、证据权限与 checkpoint 重开。它们没有要求候选保护和反证改向事件，不能据此宣称两项机制在真实现场链路的四组验收已完成，更不能宣称自主诊断或效果提升。

## 失败、权限与常驻服务

首次沙箱执行在设置私有目录 ACL 后复制语料失败，尚未启动测试进程。目录只授予管理员、SYSTEM 和 LocalService，沙箱账号没有写权限；保留 ACL，经工具权限流程在正常管理员上下文重跑通过，没有修改权限策略。首次日志保留 `runtime/controller-free-preflight-20261023.log`，失败目录为 `runtime/windows-local-faults-ff47cbe46f24461583e8e757f95a04fe/`；成功日志为 `runtime/controller-free-preflight-20261023-b.log`。

运行前后常驻监听 PID 一致：5273=31072，8200=33000，8105=19412，8103=34456，8104=34312，8106=35216。未重启、停止或接管这些服务；未改 .env、主库或业务源码，未提交推送。此前 planner 新逻辑仍未重载至常驻 API，不宣称当前主诊断已使用库15。

## 下一步与学习入口

下一步先核对并补齐免费机制现场链路：复用真实 Probe/知识 MCP，使用固定结构化决策进入同一调查实现，分别核验保护、反证改向与不适用场景的四组实际工具顺序和证据关联；先检查既有测试覆盖再补最小缺口，不新增平台或付费调用。固定决策验证工程接线，自主行为与正式效果实验仍需以后单独确认费用。

用户本次只需掌握：控制器独立核实故障，Agent 从 Probe 获取现场事实，手册提供参考；知识指纹一致只约束实验条件，不证明判断正确。没有本轮复述或亲手操作记录，不据此更新用户掌握程度。

本轮没有业务逻辑修改，未重复全仓单测、前端构建或浏览器验收；前轮198项离线回归与本轮24个现场检查分开记录。
