# Windows Probe 本机免费验收记录（2026-10-18）

本记录只覆盖本机只读验证。没有调用付费模型，没有停止或修改真实业务服务，没有启动 Docker，没有扩大 Probe 白名单。

## 已通过

- `RagAIOpsProbe`：`Running / Automatic / NT AUTHORITY\\LocalService`。
- 直接采集：`scripts/verify_windows_probe_readonly.py`，inventory、资源、服务、进程、端口边界通过。
- 回环链路：`scripts/verify_probe_local_runtime.py`，Probe → WebSocket → Gateway → MCP → LangChain MCP adapter 通过。
- 安装服务正式执行器闭环：临时只绑定 `127.0.0.1:18767` 的网关接收安装服务主动连接，`scripts/verify_installed_windows_probe.py --executor-batch` 通过。
- 该次闭环记录：`runtime/probe-final-aec69a56288f456ab310f5cf534da9fc`。实际读取 inventory、resources、两种进程排序、ports、配置服务和 Event Log；目标为 `windows-local-01`，状态为 `online`，模型调用为 0，历史基线 5 条。
- TLS/WSS：`scripts/verify_windows_probe_tls.py` 通过。错误 CA、主机名不匹配、过期证书均拒绝；真实回环 WSS/HTTPS/MCP inventory 通过；系统信任和已安装服务未被修改。
- 知识库本地检索：`scripts/verify_windows_runbook_retrieval.py` 通过，5 类 Windows 症状命中手册；这是词法/BM25 验证，不是 embedding 或重排验证。
- 临时故障与证据链：`scripts/verify_windows_local_faults.py --evaluation-preflight` 通过，31 条证据，模型调用为 0；覆盖正常、进程退出、依赖不可达、HTTP 异常、端口冲突、恢复、断线重连、网关重启后的 SQLite 基线、伪造证据拒绝和 checkpoint 重开。
- 基线清理：`scripts/verify_probe_retention.py` 通过，启动清理、无 Probe 时 60 秒定时清理、未过期基线保留、诊断证据不变、优雅退出和端口释放均通过。
- API/浏览器：正式 API 路由、JWT 权限和真实浏览器证据时间线通过；普通用户只能读取自己的脱敏摘要，审计权限才可读取原始内容，跨用户访问拒绝。
- 跨 API 进程待审恢复：`scripts/verify_aiops_cross_process_resume.py` 通过（最新记录 `runtime/cross-process-357ed36c80ca4f31af6ba9cd593b7558/summary.json`），独立第一/第二 API 进程共享隔离 SQLite；第二进程从待审 checkpoint 恢复，规划器与执行器均未重放（`0/0`），批准后的输出工具只调用一次；错误用户续跑返回 404，完成后重复续跑返回 409。使用正式 HTTP 路由和 JWT，但模型、Termcp authority 和 shell 输出均为测试替身，因此只证明运行记录和 checkpoint 恢复接线，不证明真实模型或 Termcp UI。
- 故障预检复跑：`runtime/windows-local-faults-317b30627596405cadeb433043efa224`，31 条证据、正常/进程退出/下游不可达/HTTP 503/应用 500/端口冲突/恢复/断线重连/网关重启基线均通过；模型调用 0 次，专用进程和端口已清理。
- 页面真实入口复跑：`runtime/aiops-browser-56c45b9d703c49cc952c5eb20c821e9e/summary.json`，真实 Edge 登录并从 `/aiops` 提交症状，生产 API 路由返回 SSE 完成事件，页面显示报告和 `windows-local-01` 证据时间线；普通用户未自动展开原始证据，模型调用 0 次，端口已释放。
- 离线回归：Probe/调查相关 192 项通过；后端全量 552 passed、99 deselected；前端 84 passed；前端生产构建通过；Compose 配置检查通过。

## 这批验证证明什么

证明了本机 Probe 能以 LocalService 运行，主动连接网关，返回带 target、时间、来源和 hash 的只读现场证据；证据能进入 MCP、LangGraph 执行器、SQLite 账本和前端时间线；断线、网关重启、过期快照、权限越界和错误证据有明确处理。

## 仍未证明

- 没有真实业务服务、业务日志目录或依赖地址配置，因此本机还不能证明某个真实业务的根因定位。
- `fixed_model_graph_*` 和 preflight 使用替代决策或无模型流程，只证明接线和证据链，不证明真实模型自主归因。
- 最近的真实模型盲测预算已用完，不能在没有新授权的情况下重跑。
- Docker Linux 引擎当前不可用，因此正式 Compose 网关未做本轮运行时验证；本次只用了本机回环临时网关，且没有把它冒充 Docker 验收。
- Termcp 高风险操作审批闭环、正式 AIOps API 进程中途重启恢复、隔离 Windows 故障盲测仍需单独验收。

