# Windows Probe 本机服务验收（2026-10-17）

本次在用户授权安装后完成。当前电脑只读采集，未制造业务故障，未调用付费模型。安装修改范围为 Probe 专用 ProgramData 配置、运行目录及 Windows 服务注册；Docker Desktop 启动后仅新增/替换 probe-gateway，未接管其他业务进程。

## 实际运行状态

- Windows 服务：`RagAIOpsProbe`，`Running`，`Auto`，账户 `NT AUTHORITY\LocalService`。
- 运行时：`C:\ProgramData\RagAIOpsProbe\runtime-0e9c278a51b6\pythonservice.exe`；代码和依赖为独立副本，不从开发工作树加载。
- 配置和凭据：`C:\ProgramData\RagAIOpsProbe`，仅 Administrators/SYSTEM 可修改，LocalService 读取；spool 单独允许 LocalService 修改。未记录 token 内容。
- 目标：`windows-local-01`。白名单仅配置 EventLog 服务、System channel、Service Control Manager provider；未配置业务文本日志和依赖地址。
- 网关：`docker-probe-gateway-1`，宿主仅回环 `127.0.0.1:18767`，本机 ws；生产 TLS/WSS 未在本轮验收。

## 本轮现场验证

1. 独立运行时导入 SSL、psutil、websockets、服务模块成功；随后注册服务并以 LocalService 启动。
2. 网关收到 hello；通过 LangChain MCP adapter 加载 9 个只读工具。
3. 实际读取 inventory、EventLog 服务（running）、资源、进程、端口、白名单 Event Log。6 类响应均通过 validate_evidence 的目标、采集时间、新鲜度与 payload hash 校验。hash 校验用于完整性，不单独证明采集内容的真实性；来源信任仍依赖受保护的本机配置和认证连接。
4. 进程快照达到 256 行时明确 truncated；事件查询本次指定 5 条，达到上限明确 truncated。
5. 停止/启动 Probe 成功，测得一次停止耗时 6311 ms，重新连接后恢复采集。只控制 Probe 本身，没有停止业务服务。
6. 网关数据库保存了真实基线。停止 Probe，再实际重启网关进程，在 Probe 仍停止时通过 MCP 读取到 01:05:45 UTC 的既有 SQLite 基线，同时状态为 offline。随后重新启动 Probe。
7. 后续 SQLite 核对已有 4 条基线，最新两条采集时间分别为 01:07:01 和 01:08:01 UTC，间隔约 60 秒。

## 本轮修复与测试

- 修复 InstallService 需要完整服务类名字符串的问题；保存服务配置路径。
- 安装 ACL 失败立即报错，拒绝覆盖已有服务；服务运行时部署到独立受保护目录，补齐 Conda OpenSSL DLL。
- 修复 stop event 被自动复位导致停止信号丢失；连接和 hello 设超时，内层循环检查 stop。
- 修复网关数据库导入间接加载整个 LangGraph Agent 的问题；网关镜像增加 loguru，并记录持久化异常。
- 修复历史基线把 24 小时保留期误当作证据新鲜度的问题；超过 180 秒保留但标 stale。
- 相关离线测试 30 passed：collector、protocol、gateway、persistence、evidence、aiops_graph、settings。PyMilvus 既有弃用警告仍存在。
- 网关镜像构建通过，git diff --check 通过（现有 CRLF 提示）。
- 随后完整后端离线回归：375 passed、99 deselected，耗时 21.84 秒；未运行 integration 测试。本轮未修改前端，未重跑前端测试和构建。

## 未验证和边界

- 本轮未验证真实 AIOps 页面时间线、AIOps 应用进程重启恢复、严格的真实模型根因调查。网关跨进程重启测试不能替代这些验收。
- 未配置业务日志/依赖，所以本轮未现场运行文本日志及 DNS/TCP/HTTP 工具。
- 未在当前电脑制造故障；隔离 Windows 主机的 8 类故障盲测仍未完成。
- 未验证生产 TLS/WSS 和整机重启自启；Service Auto 配置不等于实际整机重启验收。
- 本轮结果证明真实只读采集、MCP、服务管理和基线持久化可用，不能据此声称自主找根因的最终目标已全部实现。

## 2026-10-18 本机常驻服务回环复验

先执行 `scripts/verify_installed_windows_probe.py --executor-batch`，当时 Docker Desktop 未运行，18767 没有监听，Probe 工具加载失败；没有重启 Docker 或业务服务。随后使用当前 ProgramData token 和单独临时 SQLite 启动仅绑定 `127.0.0.1:18767` 的网关，等待常驻 LocalService Probe 主动重连。

第一轮临时网关复验的30秒等待不足以覆盖 Probe 的最大60秒退避；脚本改为等待90秒并先检查 `probe_list_evidence.status=online`。重连后批量采集成功，但新数据库只有连接时的一条基线；脚本补为等待一个配置的60秒周期，再要求至少两条基线。以上两次失败均为验收时序/环境问题，未修改常驻服务或降低断言。

最终临时网关回环复验记录为 `runtime/probe-final-4e104a56777740b4b2e898467c112502`，退出码0：

- 真实安装服务 `RagAIOpsProbe` 保持 `Running`、`Automatic`、`LocalService`；网关重连后通过正式 MCP 客户端加载9个只读工具。
- `inventory`、`resources`、两种排序的 `processes`、`ports`、配置服务状态、白名单 Event Log 共7类操作全部通过 target/operation/时间/hash校验；批量执行器顺序和成功状态通过。
- CPU采样返回252和258个可读进程，分别19个非零CPU样本；进程采样间隔0.1秒、排序和字段限制通过。两条持久化基线由真实60秒上报产生，历史摘要可读取。
- 临时网关进程退出后18767释放；没有修改配置、服务、业务进程或防火墙，模型调用0。

本轮只证明常驻 Probe 的真实重连、批量只读采集和周期基线，不证明业务日志/依赖配置或自主根因归因。为此新增脚本等待逻辑的离线回归仍需与后续完整回归一起查看。
