# Windows Probe 首期运行说明

Probe 只读采集当前 Windows 目标的服务、进程、端口、资源、白名单日志和配置依赖探测。它没有 `exec`、PowerShell、写文件或服务控制协议；高风险动作继续走 Termcp。

1. 在目标机安装 `pywin32` 和项目依赖，创建 `C:\ProgramData\RagAIOpsProbe\config.toml`、`token`、`ca.pem`。配置格式参见 [windows-probe-config.example.toml](windows-probe-config.example.toml)。
2. 用管理员 PowerShell 执行 `python scripts/windows_probe.py validate`，确认目标名、白名单服务和依赖均正确。
3. 安装服务：`python scripts/windows_probe.py install`；启动：`Start-Service RagAIOpsProbe`。安装会将 Python、必要依赖及 Probe 代码复制到 ProgramData 下独立的 `runtime-*` 目录，避免服务从普通用户可修改的开发目录加载代码。服务账户固定为 Windows `LocalService`；管理员和 SYSTEM 可以修改部署文件，LocalService 只能读取配置、token 和运行时，在 spool 子目录拥有写权限。ACL 失败会终止安装，已有服务不会被覆盖。Probe 主动连接网关，不监听本机端口。
4. 本机验证时先设置一个临时 token，并使用本地覆盖文件启动 gateway：

   ```powershell
   $env:PROBE_TOKEN = '只在本机测试使用的随机值'
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.probe-local.yml --profile termcp up -d probe-gateway
   ```

   把配置中的 `gateway_url` 改为 `ws://127.0.0.1:18767/probe/ws`。覆盖文件只绑定回环地址，不对局域网开放；生产环境仍保持默认 Compose 不发布端口，并由 TLS 反向代理提供 `wss://` 入口。AIOps Compose 中设置 `PROBE_ENABLED=true`、`PROBE_TARGET_ID`、`PROBE_TOKEN`，MCP 访问也需要 Probe token。

   不安装服务也可以先跑一次真实进程链路烟测：

   ```powershell
   .\.venv\Scripts\python.exe scripts/verify_probe_local_runtime.py
   ```

   该脚本使用临时 token 和临时配置，启动 gateway 与 Probe 后通过 MCP 读取当前机器 inventory，结束时自动停止两个进程。

   只做当前电脑的本地采集、不连接 gateway 时，可运行：

   ```powershell
   .\.venv\Scripts\python.exe scripts/verify_windows_probe_readonly.py
   ```

   它会读取 EventLog 服务、进程、端口和资源摘要，结束后删除临时配置。

   如果已有 AIOps 容器正在运行，可额外检查容器内的 MCP 工具装配（只执行一次 `docker exec`，不重启容器）：

   ```powershell
   .\.venv\Scripts\python.exe scripts/verify_probe_local_runtime.py --external-gateway --check-container rag_pdf_system
   ```

验收先执行 `validate` 和一次 `run` 只读快照，再连接 WSS 网关。目标注册、在线/离线、快照过期和证据 hash 均可从 AIOps API/证据时间线核对。生产必须使用 WSS 和 CA；本机回环测试才使用 `ws://127.0.0.1`。

基线保留 24 小时；网关启动时清理已过期记录，运行期间每60秒独立清理一次，即使Probe离线也执行。清理失败会记录日志并在下一轮重试，网关退出时取消清理任务；仅删除ProbeSnapshot记录，不删除诊断证据和原文文件。过期记录在查询中立即隐藏，正常运行时数据库行删除最多再等一个清理周期；网关停止期间不清理，下次启动补清理。这里是数据库行删除，不承诺SQLite文件缩小或安全擦除。超过采集时间180秒但尚在保留期内的历史快照仍可查询，`fresh=false`，不能当作当前现场。此项开发代码已通过临时网关验收，尚未部署到常驻网关；结果见 [本机故障验收记录](history/windows-local-fault-verification-20261017.md)。服务安装和基线跨网关进程重启的本机验收见 [2026-10-17 记录](history/windows-probe-local-service-verification-20261017.md)。

