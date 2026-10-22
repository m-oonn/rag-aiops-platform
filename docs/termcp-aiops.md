# AIOps 受控终端诊断

本分支把基于 Termcp v0.2.7 的审批期限修复镜像作为独立 Compose 服务接入 AIOps。AIOps 只拿到网关暴露的 MCP 工具和只读审批查询；Termcp bearer token 由 Termcp 和网关持有，不传给 AIOps。Termcp 自带 Web UI 负责逐条批准或拒绝 shell 写入。

首期边界：单个 `test-target` 测试/预发主机、单个 AIOps 实例、SQLite checkpoint。终端诊断必须由用户勾选启用，或由证据不可用策略显式打开。文件传输、端口转发、SSH profile 管理和任意启动命令均被关闭。

## 配置

复制示例 profile 到运行时数据目录，并填入真实连接信息：

```powershell
New-Item -ItemType Directory -Force data/termcp/ssh_configs/test-target | Out-Null
Copy-Item docker/termcp/ssh_configs/test-target/config.toml.example `
  data/termcp/ssh_configs/test-target/config.toml
```

修改 `config.toml` 中的 `host`、`user`、认证方式和固定 `known_hosts`。`private_key` 填入 PEM/OpenSSH 私钥内容，支持 TOML 多行字符串，不是私钥路径。固定目标实际使用的主机公钥；若目标提供多种主机密钥，需要固定协商使用的密钥。`trust_unknown_host` 保持 `false`，`default_approval` 保持 `true`。使用最小权限测试账户，不配置带命令参数的 `default_shell`。运行配置不要提交仓库。

设置一个只在 Compose 环境使用的随机 `TERMCP_TOKEN`，然后启动 Termcp profile：

```powershell
$env:TERMCP_ENABLED = "true"
$env:TERMCP_TOKEN = "replace-with-a-long-random-token"
docker compose -f docker/docker-compose.yml --profile termcp up -d --build termcp termcp-gateway
```

上述命令只启动终端相关服务。AIOps 应用也需以 `TERMCP_ENABLED=true` 重新创建才能使用 Compose 内网地址；已有应用的部署方式和数据库配置应保持现状。网关不发布宿主机端口，AIOps 只加入网关所在网络，不能直接访问 Termcp 所在网络。Termcp UI 只绑定宿主机 loopback；远程访问需自行配置受控入口。

Termcp UI 在宿主机 `http://127.0.0.1:18765`，AIOps 通过内网网关访问 `/mcp` 和只读审批状态。每个审批请求由网关设置 1800 秒期限；AIOps 续跑前再次核对 request ID、session、shell、命令文本和状态，任何不一致都 fail-closed。

## 审批与恢复

用户在 AIOps 启用终端诊断后，命令文本由 `shell_input` 暂存，`shell_key(enter)` 创建一条待审请求。AIOps 对请求 ID、session、shell、完整命令、来源和期限建立关联，持久暂停。用户在 Termcp UI 批准时，Termcp 已执行命令；返回 AIOps 点“继续诊断”只核验决定并读取输出，不再提交命令。到期前已批准的请求允许用户稍后返回继续；拒绝、取消、到期或关联不一致则停止。

SQLite checkpoint 和运行数据库都必须保留。首期只支持单个应用实例；这里只验收了 AIOps 进程重启，不能推断 Termcp/SSH 重启后仍保留活会话。写入超时或响应丢失会停止诊断，不能自动重试；操作者应在 Termcp 核实尚存的待审请求。

## 固定上游修复

真实隔离 SSH 验收发现原版 0.2.7 的 `Approve()` 不检查 `expires_at`，只有 `Wait()` 处理到期；shell 审批没有等待者，导致到期后仍可批准并执行。AIOps 的核验只能拒绝续跑，无法撤销已执行命令。不得用原版镜像代替本分支修复镜像来满足 30 分钟 fail-closed。

`docker/termcp/patched.Dockerfile` 固定上游提交 `0ee6536a41a7963e94afbbf1b4faa28eba1e2b86`，应用 `approval-expiry.patch`，在审批裁决锁内先检查期限，到期直接转为 `expired` 并拒绝批准。构建会运行上游审批测试和两项新增回归（无等待者到期、并发晚到批准），然后编译镜像 `aiops-termcp:0.2.7-expiry.1`。运行底镜像固定 digest，保留上游 MIT 许可。上游升级时需重新审查补丁并复验，不自动跟随 latest。

