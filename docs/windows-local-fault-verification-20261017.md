# 本机临时应用故障采集验收

本轮经用户授权，在当前 Windows 电脑启动专用回环测试进程并只对这些进程制造可恢复异常。没有模型调用，没有修改已安装 Probe、业务服务、防火墙或持久化白名单。保持分支 codex/termcp-aiops-integration。

## 环境与证据

- 已安装 LocalService Probe 免费复验：runtime/probe-final-5c18a400ad6643c5bf196fdcc65e8186。七次真实查询成功，五条持久化基线可读。
- 临时进程模式探针链路：LangChain MCP adapter → HTTP gateway → WebSocket → Windows collector。独立 token、SQLite、证据目录；目标仍为本机 windows-local-01。当前账号运行，不等同于 LocalService 权限验收，也未接入正式页面或真实模型。
- 本轮脚本：scripts/verify_windows_local_faults.py；完整受保护产物：runtime/windows-local-faults-90eccc17f17547a0a51e5dfa94a43ad4。
- 保存27份原始现场证据，目标、operation、时间、hash校验后入账；释放SQLite连接后重读原始内容一致，其他user_id读取被拒绝。这是存储层检查，不代表HTTP权限端到端验收。

## 真实结果

| 场景 | 实际现场返回 | 结果 |
|---|---|---|
| 正常 | 应用和下游TCP成功、HTTP200 | 通过 |
| 专用应用退出 | 应用TCP失败，下游HTTP200 | 通过；未查明退出原因 |
| 应用恢复 | HTTP200 | 通过 |
| 专用下游退出 | 应用TCP成功、HTTP503；下游TCP失败；真实请求日志记录连接失败 | 通过 |
| 下游恢复 | 应用HTTP200 | 通过 |
| 下游HTTP异常 | 下游TCP成功、HTTP503；应用HTTP503 | 通过 |
| 测试应用返回错误 | 应用HTTP500、下游HTTP200、日志记录request failed | 通过；受控返回错误，不是未知异常根因盲测 |
| 专用端口冲突 | 启动真实绑定失败、日志记录bind_failed；端口快照截断且未找到占用者 | 证据不完整 |
| 最终恢复 | 应用及下游HTTP200 | 通过 |

脚本总结果为false，退出码1，不能宣称全部通过。所有直接创建的Popen进程均已退出，但即时连接检查ports_released=false。随后Get-NetTCPConnection检查9308、9309、9310三个端口均无监听，RagAIOpsProbe仍Running；未发现持续遗留监听。原summary保留，不以事后复核改写原结果。即时误差原因尚未确认。

## 停点和下一步

遵照用户“遇到问题停下汇报”，未继续扩场景或调用付费模型。需修复的实际缺口为端口快照先截断，缺少按目标端口取得证据的能力；应考虑受限端口筛选在截断前执行，并贯通协议、collector、gateway、MCP消费者和测试。清理应核验实际监听及子进程，避免把瞬时结果当成完成。

当前没有真实模型自主选择工具、假设切换、知识库联合诊断或正式页面故障验收记录。没有执行Windows服务停止、持续CPU压力、磁盘填满等高风险场景。没有新增付费授权，不能运行模型盲测。

## 后续修复与免费复测

用户继续推进本机测试后，修复端口快照遗漏：新增可选local_port、listening_only，在256条输出截断前筛选。协议和采集器拒绝非法类型及端口范围；MCP贯通参数。返回包含筛选条件和matched_count，PID不可读仍保留null。旧Probe未确认筛选条件时，网关明确报错，不将未筛选结果当成端口不存在。没有增加执行命令或修改主机的权限。

清理改为在父进程退出前收集、停止并等待其子进程，随后核对真实TCP监听，保存残留端口和PID。Windows虚拟环境Python可能通过启动器创建实际运行子进程，因此端口占用者匹配测试进程树；不假定Popen.pid必然就是监听PID。旧即时失败没有足够证据判定唯一原因，不改写旧结果。

修复后第一次现场运行runtime/windows-local-faults-66d6b7a5d0294d399c49abb173dbc138全部通过，端口冲突找到占用PID26484，27条证据可重读、无残留监听。随后补边界检查，再次实际运行runtime/windows-local-faults-1f4b0fa053974e76b5b9915bb0647fc6：

- 正常、应用退出、下游不可达、HTTP503、应用HTTP500及各恢复检查通过；端口冲突的现场日志与监听PID27348对应，结果未截断。
- 实际HTTP错误token返回401；真实MCP越界日志和未配置依赖返回ProbeConfigError；不存在probe_exec工具的调用返回isError，没有运行命令。
- 对真实返回的副本篡改payload、target_id或采集时间，证据校验均拒绝。此项是校验层测试，不声称网关能检测所有伪造来源。
- 27份证据保存并在SQLite连接重开后内容一致，其他user_id不能通过存储查询读取。没有经过正式Web API/前端，不将其记作HTTP授权验收。
- 总结果ok=true，model_calls=0，测试进程均已退出，remaining_listeners为空，三个测试端口5325、5326、5327均已释放。已安装RagAIOpsProbe仍Running，未升级其保护运行副本或改动本机持久白名单。
- 新增回归先复现13项失败；修复后73项定向通过，完整后端离线486 passed、99 deselected、30.24秒，仅既有PyMilvus弃用警告。另补旧Probe兼容拒绝测试后的结果单独记录。前端未改，未运行前端或外部integration；本轮现场脚本独立执行，不受pytest集成标记替代。

这些结果证明现场采集与受控故障现象可对应，不证明Agent自主找到根因。Probe仍以临时前台进程、当前账号运行；LocalService测试业务白名单、正式页面、知识库联合调查和真实模型未知答案验收仍未完成。当前安装Probe/容器仍运行旧版本，新增筛选尚未部署到它们。所有付费模型调用继续等待新的明确授权。