`probe_list_evidence` 现在同时返回最近最多 10 条持久化基线摘要，供比较 CPU、内存、磁盘剩余空间和服务状态；每项包含采集时间、新鲜度及进程/端口截断标记。历史项始终为 `historical=true,current=false`，即使采样时间仍在新鲜期，也不能当作刚执行的现场检查。网关重启后可从 SQLite 恢复摘要；数据库读取失败会明确返回 `history_error`。摘要只作调查线索，根因引用仍需通过原始现场证据门槛。

已安装服务可执行 `python scripts/windows_probe.py upgrade` 更新受保护运行副本。该命令校验已注册配置、LocalService 账户和 ProgramData 路径，先部署新副本再切换 Probe 服务；启动失败恢复旧路径，旧目录保留。不会自动扩大业务白名单。

日志只允许本地固定目录，文件名可通配；拒绝目录通配、链接/reparse 路径、备用数据流和网络共享。文本读取通过已打开句柄复核实际路径，只读取尾部最多 16 KB。采集运行在固定入口的独立子进程，超时或停止时结束子进程；该进程不是安全沙箱，权限仍来自 LocalService 和本地白名单。

最新边界修复、两场真实模型失败结果和费用见 [本机模型验收记录](history/windows-probe-model-verification-20261017.md)。

进程 CPU 使用同一批进程的两次读数，中间统一等待 0.1 秒；首次读数只用于建立采样基准，不作为 0% 返回。权限不足或采样期间进程退出时，`cpu_percent=null` 并附 `cpu_error`。`cpu_percent_basis=100_per_logical_core` 表示占满一个逻辑核为 100%，可能超过 100%，与整机 CPU 百分比的口径不同。这个短窗口仍是瞬时观测，不能证明持续高负载；进程列表最多 256 条且可能截断。

`probe_process_snapshot` 支持 `sort_by=memory`（默认）或 `sort_by=cpu`。采集端先枚举可读取进程、完成采样，再按所选指标降序返回最多256条，避免枚举顺序把高占用进程排除在结果之外。返回扫描数、匹配数、跳过数、内存/CPU不可读数；服务配置没有进程名称时返回空结果，不退化为全机查询。`memory_bytes` 为工作集RSS，可能包含共享内存，不能相加当作整机内存或据此确认泄漏。Windows PID 0 带 `cpu_role=idle_time_not_workload`，表示空闲时间，不是负载来源。

调查器与执行器会收到同一目标和操作的最近两份新鲜现场数据对比：保留证据ID、采集时间、截断标记、payload是否相同及资源数值。它只描述返回内容变化，不判断根因，也不保证两个不同时间窗查询的覆盖一致。没有新增固定调查步数或采样次数限制；模型能否正确停止无效重复调查，仍需单独真实验收。

Probe 在生成现场证据时先遮盖常见凭据，再计算 payload hash；传输与后续校验使用同一份脱敏数据。支持凭据字段、Authorization/Cookie 文本、带密码的连接 URL 和完整 PEM 私钥块。文本日志先对本次读取的尾部文本脱敏再拆行。这里的 hash 证明脱敏采集数据一致，不能据此还原含凭据的源文件，也不能保证识别业务自定义格式或被截断的私钥片段；业务接入仍须检查日志格式。

配置依赖的 HTTP 检查保留 4xx/5xx 状态码和最多 1024 字节响应摘要，超出时标记 `truncated=true`；TCP 连通与 HTTP 返回异常分别记录。3xx 只记录响应，不跟随 Location。仍只发送固定 GET，不使用环境代理或自定义请求头。返回 503 只能证明该健康接口返回异常，不能单独证明数据库内部故障。

本机可免费运行 `./.venv/Scripts/python.exe scripts/verify_windows_local_faults.py --evaluation-preflight`：仅启动专用回环测试应用、模拟下游、临时网关和当前账户Probe，验证真实故障采集及固定模型完整图，结束后检查专用进程和端口清理。现在同时检索独立本地手册，并保存规划收到的资料及配置目录；不调用embedding、重排或对话模型，不证明真实模型自主归因。单独验收入口可使用`--local-runbooks docs/fixtures/windows-local-runbooks`，未传`--run-model`始终为免费预检；付费参数不能替代用户授权。详见[本机验收记录](history/windows-local-fault-verification-20261017.md)。