## Pi 思路的落点

保留 Python/FastAPI/LangGraph；借鉴 Pi 的小核心与明确扩展边界，把终端权限和协议关联放在工具包装层与网关，把暂停/续跑放在独立图节点，把状态保存到 checkpoint。沿用现有 SSE events 和上下文压缩，没有引入 Pi/Node 运行时或通用 hooks 框架。

## 自主调查实现与部署边界

现场连接与审批分开：Termcp 保留逐条审批通道；自动查询使用独立 SSH key 的 forced command，只运行 `mcp_servers/diagnostic_collector.py`，不能提交任意宿主命令。部署方将采集脚本和 `/etc/aiops-diagnostic.json` 设为 root 所有、诊断账户不可写；key 的 authorized_keys 使用 `restrict,command="/usr/bin/python3 /opt/diagnostic_collector.py"`，禁用转发、PTY 和任意命令。必须使用与 Termcp 审批不同的 key，固定同一个 `test-target` 和主机指纹。采集账户只有已授权日志等读权限，不配置 sudo 或 Docker socket。容器清单等额外现场信息尚未实现，返回不可见时申请审批，不能拿诊断容器状态代替。

采集配置格式：`{"target_id":"test-target","services":{"api":{"entrypoint":"https://test.example","unit":"api.service","process_name":"api","logs":["/var/log/api/service.log"],"dependencies":["cache"]}},"dependencies":{"cache":{"host":"cache.internal","port":6379}}}`。可选固定健康检查 `health: {"scheme":"https","path":"/health"}`，只发 GET、不跟跳转。配置路径和依赖地址由部署方定义，不接受模型自选路径、地址或业务请求。配置服务目录用于定位，再查询目标端进程、端口、systemctl show、资源、日志或依赖 DNS/TCP/健康端点；每份结果包含 target_id、hostname、collected_at。

`data/diagnostic-connection/target.json` 格式：`{"target_id":"test-target","host":"test-host","port":22,"user":"collector","identity_file":"/connection/key","known_hosts":"/connection/known_hosts"}`。将连接 key 和 known_hosts 放在同一只读目录；UID 65532 必须能读取 key，key 只对该 UID 可读。采集缓存 `data/aiops-evidence` 需该 UID 可写，不能放凭据、symlink、socket 或设备。诊断服务写入采集结果，bubblewrap 只读挂载这些结果供自由分析。启用服务需同时配置 DIAGNOSTIC_ENABLED、DIAGNOSTIC_TOKEN；自动 shell 另需 DIAGNOSTIC_EXEC_ENABLED。缺 token 的服务不启动，普通未启用终端的诊断不加载这些工具。

自由 shell 在独立 PID/网络/挂载空间中运行，只能看到运行库、命令、自己的 /proc 和只读 /evidence；输出源标为 diagnostic_analysis，不可作为目标原始证据，防止 echo/脚本捏造现场事实。连接目录、MCP token、应用源码不挂入沙箱。Compose 使用只读根、非 root、cap_drop ALL、no-new-privileges 和拒绝默认的 seccomp 白名单，允许 bubblewrap 所需的 namespace 系统调用；不使用 privileged 或 docker.sock。隔离不可启动时 fail-closed。单命令最长 15 秒，stdout/stderr 各最多保留 16KB，边读取边丢弃额外输出。该边界依赖内核 namespace，不能宣称抵御内核漏洞。

自主调查由 InvestigationStrategy 实现：每次工具检查后，模型依据原始证据索引、此前假设和引用选择下一检查，可以改方向。原计划耗尽/概率高不会自动完成。服务端核对引用 ID 和原文确实在真实工具结果中（语义上的因果关系仍由模型判断，不是确定性证明），替代解释需证据排除或明确无法核查；存在矛盾或未检查方向时继续。没有新检查则报告未定位。正常结论也需要证据门槛。原始输出与调查记忆进入 SQLite，提示保留此前有效引用和最近证据；分段从 checkpoint 下一节点继续，避免 LangGraph 默认递归次数成为隐性总步数。单步骤的工具轮次仍有限，后续调查可另选新检查；未新增总调查预算。自主工具列表禁用接受任意地址/业务请求的旧网站/API 探测工具，依赖探测统一走采集白名单。浏览器断开时取消调查任务并清理本地运行上下文；已发出的远端只读检查可能继续到单命令超时，不能宣称点击取消即撤销已批准的 Termcp 命令。