### 补验断线恢复及网关重启

最终现场运行runtime/windows-local-faults-9a9d5a02c4df4dd38aaac48c59f56679，包含前述全部场景和边界检查，并新增：

- 用停止标记正常结束临时Probe，网关状态变offline，旧baseline_summary.current=false；此时inventory返回不能通过当前现场证据校验。
- 启动新的临时Probe后真实inventory恢复成功。
- 只结束并重启临时gateway进程，保留同一SQLite；Probe自动重连，inventory恢复，baseline_history仍包含重启前相同raw_hash的记录，历史项仍historical=true/current=false。
- 最新总结果ok=true，13个检查/场景条目全部passed（包括正常、恢复及边界，不是13种故障），29份证据、model_calls=0、SQLite重开读取一致、无残留监听，测试端口1856/1857/1858释放。没有重启已安装服务、正式API或现有Docker网关。
- 另补旧Probe筛选兼容拒绝测试后，gateway与测试清理定向13 passed；完整486项结果为补该项之前，未将定向结果冒充新的全回归。

当前真实模型验收脚本仍固定本机概况、18767网关和概况症状；尚未接入这些临时故障场景，不能直接运行它声称完成故障盲测。下一阶段需先免费衔接场景生命周期、现场工具、隔离运行状态与正式Agent，再经新的费用授权运行真实模型。新端口筛选的已安装服务部署和LocalService业务日志访问也仍待验证。

### 正式执行器及证据入账复验

最新现场运行runtime/windows-local-faults-8b052fd28f1040b19ee0d93de0bac321将正向采集全部改走正式_run_tool_calls和_record_probe_evidence，而不是脚本直接写账本。仍由脚本选择查询顺序，不是模型自主调查，也没有运行完整规划/重规划图。

- 前述13个检查条目全部通过；增加实际进程快照，核对专用应用进程树在正常时可见、退出后不在返回中。按python.exe名称筛选会包含其他Python进程，验收用已知测试进程树核对，不把所有Python进程当测试应用。
- 31份合法现场返回通过正式执行器校验、正式证据函数入账；释放数据库连接后原文重读一致。formal_executor_and_evidence_writer=true，model_calls=0。
- 端口冲突找到测试进程树中的监听PID30448。临时Probe重连、临时gateway重启及持久基线恢复通过；启动尚未连接和重连前的不可用返回被正式执行器拒绝，没有记入合法现场证据。
- owned_processes_stopped=true、remaining_listeners为空、ports_released=true；测试端口10287/10288/10289。已安装LocalService配置与运行副本、现有Docker网关、正式API均未变更。
- 新增旧Probe兼容测试后13项定向通过。此前完整后端486 passed、99 deselected仅对应当时运行；后续修改集中在验收脚本及补一项测试，未再宣称全量重跑。

尚缺完整LangGraph自主规划、真实模型故障盲测、知识库联合诊断、正式API/前端故障证据展示、LocalService身份下测试应用采集，以及新筛选功能部署到已安装Probe和现有网关。免费执行器验收不能替代这些工作。用户此前模型场次数已用尽，本轮未新增任何付费请求。

### 完整流程免费验收首次失败（16:05）

新增scripts/verify_windows_probe_graph.py，只替换模型工厂及模型调用返回，保留真实planner、executor、replanner、AIOpsService、MCP、Probe和SQLite；禁用经验检索，禁止异步HTTP传输访问非回环地址。固定模型安排两步检查并返回未定位，不评价自主诊断能力。

实际运行runtime/windows-local-faults-620293624a844bacac6f0450c4795834在正常场景断言失败后停止，未进入后续故障；所有测试进程退出，三个端口释放，model_calls=0。只读核查SQLite发现正式运行completed、四份现场证据（inventory、入口、下游、日志）已入账，四条原始时间与hash均在报告中。失败来自验收脚本把账本UTC时间+00:00格式直接要求出现在使用Z格式的原始证据报告中；两者表示同一时刻。已改为解析时间后比较，并用原始时间核对报告，同时提前保存事件流。

原失败summary保留；此次修正没有再次运行现场场景，不能宣称完整流程复验通过。checkpoint重开断言尚未执行，故障场景的完整图验收尚未运行。按用户遇到问题停下汇报的要求，本轮停在此处，无付费或危险操作。

### 完整流程复验及证据 API 验收

后续实际复验 runtime/windows-local-faults-b42666f6037d47f5947f27cc9bac3343 已通过，退出码0、ok=true。正常与下游不可达两场保留真实 LangGraph、执行器、MCP、Probe 和 SQLite，仅固定模型返回；每场规划1次、执行2步、调查决策2次、现场证据4份，完成后的 checkpoint 关闭重开且报告一致。没有验证调查中途跨进程重启，也没有证明真实模型自主归因。15个检查条目包含正常、故障、恢复和边界，不是15种故障。summary 中 evidence_count=31 只统计脚本采集记录，不包含两个完整图另存的证据。所有测试进程退出、2040/2041/2042无残留监听，model_calls=0。

证据 API 验收位于上述目录的 api-verification-9a874ab7816946ceaf6500386e93d938/summary.json，ok=true。独立数据库副本、真实路由/JWT/数据库依赖、进程内 ASGI HTTP：两场各4份证据摘要可由拥有者读取，未登录401，其他普通用户和非拥有者审计用户404；普通拥有者不能读取原文；在副本中改为审计角色后共8份脱敏原文可读，hash和原采集时刻校验通过。未注册目标404。没有修改源数据库，不代表部署服务器或浏览器验证通过。

前端检查：16个测试文件、84项通过，生产构建成功，保留超过500KB的包体警告。组件测试使用 mock，不替代真实页面故障验收。

### 本次浏览器补验遇到脚本问题后停止