上面的跨进程待审恢复已经完成；仍未证明“普通调查正在执行中途崩溃后可恢复”。当前正式继续接口只接受 `pending_terminal`，这是有意的安全边界，不能把任意运行中断后的恢复能力混同为已实现。

## 本轮追加（2026-10-18）

- 跨进程恢复记录：`runtime/cross-process-13436f2982fc426982cb3410603d1964/summary.json`。
- 本机只读 Probe 复跑：`scripts/verify_windows_probe_readonly.py`，231 个进程、256 条端口上限、资源四类字段通过；端口截断按设计报告。
- 本地 Windows 手册检索复跑：`runtime/windows-runbook-verification-acc492b40858476abeb1aea40176f93d`，7 类症状首位命中、0 次模型调用；新增 Event Log 和白名单文本日志两类手册。
- Probe 网络烟测复跑：`scripts/verify_probe_local_runtime.py`，LangChain MCP adapter → MCP HTTP → 网关 WebSocket → Probe 通过。
- 全量离线回归：后端 `552 passed, 99 deselected, 1 warning`；前端 `84 passed`，生产构建通过；Compose 静态配置通过。

## 最终收尾复验（2026-10-18）

本节为最新结果；上文测试数量保留为历史记录。本轮没有付费模型调用，没有升级、重启常驻 Probe，也没有停止或修改真实业务服务。

- 修复 `src/probe/windows/config.py` 的文本日志白名单路径比较：Windows 临时目录可能使用 `ADMINI~1` 等 8.3 短名，但打开文件句柄返回长目录名。比较前解析目录的实际路径并按系统大小写规则归一化，避免合法日志被误判越界；保留打开句柄后的复核、链接/reparse point、路径穿越、网络路径和备用数据流拒绝。
- 补充短/长目录别名、大小写及分隔符、配置目录链接、失效白名单条目回归。首轮相关测试 44 项通过；追加边界回归后已纳入最终全量 557 项。
- `scripts/verify_windows_probe_readonly.py` 最终真实采集通过：EventLog 服务 running；CPU、内存、磁盘、网络四类字段；209 个进程；端口达到 256 条上限并明确 `truncated=true`；5 条 Application 事件，无采集错误。进程和端口数量是当时快照，不能视为固定机器状态。
- 文本日志为独立临时目录中的 4 行测试日志；凭据脱敏、证据格式/hash 校验与白名单外路径拒绝均通过。没有读取未配置的真实业务日志，也没有把这次工作区采集冒充已安装 LocalService 的日志权限验收。脚本的越界文件也限制在本次临时目录内，避免覆盖共享临时文件。
- 后端最终离线回归：`557 passed, 99 deselected, 1 warning`，31.51 秒；默认排除的 99 项不计为通过。唯一警告是既有 PyMilvus ORM API 弃用提示。
- 前端：16 个测试文件、84 项通过；Vite 生产构建通过，有现有的大 chunk 提示。
- Compose：`config --quiet` 通过，仅有旧 `version` 字段提示；未运行 Docker 容器。
- 本地 Windows 手册：7 类症状首位命中、模型调用 0；最新记录 `runtime/windows-runbook-verification-eaab946347ea41149496b6be7f2c608a/summary.json`。这仍是本地词法检索，不证明 embedding、重排或真实模型归因。
- 常驻 Probe 核对为 `Running / Auto / NT AUTHORITY\LocalService`；既有浏览器与故障测试专用端口 7263、7938—7941 未发现遗留监听。此次只读脚本没有创建监听端口。
- `git diff --check` 通过，存在工作区原有 LF/CRLF 提示；既存修改和未跟踪文件保留，未提交、推送或部署。

本次原始检查输出保存在 `runtime/windows-final-1792291260683/`：`readonly.json`、`backend-tests.txt`、`frontend-tests.txt`、`frontend-build.txt`、`compose-config.txt`、`runbook-check.txt` 和 `summary.json`。

此前页面、跨进程待审恢复与临时故障链路的独立报告仍作为对应范围的证明；本轮核对了报告，没有重新宣称全部实景重跑。临时故障链使用前台当前账户 Probe；跨进程恢复使用 Termcp authority 和模型测试替身，不能据此宣称真实 Termcp UI 审批或未知故障自主定位通过。

最新修复只在工作区代码验证，尚未同步到已安装服务的受保护运行副本。最终目标还需要：配置真实业务对象并验收 LocalService 读取业务日志的权限；另行授权真实模型盲测；验证真实 Termcp UI 审批；完成正式 Compose 运行验收；普通调查执行中途崩溃恢复仍未证明。