## 新增验收（2026-10-14）

后端离线回归 344 通过、98 integration 默认排除（此前两项快照测试的 fake graph 不支持新分段参数，已更新测试契约后通过）。包含无来源/伪造引用拒绝、计划耗尽后继续检查、35 步分段不重放、采集目标身份核对、限定服务/依赖、输出保留上限、隔离启动失败降级等。Compose config 和 Python 编译通过；既有 PyMilvus 弃用提醒仍存在。

`scripts/verify_diagnostic_boundary.py` 在一次性 Linux SSH 容器与受限分析容器中执行生产 stdlib 查询/执行函数：现场目录、日志、端口、白名单依赖真实采集通过；未知服务/依赖拒绝；读取连接私钥/越界文件、写回证据、目标网络访问和 Docker socket 不可用；大量输出截断、超时终止通过。测试使用本地 Alpine/Python 3.14 镜像，0 次模型调用，并跳过 MCP transport，不能冒充正式 Python 3.12 镜像验收。正式诊断镜像构建被 Docker Hub 网络超时阻断；镜像代理下载也未完成。新增诊断 MCP 在本机真实客户端检查通过：缺失/错误 token 均 401，认证后工具发现与 fail-closed 返回通过。它与目标端 SSH 的完整容器传输组合尚未验收。真实模型未知答案调查和完整 UI 停止交互仍未验收；不要据此部署到生产。

## 验收记录（2026-10-14）

使用隔离 SSH 容器、非 root 测试账户、固定主机指纹和独立 SQLite；测试规划/重规划使用确定性节点，不调用付费模型。真实 MCP 客户端连接网关，验证了允许工具发现、待审不执行、批准仅执行一次、重复批准被拒绝、AIOps 新进程恢复后读取真实输出、重复续跑被拒绝、拒绝不执行。修复镜像真实到期测试将隔离会话期限缩短至 1 秒；到期后批准被拒绝，目标文件不存在；另核对正式请求期限为 1800000 毫秒。

最终离线回归：后端 319 项通过、98 项 integration 被默认排除；前端 82 项通过，Vite 构建通过；终端专项 22 项通过。已有 PyMilvus 弃用和前端包体积警告仍存在。Compose 配置和 diff 空白检查通过，修复镜像构建及其中的上游审批测试通过。

尚未验证浏览器中的 Termcp 审批交互、正式预发目标及整套 Compose 应用部署。测试网关使用本机 Python；正式网关镜像构建尝试被 Docker Hub 认证服务连接超时阻断，尚未通过容器构建验收。离线测试不代表这些外部依赖已验收。

## 真实模型调查验收（2026-10-14）

按用户授权，使用隔离 SSH 容器、未知答案症状和当前配置的 `deepseek-v4-flash` 做了真实模型调查，预算上限为 4 个场景、¥5。实际发出并返回 56 次请求；按返回 token 和 DeepSeek Flash 峰值价估算约 ¥1.03。脚本的保守预留额达到 ¥4.97 后停止后续请求，没有继续消耗额度。原始记录保存在 `data/autonomous-model-evaluation/c80f21e3e6e6463280a8199400922880/`，其中 `results.json` 是调查轨迹，`cost.json` 是逐请求账本。

已启动 3 个场景：`healthy`、`dependency_stopped`、`misconfigured_dependency`。应用停止场景因预算保护未启动，因此这不是完整的四场景验收。healthy 场景中模型自主选择健康检查、日志、进程、端口、资源和依赖探测；它发现服务自报正常，但没有 SQL 级证据和端口归属证据，所以按证据门槛报告“未定位”。数据库停止场景中模型根据 503、`ConnectionRefusedError`、数据库进程缺失和 15432 无监听，把方向转到数据库故障，并继续检查替代解释；由于没有配置/容器/近期变更证据，最终仍报告“未定位根因”，没有硬猜。这个结果证明调查循环、换方向和证据门控在工作，也暴露出当前测试采集面还不足以完成完整根因闭环。

脚本现在会把计划、已尝试场景、预算停止原因和实际费用写入 `evaluation_summary.json`。后续需要重新授权模型费用后，才能补跑配置错误和应用停止场景；在此之前不应宣称真实模型调查已经全部通过。