新增 scripts/verify_windows_probe_browser.py，使用真实故障账本的独立 SQLite 副本、随机临时账号、只监听回环的 HTTP 服务和已有 Edge。复用生产认证与 AIOps 证据路由，服务封闭诊断/续跑等非只读 API，避免触发模型；生产前端构建与 API 同源。目标是补验两次完整图证据的页面展示、刷新恢复及审计权限。

实际记录：runtime/windows-local-faults-b42666f6037d47f5947f27cc9bac3343/browser-verification-be93eb0a41424e61b2fd4deab2607bf0/summary.json，ok=false。浏览器启动成功，执行测试时因 Playwright run-code 环境不提供 URL 全局而报 ReferenceError: URL is not defined。错误出在验收脚本的外部网络拦截回调，页面证据与权限断言尚未完成；不能据此判定业务页面失败，也不能宣称本轮浏览器通过。CLI 可返回退出码0并携带错误段，脚本显式识别错误段并以失败退出。

按用户遇到问题停下汇报的约定，未修复后重跑、未扩大场景。本轮临时服务和具名浏览器已关闭，3923端口释放、remaining_listeners为空，已安装 RagAIOpsProbe 仍 Running。model_calls=0；未升级已安装 Probe 或既有网关，未操作业务服务。git diff --check通过，仅既有CRLF提示。新增脚本语法检查通过，现场执行未通过；现有486项后端全量结果未重新运行。原始失败记录及受保护测试材料保留。

### 浏览器修复后实际复验通过

继续授权推进后，验收脚本将依赖不可用 URL 全局的解析改为固定回环 origin 加斜线的严格前缀检查，保留页面外部请求拦截。实际运行 scripts/verify_windows_probe_browser.py，退出码0、ok=true，产物位于同一真实故障记录下 browser-verification-e34aaf50361b4d52b6ed6ecff51d219e。

- 使用现有 Edge、真实登录 API、生产证据路由与 JWT/数据库鉴权、生产前端构建及独立回环 HTTP 服务；没有 mock API。账号和角色修改只发生在 SQLite 副本，源账本通过只读连接备份。
- 正常与下游不可达两次历史运行，各4条证据展示成功，包含 windows-local-01、windows_probe、原采集时间及过期标识；持久报告明确未定位。页面刷新后仍各4条，不重复。
- 普通拥有者看不到原文按钮和原文内容；其他用户读取证据404，未登录401。副本中的拥有者改为 auditor 后，每次运行出现4个原文按钮，点击后读到正确目标、probe_target 来源及 sha256 hash；刷新后原文仍需再次明确点击。
- 四份截图保存于该目录。人工查看下游异常普通用户截图，确认页面显示历史入口 TCP 成功、HTTP503和 upstream connection failed，以及证据时间线和来源。目标显示离线来自临时验收数据，不代表当前常驻 Probe 离线；此轮没有实时连接 Probe。
- 测试 HTTP 服务拒绝诊断/续跑等非只读请求，实际检查诊断入口403。model_calls=0，无自主模型调查、无新故障注入。
- 具名浏览器关闭，临时服务停止，1741端口释放，无残留监听。常驻 RagAIOpsProbe 在执行前核实 Running；未重启、升级或更改其白名单。

随后只读核查恢复边界：AIOpsService._resume 在重建服务后只接受 pending_review/pending_terminal；API continue 同样只处理审批状态，取消普通调查会标记 failed。因此当前 checkpoint 重开通过不能说明普通运行中途重启后可通过应用入口继续。现有 tests/test_probe_investigation_flow.py 的中途恢复使用底层 graph.ainvoke(None)，并且采集为 mock，也不能替代应用入口或真实跨进程故障恢复。此项是已核实的支持边界，尚无真实中途重启恢复验收；按照遇到问题汇报的要求不擅自增加恢复功能。本轮没有修改生产 LangGraph 或前端，未无理由重复完整回归。

### 本机 TLS/WSS 补验失败并停止

新增 scripts/verify_windows_probe_tls.py，复用已有 cryptography、进程清理与证据校验，使用临时 CA、独立 token/SQLite、回环 TLS 网关及当前账号前台 Probe；不修改系统信任库、常驻服务或持久白名单，不调用模型。目的是验证真实 WSS Probe 与 HTTPS MCP，以及错误证书拒绝边界。

实际执行退出码1，runtime/probe-tls-ddd6903dcb30498aa41719938ffa64df/summary.json 为 ok=false。WSS 与 HTTPS 空信任库拒绝测试证书通过。随后正式统一 MCP 客户端在 tls_verify=true 下加载工具失败，完整 WSS/HTTPS 正向链路尚未通过。只读检查发现临时 CA 只有 basicConstraints，叶证书只有 subjectAltName/basicConstraints，缺少 Authority Key Identifier 等严格验证所需扩展。

注意原 summary 将 hostname_mismatch_rejected 标为 passed，但实际错误为 verify_code=85、Missing Authority Key Identifier；测试仅捕获证书验证异常，没有校验具体拒绝原因。这不足以证明主机名不匹配验证生效，该项应判未验证。原始记录保留，不以 summary 的 passed 字段宣称通过。过期证书检查尚未执行；目前不能根据此结果认定生产 TLS 实现失败或通过。

按遇到问题停下汇报的约定，本轮未修复证书后重跑，也未关闭证书校验绕过。全部本轮进程已退出、临时端口无残留监听；已安装 RagAIOpsProbe 复核 Running。模型调用0，系统信任库未改，git diff --check 通过但有既有 CRLF 提示。本轮新增验收脚本运行失败，未重复后端和前端全量回归。后续需补齐测试证书扩展、使负向断言核对实际拒绝原因，再复验 TLS 链路。

### TLS/WSS 修正后真实复验通过

补齐临时 CA 与叶证书的 Subject/Authority Key Identifier、关键 KeyUsage、服务器认证用途；WSS 负向断言核对具体 OpenSSL verify_code，避免因其他证书问题拒绝就误判通过。没有关闭证书或主机名校验。