默认本地排查资料新增 `data/runbooks/windows-probe/` 七份手册：服务停止、端口冲突、下游不可达、HTTP 5xx、CPU/内存/磁盘异常、Windows Event Log 和白名单文本日志。它们仅指导取证，不提供本次故障答案；由现有 `retrieve_local` 检索，未写入向量库，也未配置为独立生产 MCP 知识库。Git 和 Docker 忽略规则只放行这七份公开手册，其他本机数据仍排除。容器构建规则已修改，镜像构建尚未运行。

免费复验命令：`./.venv/Scripts/python.exe scripts/verify_windows_runbook_retrieval.py`。它针对真实本地语料检查七类中文症状的首位结果，保存查询、上下文、源文件 hash 和耗时到独立 `runtime/windows-runbook-verification-*`，不调用 embedding、重排或模型。该结果仅证明本地词法检索，不能推导真实模型归因准确率。

已安装的常驻服务可用 `./.venv/Scripts/python.exe scripts/verify_installed_windows_probe.py --executor-batch` 做只读回环验收。脚本先等待 `probe_list_evidence` 报告在线，覆盖网关重启后Probe最长60秒退避；新数据库会再等待一个配置的60秒基线周期，随后要求至少两条持久化基线。它不启动或停止业务服务、不调用模型。2026-10-18在临时回环网关上真实通过7类操作、两条60秒基线和批量执行，记录见[常驻服务验收](history/windows-probe-local-service-verification-20261017.md)。

规划阶段的服务目录和检索经验现在以`investigation_reference_context`独立保存到运行状态，先通过现有脱敏函数，再供执行器与后续调查使用；随checkpoint保存，旧记录缺少该字段仍兼容。参考资料只指导检查，不进入现场证据账本，不能用于根因的现场原文引用。免费固定模型验收已核对资料到达三个环节及SQLite重开后的保留情况；不代表真实模型已正确利用知识库。

调查中途检索的知识片段通过`knowledge_context`从带知识库来源标记的工具记录中单独提取，供下一步执行和调查选择检查。保留来源/页码/chunk，脱敏后每片最多1200字符、最多六条，截断明确标注；它们不进入现场证据索引。免费完整图已验证独立本地BM25经现有RAG函数处理后可沿此路径传递，并在报告中保留引用。2026-10-17补验已使用独立回环MCP服务，替代先前进程内调用；证明本机网络传输和后续上下文衔接，不代表真实向量检索或模型自主归因通过。

`evaluate_windows_probe.py`新增`--knowledge-mcp-url http://127.0.0.1:<port>/mcp`，仅用于独立本机BM25验收服务，不是生产知识库地址配置。免费预检和模型模式共用严格工具装配及调用记录：九个Probe工具加一个`search_knowledge_base`，知识工具不能混入额外操作，也不携带Probe token。知识库编号14为该测试服务的独立资料库；目录向模型说明编号及资料用途。预检主动读取一次手册，标记`autonomously_selected=false`；模型模式只提供工具，不强制检索，调用次数单独记录，不据此认定知识改善归因。`verify_windows_local_faults.py --evaluation-preflight`自动启动该知识服务并传给预检入口；显式付费两场也传同一地址，共用原费用账本，但本轮未运行付费分支。默认免费，仍须新授权才能调用模型。

证据文件新增写入使用`src/probe/storage.py`保护目录与文件权限。Windows仅允许应用进程账户、Administrators、SYSTEM；本机应用账户已确认为Administrator，实际默认证据目录及四个既有文件已收紧且内容hash不变。受限令牌正反对照通过，不等于独立普通用户登录或完整防篡改验证；POSIX权限分支未实际运行，Linux诊断来源的旧query写入路径尚未统一改用此函数。API授权和文件系统权限应分别验收。