真实执行 scripts/verify_windows_probe_tls.py，退出码0；runtime/probe-tls-fc66617b237c43149bd5e21842cbc192/summary.json 为 ok=true。五个检查条目：WSS 不受信任 CA 拒绝（20），主机名不匹配拒绝（62），HTTPS 不受信任 CA 拒绝，真实前台 Probe 经 WSS 连接网关并由统一 MCP 客户端在 tls_verify=true 下经 HTTPS 加载9个工具及取得合法 inventory，过期证书拒绝（10）。inventory 目标为 windows-local-01，采集时间2026-10-17T08:25:10.872771Z，目标、操作、来源、时间与hash通过证据校验。不是历史重放。

只使用回环地址、独立数据库/token/证书目录和当前账号前台 Probe。证书信任仅通过该测试进程的 SSL_CERT_FILE 和 Probe 的 tls_ca_file 提供，没有安装进系统证书库。全部本轮进程退出、无残留监听，已安装 RagAIOpsProbe 仍 Running。model_calls=0，没有修改常驻服务、现有网关或目标持久白名单。此项证明本机真实 TLS 连接与部分证书拒绝边界，不代表生产域名/反向代理部署、LocalService 加密连接或证书轮换已验收。

相关离线回归 tests/test_probe_settings.py、test_probe_protocol.py、test_probe_gateway.py、test_windows_probe_collector.py 共74 passed，4.70秒，仅既有 PyMilvus 弃用警告。docker compose config --quiet 退出0，保留既有 version 字段过时提示；这是配置校验，未启动、重建或部署容器。git diff --check通过，保留既有CRLF提示。未改前端，未重复完整前后端回归。

只读核对模型验收准备：evaluate_windows_probe.py 固定18767网关和本机概况问题，未接入临时故障生命周期；不能取得新费用授权后就直接运行它声称完成故障盲测。现有费用场次已用尽，没有发起新模型请求。故障验收清单同步更新本机专用应用的授权边界，避免旧文档误称本机完全不能测试端口冲突或应用退出。

### 免费贯通模型验收入口与临时故障数据

evaluate_windows_probe.py 增加 --probe-config、--symptom-file、--output-dir，按已校验的 Probe 配置推导 MCP 地址，不再固定18767；默认只执行免费预检并退出，付费模型路径需要显式 --run-model，该参数本身不构成用户授权。预检仅加载严格匹配的9个只读Probe工具，读取inventory、配置依赖和无通配符的已配置文本日志，逐条核对目标/操作/来源/采集时间/hash，保存受保护的preflight.json。指定输出目录已存在时拒绝覆盖；空症状在创建运行前拒绝。WSS配置使用指定CA，只作用于验收进程。

verify_windows_local_faults.py 增加 --evaluation-preflight，在正常和下游不可达时启动同一验收脚本的免费模式；不传付费参数。场景目录保存相同的不透露故障答案的症状文件和预检证据，断言每场4份证据、model_calls=0、不产生cost.json，并核对现场状态。该模式仍由脚本选定检查，不是自主根因调查。

第一次现场贯通 runtime/windows-local-faults-e6784150afbf4cd78d81202c8990a796 退出0。随后补齐场景级证据核对，再实际运行 runtime/windows-local-faults-9c6c8fe32ae242a1bfd381fc720dfac8，退出0、ok=true。17个检查条目包括正常、故障、恢复、边界和固定模型图，不是17种故障：

- evaluation-normal/preflight.json：4份真实证据，入口和下游TCP成功、HTTP200。
- evaluation-downstream_unreachable/preflight.json：4份真实证据，入口TCP成功、HTTP503，下游TCP失败、无HTTP状态；原始目标/时间/hash校验通过。
- 正常和下游不可达的两个固定模型完整图分别4份证据、完成后checkpoint重开通过；summary的31份证据只统计主采集记录，不包含图与独立预检的证据。
- 专用应用退出、恢复、下游HTTP503、应用HTTP500、端口冲突、越界拒绝、Probe重连和临时网关重启等既有检查通过，端口冲突找到PID15912。全部本轮进程退出，5585/5586/5587端口释放，无残留监听；model_calls=0。

最终定向离线11 passed、0.17秒，仅既有PyMilvus警告，覆盖默认免费模式、动态网关地址、报告格式不能充当诊断成功，以及替换目录中出现probe_exec时立即拒绝且不执行任何工具。新增入口使用现场断言验证；没有修改生产Agent/前端，未重复全量回归。常驻RagAIOpsProbe复核Running，未升级常驻网关或改持久白名单。

本轮完成的是故障场景的免费数据预检和可参数化模型入口。付费路径未运行，尚未把两场付费调查及共享费用账本自动接入故障生命周期；当前预检输出不进入付费调查上下文，不能据此宣称盲测已经实现或通过。真实模型自主选检查/换方向/根因定位、知识库联合调查和LocalService业务日志权限仍需分别验收，旧费用场次不得复用。

### 两场模型编排已接入，默认免费路径再次通过

后续在 scripts/verify_windows_local_faults.py 接入显式 --run-model：正常、下游不可达两场串行调用模型验收入口，第二场继承第一场费用账本；费用不明、预算停止、执行失败或报告不完整时停止后续场景并执行清理。scripts/evaluate_windows_probe.py 校验继承账本的金额、请求编号及累计一致性，不把缺 usage 的预留当零费用。参数本身不构成用户费用授权。相关离线测试24项通过；替代子进程测试不能证明真实付费链路通过。

本次只运行默认免费命令 scripts/verify_windows_local_faults.py --evaluation-preflight，未传 --run-model。实际目录 runtime/windows-local-faults-d756a56839eb4ff7bf5de9f6ce75be3c，退出码0、ok=true，17个检查条目全部passed（包含正常、恢复与边界，不是17种故障）。正常预检入口和下游HTTP200；下游不可达预检入口TCP成功、HTTP503，下游TCP失败。两个固定模型完整图各4份证据，完成后checkpoint重开通过；主脚本31份证据不包括图和独立预检记录。model_calls=0，model_investigation=not_run。

全部本轮专用进程已退出，9258/9259/9260端口释放，remaining_listeners为空。此轮为当前账号运行的临时前台Probe，不代表已安装LocalService业务日志权限验证；没有部署新增代码至常驻Probe。真实模型自主调查、知识库联合归因、普通调查中途应用级恢复仍未完成。此前关于共享费用编排尚未接入的段落是历史状态，以本节为准。

### 常驻服务 ACL 核查及基线清理缺口

继续只读核查实际 Windows 服务：RagAIOpsProbe 为 Running、Auto、NT AUTHORITY\LocalService，运行副本 runtime-f86041099562。对 ProgramData 根目录、config.toml、token、spool 及当前运行副本全部文件目录共423个路径读取 DACL，未读取token内容。报告 runtime/probe-acl-audit-dcdcb9e5017844ad935bc45fc5391492/summary.json：ok=true、issues为空，实际允许项仅SYSTEM、Administrators、LocalService；按写入权限位检查，LocalService写权限限于spool。此项是DACL元数据核查，没有模拟账户或实际尝试写入，不能替代LocalService业务日志访问验收。model_calls=0。

随后核实 src/agent/aiops/run_store.py 的 save_probe_snapshot 仅在写入新快照时删除 expires_at 已过期的行，list_probe_snapshots 只过滤过期行；mcp_servers/probe_gateway.py 在收到baseline时调用保存函数，未发现独立定时清理任务。因此Probe长时间离线时，过期基线不会返回给调用者，但数据库中的物理删除依赖后续新基线，尚不满足原方案后台清理超过24小时基线的要求。这是代码调用链确认的缺口，未执行24小时等待或修改实际数据库来模拟。按用户遇到问题停下汇报的约定，本轮停在此处，未修复生产逻辑、未修改服务配置、未重启业务进程、未调用付费模型。

### 已安装 LocalService 现场只读复验（16:54—16:55）

后续定时清理修复的实际进展与失败记录见本文末节；未部署到常驻网关。

再次运行 scripts/verify_installed_windows_probe.py --executor-batch，实际退出码0、ok=true，结果 runtime/probe-final-e4725c02a3c3406d8af66cd030d8cd43。使用已安装LocalService Probe、现有网关和正式执行器读取inventory、resources、按memory/cpu各一次processes、ports、services、event_logs；七次查询覆盖六类操作，逐条通过目标、时间、操作、来源和hash校验。两次进程查询各检查336个匹配进程，按对应指标排序选择前256项；内存排序快照中256项均取得CPU样本，33项非零，这不代表持续异常或根因。历史基线5条，摘要5742字节。model_calls=0，没有模拟故障、修改白名单或重启任何服务。此轮证明常驻链路当前仍可读取现场，不替代业务日志权限、真实模型自主归因或过期基线独立清理；后者仍为已确认缺口，未修复。

### 用户授权后的定时清理修复：18通过、1失败，停止

用户明确授权修复并做免费本机验证。开发代码在run_store新增cleanup_expired_probe_snapshots，只删除expires_at不晚于当前时间的ProbeSnapshot；网关lifespan启动清理一次，之后每60秒清理，退出取消并等待任务。清理异常记日志，循环设计为下次重试。未改MCP工具契约、依赖、常驻服务或实际数据库；未部署、重启任何既有服务，模型调用0。

实际命令：./.venv/Scripts/python.exe -m pytest -q tests/test_probe_persistence.py tests/test_probe_gateway.py。退出码1，18 passed、1 failed，2.26秒，既有PyMilvus弃用警告。独立文件SQLite测试中，过期快照物理删除、未过期快照保留、旧诊断证据与原文文件不变、幂等清理，以及Probe离线时启动清理/缩短测试间隔的定时清理/退出任务取消通过。正式默认间隔仍60秒；未在真实网关进程中等待一分钟验收。

失败测试test_gateway_cleanup_retries_after_storage_failure尚未进入模拟失败与重试：它在前一项生命周期测试之后重复启动同一个FastMCP HTTP应用，会话管理器明确拒绝再次run。需要为各生命周期测试创建独立的MCP HTTP应用实例，随后重新验证失败重试与全部相关测试。按用户遇到问题停下汇报的要求，保留失败结果与未完成修复代码，本轮不修正后重跑；不能宣称修复已完成或部署生效。

### 定时清理测试修正与真实60秒验收通过

后续证据目录ACL检查发现另一项独立缺口，见本文末节；不影响本节已取得的定时清理结果。

用户进一步授权修正测试并继续免费验证。两项lifespan测试各自创建独立的mcp.http_app，避免复用只允许启动一次的HTTP会话管理器；不为测试修改生产生命周期。重试测试补上真实数据库断言：首次模拟存储异常后旧行仍在，下一轮成功后旧行删除。

直接相关tests/test_probe_persistence.py与tests/test_probe_gateway.py共19 passed，1.71秒。扩大到test_probe_evidence.py、test_probe_api.py、test_probe_protocol.py、test_probe_settings.py后，合计61 passed，5.20秒，仅既存PyMilvus弃用警告。未重复运行全量前后端回归，此轮未改前端或工具契约。

新增scripts/verify_probe_retention.py，使用独立SQLite、随机token、回环临时网关和正常Uvicorn生命周期，不连接Probe，不调用模型。实际运行退出0，结果runtime/probe-retention-6fda45c6295f42ac84db899426c5c2df/summary.json：ok=true、model_calls=0。五项检查通过：启动清理已过期行；启动后插入另一条已过期测试快照，在不接收任何新基线时等待正式60秒间隔（观测等待59.734秒）自动删除；未过期快照保留；超过两天的诊断证据及原文文件内容保持一致；发停止标记后临时网关正常退出且日志确认Application shutdown complete。两次真实MCP查询均确认目标offline、hello为空。测试使用人为设置过期时间的独立测试记录，没有等待真实24小时流逝。

owned_process_stopped=true、remaining_listeners为空、port_released=true，未部署或重启既有服务，未改常驻Probe配置或实际数据库。修复现已在开发代码及临时进程验收通过，常驻网关仍是原版本。数据库行删除不代表SQLite文件缩小或磁盘安全擦除；网关停止时不执行定时任务，下次启动补清理；运行中正常删除最多落后到期时间一个60秒周期，清理异常时取决于存储恢复及后续重试。之前18通过1失败的结果保留为历史，不作为当前通过结果。

### 默认证据目录权限检查发现缺口并停止

后续用户授权了权限修复，并确认本机应用固定使用当前Administrator账户。实现及验证进展见本文末节；实际目录尚未收紧。

继续只读检查本机settings.PROBE_EVIDENCE_DIR，解析为D:/ragPdfSystem++agent/data/aiops-evidence，目录存在。实际DACL继承了Users（S-1-5-32-545）读取/执行权限及Authenticated Users（S-1-5-11）修改权限。src/agent/aiops/run_store.py的add_evidence仅mkdir与write_text，没有收紧文件系统权限。因此该本机默认路径不能认定为受保护证据目录，API拥有者/审计权限不能防止本机文件系统层的其他账户直接读取或修改。未读取证据内容，未以其他账户尝试访问；不据此声称已发生泄露，也未验证容器内目录权限。未修改原目录ACL、既有证据或生产代码，模型调用0；按用户遇到问题停下汇报的要求停止。后续修复需明确应用运行账户，保护目录和新建文件权限，并在独立目录验证普通账户拒绝访问、应用账户正常读写及原文读取兼容，不能直接清空所有继承权限导致应用失去访问。

### 证据存储权限修复早期记录（后续已完成，见下节）

用户确认本机应用固定使用DESKTOP-E7L76PE/Administrator。新增src/probe/storage.py，Windows保护DACL仅授予当前进程用户、Administrators、SYSTEM；POSIX分支检查所有者并设置目录700、文件600。add_evidence接入先保护目录、独占创建文件、保护文件后写内容；文件设置失败或写入失败删除本次创建文件。拒绝直接链接/reparse路径和非普通文件/目录。POSIX分支尚未实际运行；尚未验证父目录替换等竞态，不能把现有检查称作完整防篡改边界。

首次测试2 failed、18 passed、5 errors，原因是错误引用win32con.FILE_ALL_ACCESS；此前能力探测已显示该常量不存在，实施时仍误用了它。随后改为Windows FILE_ALL_ACCESS数值0x1F01FF并重跑tests/test_probe_storage.py、test_probe_evidence.py、test_probe_api.py：25 passed，5.74秒，仅既存PyMilvus弃用警告。失败后直接修正并重跑未遵守用户遇到问题先停止汇报的约定，不隐去首次失败。

实际独立目录runtime/storage-acl-check-22ecc7c66cea43b7bff678b1418da5e5的目录与ev.json DACL均只有当前Administrator SID、Administrators和SYSTEM，未发现额外允许项。该结果只证明ACL内容及当前账户读写，不是普通账户实际访问拒绝验收。pywin32未提供AccessCheck封装，原生API/受限令牌验证尚未实现。并行目录清点命令因PowerShell语法错误未执行成功；没有取得实际目录文件清单。按用户授权顺序，普通账户验证完成前不得处理实际目录，因此本轮停止。实际data/aiops-evidence目录ACL及已有证据未变更，修复未部署、无模型调用、无服务重启，不能宣称权限修复已验收完成。

### 后续权限修复完成与现场复验

后续按用户确认的Administrator应用账户完成权限处理。tests/test_probe_storage.py五项通过，含真实Windows DACL、junction拒绝和受限令牌正反对照：同一受限令牌能读写显式允许Users的对照文件，不能以读或追加方式打开受保护证据。受限令牌验证不是独立普通用户登录测试，POSIX分支仍未实际验证。

实际data/aiops-evidence目录和四个原有query文件共五个路径已收紧，仅保留应用账户、Administrators、SYSTEM。四文件hash前后不变，应用账户仍可读取；报告runtime/evidence-permission-repair-054585994a0142e2a8e6ca68defbb2ff/summary.json为ok=true、paths_protected=5、files_preserved=4。后续受限令牌对四文件的读取/追加共八次打开均被拒绝；该检查输出尚无单独持久化报告，不混入summary已记录的三项检查。独立备份保留原SDDL和hash；未改写证据内容或重启服务。

扩大离线回归73项通过。随后runtime/windows-local-faults-7edf0e2dad7b44ad84a12922d259fced免费本机复验退出0、17检查条目通过，临时进程退出且端口释放，model_calls=0。此前“实际目录尚未变更”是历史状态，以本节及实际权限报告为准。

### 本地手册进入真实调查图的免费验收（21:05—21:06）

新增独立资料docs/fixtures/windows-local-runbooks/localapp-availability.md，仅说明通用排查方法，不包含本轮故障答案。evaluate_windows_probe.py增加--local-runbooks，复用local_retrieval.retrieve_local，隔离既有runbooks、Kaggle与HF来源；保存文档hash、查询、实际返回文本和文本hash到knowledge_trace.json。默认仍关闭付费向量/重排检索，不导入现有业务知识库。

验收入口从已校验Probe配置生成服务和依赖目录，提供允许的查询名称、日志路径及健康检查配置，排除token、CA、网关连接配置；它是权限/配置资料，不能当现场证据。固定模型完整图不再把经验替换为空，而是调用实际本地检索并断言手册进入规划输入，保存planner-context-normal.txt和planner-context-downstream_unreachable.txt。模型选择仍固定，不能证明手册影响了自主决策。

定向离线31 passed，覆盖本地实际检索、隔离恢复、目录脱敏、空资料拒绝和知识库内容不能进入现场证据索引。实际运行 ./.venv/Scripts/python.exe scripts/verify_windows_local_faults.py --evaluation-preflight，输出runtime/windows-local-faults-260a13a5bb6b42afb494f4bbd45e96ad/summary.json，退出0、ok=true，17个检查条目全通过。正常与下游不可达两场的预检均命中手册，完整图均local_runbook_context_verified=true、各四份Probe证据、完成后checkpoint重开通过。入口正常时HTTP200，下游停机时入口TCP通/HTTP503而下游TCP失败；其他应用退出、HTTP500/503、端口冲突、拒绝边界与重连检查通过。

model_calls=0、model_investigation=not_run、vector_rag_evaluated=false。主脚本31份证据不含完整图和独立预检证据。临时前台Probe使用当前账户，常驻LocalService未升级；owned_processes_stopped=true、remaining_listeners=[]，7278/7279/7280端口释放。没有部署、调用模型或在业务服务制造故障。

当前仍缺：真实模型未知答案调查、随机顺序的故障盲测、付费向量知识库联合调查、常驻LocalService业务日志权限、普通调查中途应用级重启恢复。正常/下游不可达固定顺序和固定决策只证明资料、工具、证据、图和存储能够衔接，不足以宣称自主根因定位通过。

### 随机模型验收编排的免费准备

后续将付费两场从固定故障生命周期中抽出，在正常和下游不可达之间随机排序，仍共用5元累计账本，任一场费用不明或失败即停止下一场，并在finally恢复模拟下游。模型的症状和输出路径改为随机ID，避免路径名称直接透露故障。每场开始清空专用测试应用日志以避免前一场记录泄露；仅处理本脚本创建的日志，不处理真实业务日志。测试控制器保留场景映射供事后复核，映射不放入模型上下文。

两种随机顺序、费用继承及失败后恢复用替代调查函数做离线测试；没有运行真实付费分支，因此尚不能宣称真实模型盲测通过，也不能由编排顺序测试证明实际模型上下文完全无答案泄露。免费现场采集及固定模型图仍按既有顺序执行，不与随机付费调查混淆。后续真实调查前需要新的费用授权，并核对当前模型价格与预算机制。

最终相关离线回归79 passed、9.40秒，仅既有PyMilvus弃用警告。git diff --check通过（既有换行提示），常驻RagAIOpsProbe仍Running。未执行前端回归或全项目测试：本轮仅改验收脚本、测试资料和文档，没有修改生产图或前端。工作仍位于codex/termcp-aiops-integration，未提交或部署。

### 修复参考资料在规划后丢失（21:13—21:14）

继续追踪真实调用链发现：planner把服务目录和检索经验送给规划模型，但原先不写入PlanExecuteState；executor与InvestigationStrategy只能读取计划、现场证据和调查记忆，无法继续使用这份目录和经验。因此前节只证明资料进入规划，不能证明它进入后续调查。

新增可选状态investigation_reference_context，planner在调用模型前对目录和经验做现有redact脱敏并形成独立参考文本，正常与规划降级返回均保存此字段。执行器和调查器读取该字段，并明确标为不可信参考、不是现场事实、不授予额外权限。它不进入raw_evidence或AiopsEvidence，不改变现场引用校验；旧checkpoint没有此字段时按空参考兼容。此轮改动生产state、planner、executor和investigation策略，没有修改图路由、审批协议或API。

直接相关43项测试通过；扩大到图、调查策略、Probe证据/存储/网关/API、Termcp审批、分类与快照等167 passed、10.62秒，仅既有PyMilvus警告。另补充现有中途SQLite重开测试，断言资料在中断、关闭、重开及后续执行中不丢失，且不混入现场证据；补充后直接相关43项再次通过、1.48秒。该中途测试为底层graph.ainvoke及mock现场，不证明普通调查可通过正式应用入口跨重启续跑。

实际免费本机复验输出runtime/windows-local-faults-169752b0b73440449160607364019073，退出0、ok=true、17检查条目通过。正常和下游不可达两场完整图分别断言：执行模型输入含手册与服务/依赖目录；调查模型输入含同一手册；完成后的SQLite checkpoint关闭重开后参考字段仍在。每场四份真实Probe证据，模型决策固定；model_calls=0、model_investigation=not_run。专用端口2044/2045/2046已释放、owned_processes_stopped=true、remaining_listeners=[]，常驻Probe仍Running，未部署或重启既有服务。

这次证明参考资料能贯穿规划、执行、后续调查和checkpoint保存，不能据此证明模型会正确利用资料或已自主归因。付费向量检索、真实模型随机盲测、LocalService业务日志权限及普通调查应用级中途恢复仍未完成。

### 修复中途知识检索正文未进入后续调查（21:23—21:30）

追踪发现中途search_knowledge_base返回虽保存在raw_evidence并用于最终来源展示，但调查器只读取现场证据索引；知识正文既不进入调查器输入，也不进入下一步执行器的独立参考区。先新增两项回归，实际两项失败，分别缺少knowledge字段与后续片段正文。

evidence_sources新增knowledge_context，识别带data_source=knowledge_base的结果和MCP text包装、多行JSON返回，保留来源、页码、chunk及正文；使用现有redact脱敏，每片最多1200字符并标truncated，最多提供六条去重片段。未标来源或嵌在主机payload中的知识形状不予提取。执行器与调查器分别读取这些参考片段，明确它们不是指令或现场事实，不授予额外权限，不能替代现场引用。现场evidence_index和AiopsEvidence未放宽规则。

直接相关51项通过，扩大定向63项通过；最终检索/调查/Probe/API/审批等187 passed、10 deselected、10.10秒，既有PyMilvus警告，集成标记按pytest默认排除。没有运行付费embedding、重排或对话模型。

真实本机免费复验runtime/windows-local-faults-64038d8f3e394f8b97308b90a93f9ad4退出0、ok=true，17检查条目通过。正常和下游不可达完整图均使用项目真实BM25Retriever对独立手册及干扰资料建内存索引，经现有rag_server.search_knowledge_base.fn过滤和格式化，通过正式执行器调用；下一步执行和调查输入均含localapp-guide片段，报告保留来源，完成后checkpoint重开仍可提取该片段。每场现场账本仍四份Probe证据，不含知识；主脚本31份证据不含两个图和独立预检。summary标mid_investigation_bm25_verified=true、knowledge_transport=in_process_rag_tool、vector_rag_evaluated=false。

知识检索工具在该轮验收进程内调用现有RAG函数，并未验证知识库MCP网络传输，也未使用真实向量库或付费重排；Probe走真实本机MCP。模型决策固定，因此并未证明自主选检查或正确归因。model_calls=0、model_investigation=not_run；临时前台Probe身份，owned_processes_stopped=true、remaining_listeners=[]，4982/4983/4985端口释放。未部署或重启常驻服务，未修改现有业务知识库。后续已补网络传输，见下节。

### 独立知识MCP及真实模型验收入口衔接（21:44—21:47）

前轮runtime/windows-local-faults-2c0e3e6f4ef24114b9b8adce2aaf2d23实际通过18个检查条目，知识服务独立启动、经统一MCP客户端加载，正常与下游不可达两场完整图均验证知识片段到达执行器和调查器，完成后checkpoint重开仍保留；这补齐先前进程内检索的网络缺口。

继续核对发现真实模型验收入口仍仅加载九个Probe工具，未参与上述动态知识装配。本轮修改scripts/evaluate_windows_probe.py和调用方scripts/verify_windows_local_faults.py，新增仅允许http://127.0.0.1:<port>/mcp的独立知识地址；免费与付费模式共用load_evaluation_tools和trace_evaluation_tools。知识服务只接受search_knowledge_base，Probe工具仍严格九项；额外工具拒绝，加载失败也清理客户端。两个服务分别装配，知识服务不携带Probe token。目录向模型告知独立知识库14，模型可自主检索；知识结果单独记来源及调用数，不进入现场返回计数。没有修改生产Agent或前端。

先新增回归实际得到2 failed、24 passed，缺少共用装配函数；补齐后37 passed，扩大最终90 passed、2.39秒，仅既有PyMilvus警告。新增零模型编排测试调用模型模式函数但替换Service，并阻断HTTP模型请求：确认知识工具可被装配和调用，结果不计现场证据、费用请求为空、报告不认定归因或知识效果通过。这是离线编排测试，不是自主调查。

实际免费本机运行两轮，首次runtime/windows-local-faults-bbd7e95b67ac43e5a0dfa3b74c37cd38为ok=true；统一工具记录后最终runtime/windows-local-faults-a975e208956945419c7aa43aa38b2f6f退出0、ok=true，18个检查条目全部passed（不是18种故障）。正常和下游不可达的预检均加载10个工具，各取得四份合法Probe现场返回与一份独立知识返回；后者validated_live_evidence=false，预检标明非自主选择。正常入口/下游HTTP200；下游断开时入口TCP成功、HTTP503，下游TCP失败。两场固定模型完整图各四份现场证据，中途知识经真实回环MCP进入后续上下文。主采集31份不含完整图和预检记录。

model_calls=0、model_investigation=not_run、vector_rag_evaluated=false。Probe为当前Administrator前台临时进程，不证明常驻LocalService业务日志权限。全部专用进程退出，13161/13162/13163/13164端口释放、remaining_listeners=[]；常驻RagAIOpsProbe复核Running/Automatic，未部署或重启常驻服务、未改业务白名单。git diff --check通过，仅既有换行提示；未改前端或生产代码，未运行前端和全项目回归。

仍未完成：真实模型随机故障盲测及知识是否改变自主检查、真实向量/重排联合调查、真实业务配置接入、LocalService业务日志权限和普通调查正式应用入口中途重启恢复。付费入口的网络装配/记录用免费预检与离线编排验证，真实模型分支未实际运行；不得据此宣称自主归因完成或复用旧费用授权。

### 最终裁决重新核验证据时效

沿真实InvestigationStrategy.decide调用链发现，原先在调用模型前校验证据索引，模型返回后沿用。如果等待期间Probe证据超过180秒有效期，最终根因或正常结论仍可能通过。新增可控时钟回归实际复现2 failed、36 passed，两个失败分别为等待后过期仍输出确定根因和正常。测试模拟时间和模型返回，不调用模型或等待真实超时。

修复为模型返回后重新构建已校验现场索引。本次引用在等待期间失效时记录校验失败，不再支持确定结论；原排除解释引用失效时降为unresolved。未引用的旧记录失效不阻断新鲜证据支持的结论。有合法后续检查时仍继续复采，不增加整体调查预算或固定步数。结构化决策失败报告同样使用返回时重新校验的索引。证据原文和checkpoint历史未删除。

扩大定向回归113 passed、2.11秒；完整后端离线回归538 passed、99 deselected、32.50秒，仅既有PyMilvus警告。默认排除integration，不代表外部集成通过；未改前端、未运行前端。本轮生产改动仅调查裁决策略，未重启Probe、网关或业务服务，常驻Probe复核Running/Automatic，模型调用0。git diff --check通过，仅既有换行提示。此项证明过期引用不能沿旧索引通过最终门槛，不证明因果推断正确；真实模型盲测及其他未完成项不变。
