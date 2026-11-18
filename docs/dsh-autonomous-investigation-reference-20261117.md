# DSH 类自主根因调查参考链路

日期：2026-11-17

这份材料把一次真实 DSH 排查抽成项目可以复用的工程流程。它描述的是节点、工具、配置和验收契约，不描述模型内部如何思考。

## 结论

这里的节点指工程操作阶段，不要求一个阶段对应一个 LangGraph 节点。实现时优先复用现有 planner → executor → replanner，把工具、记录和阶段出口接好；是否需要调整图拓扑应由实际断点决定。本文不更换模型、不修改图代码。

建议把一次调查固定成十个逻辑阶段。每个阶段都要有输入、允许工具、落盘产物和停止条件。只要一个阶段没有产物，后面的结论就不能升级。

## 十个逻辑阶段

| 阶段 | 做什么 | 主要工具或模块 | 必须留下的产物 | 不能越过的门槛 |
| --- | --- | --- | --- | --- |
| 0. 建立调查 | 固定故障现象、目标、时间窗、授权和预算快照 | API、run_store、成本账本读取器 | run manifest、账本哈希、授权范围 | 预算或授权不明确时不发真实请求 |
| 1. 绑定目标 | 确认究竟查哪个服务、进程、端口或桌面应用 | probe_inventory、target_catalog、health | target_resolution、允许服务/依赖/端口 | 目标不唯一时只做 inventory，不查具体对象 |
| 2. 采集基线 | 先取一次全局边界，避免拿错对象或旧日志 | probe_inventory、probe_resource_snapshot、probe_service_status、probe_process_snapshot、probe_port_snapshot | 带 target_id、时间戳、raw_hash 的原始证据 | 过期、未来时间、哈希不匹配、来源不明的证据不能进判断 |
| 3. 采集故障证据 | 查配置、入口日志、依赖连接、事件日志和指定文本日志 | probe_config_snapshot、probe_text_log、probe_event_log、probe_dependency_probe、MCP 日志/指标/变更工具 | 每条证据的来源、查询参数、采集时间、原文引用 | 不能用知识库经验替代现场事实 |
| 4. 建候选账本 | 把事实、未知、候选原因和互相矛盾的证据分开 | investigation strategy、registered_causes、evidence index | candidates、facts、unknowns、contradictions | 没有现场证据时保持未定位；只有故障层事实时不升级为 confirmed_cause |
| 5. 设计鉴别检查 | 每个候选只提出能区分它和替代解释的最小检查 | planner、CandidateCheck | next_check、next_tools、next_arguments、discriminating_question、expected_observation、stop_condition | 缺字段或工具不在白名单时不执行 |
| 6. 守卫并执行 | 校验目标范围、参数、重复查询和证据新鲜度，再调用工具 | tool_guards、executor、start_tool_call、finish_tool_call | proposed/executed 参数、blocked/failed/success、耗时、结果或错误 | 没有审计上下文或结果无法落盘时禁止外部调用 |
| 7. 消费结果并改判 | 把新证据送回候选账本，保留排除、支持和未决关系 | read_run_evidence、replanner、evidence_reader | evidence_consumed、candidate_transition、下一检查 | 同参数同结果不能无限重采样；没有新证据不能宣称收敛 |
| 8. 复现与修复 | 在隔离副本或受控现场复现修前行为，再执行批准的最小修复 | 证据快照、版本/配置快照、受控修复操作、回滚操作 | pre_fix、change、post_fix、备份哈希、操作者和审批 | 模拟输入必须标记 simulation，不能充当真实验收 |
| 9. 恢复与关闭 | 验证业务接口、进程、端口、页面和证据链恢复，再关闭事件 | health、probe_service_status、probe_port_snapshot、恢复控制器 | recovery checks、清理结果、残留风险 | 只恢复夹具不等于根因已解决；人审、机械审核、流程状态分开 |

## 这次 DSH 排查对应的工具清单

项目现在已有的通用工具可以覆盖服务型故障：

- inventory：发现目标、服务、依赖和允许范围。
- resources：CPU、内存等基线。
- services：服务状态。
- processes：进程、PID 和采样时间。
- ports：监听端口和绑定关系。
- event_logs：系统事件日志。
- text_logs：指定服务、路径和行数的文本日志。
- dependency_probe：检查登记依赖的连接；普通检查从 Probe 所在主机发起，支持的容器检查才有明确 source_service，不能一律当作应用进程实际发出的请求。
- config_snapshot：读取已登记服务的配置文件快照；是否被运行进程加载还需结合启动日志、加载哈希或运行时接口核实。
- read_run_evidence：只读重读本轮已经通过校验的证据。
- MCP monitor / CLS / change / knowledge：指标、日志、变更和经验参考。

DSH 桌面类问题还需要新增一个受控的运行时适配层。它不应直接给 Agent 任意 PowerShell，而应暴露固定操作：

- desktop_console_errors：读取指定时间窗的插件异常栈，带来源和采集时间。
- desktop_runtime_versions：读取宿主、插件、运行时和 peer 版本。
- desktop_plugin_manifest：读取插件 manifest、入口文件和已加载 bundle 的哈希。
- desktop_window_state：读取窗口、页面、插件面板是否可见及错误 overlay 状态。
- desktop_process_snapshot：区分主进程、renderer、GPU、插件宿主进程并采样 CPU/内存。
- desktop_event_loop_probe：测量固定窗口内事件循环延迟和长任务数量。
- desktop_render_probe：在固定窗口和采样时长内记录 FPS、renderer CPU 和 GPU 指标。
- desktop_controlled_experiment：只允许登记过的实验，例如禁用一个插件、最小化窗口或遮挡窗口；每个实验必须有前后快照和恢复动作。

这组 DSH 工具目前属于待补能力。当前项目的 Windows Probe 不能替代插件异常栈、事件循环和渲染性能工具。

## 我这次实际采用的顺序

1. 先用桌面控制工具确认 DSH 主窗口、DevTools 和当前错误是否仍在，先记录窗口状态，不立即点击或改设置。
2. 用 PowerShell 的文件枚举、rg 和定向读取确认插件版本、peer 范围、宿主 ASAR 元数据以及真实调用表达式；搜索失败或输出截断也单独记录。
3. 保存修前源码、bundle 和哈希，再把真实函数复制到工作区内、node_modules 之外的隔离目录，用 Node 做修前复现。此次 Node 直接从 node_modules 导入 TypeScript 被运行时拒绝，这是换用隔离副本的实际原因。
4. 对比宿主投影字段和插件类型，形成有限候选；没有把版本差异直接当成根因。
5. 对已安装插件做最小兼容保护，保存修后快照；重新读取真实窗口和 DevTools，检查原异常、兼容警告和页面数据。
6. 把修前/修后行为写成可重复脚本，用测试确认“修前会失败、修后不崩、重复调用只告警一次、正常成员仍能显示”。
7. 对卡顿只做负载观察；没有完成最小化/遮挡和 profiler 对照，就把壁纸或渲染器关系保留为未确认。

这套顺序里，CUA 负责真实窗口观察，PowerShell 负责可复核的文件和进程读取，Node 负责隔离复现，pytest 负责回归，apply_patch 负责留下可审计的修改。它们分别对应“现场事实、源码事实、可复现行为、回归证据、变更记录”，不能互相替代。

这里的 CUA、functions.exec 和 apply_patch 是本次外部调查者使用的工具，不是项目已经可以调用的 API。项目可复用的是这些工具完成的操作；desktop_* 名称是建议新增的项目接口。

| 真实调查记录 | 可复用的经验 | 失败后怎样换路 |
| --- | --- | --- |
| 主调查 226、242：窗口错误及保存的 DevTools 栈 | 先确认错误仍在，并记录异常发生时间、采集时间和来源 | 旧日志没有当前错误时，改从当前窗口/控制台取证，不能用旧日志冒充现场 |
| 228、232–234：源码、bundle、宿主版本与投影结构 | 从栈追到具体表达式，再查数据结构和版本契约 | ASAR 解析偏移出错后修解析方法；只读取目标条目，不运行解包代码 |
| 235–239：导入受限、备份、兼容修改 | 运行环境拒绝导入属于复现工具限制；先保存修前副本，再在隔离目录验证 | Node 拒绝 node_modules 内的 TS stripping 后改用工作区副本，不把导入失败当业务失败 |
| 244、246–249：窗口复核及四项断言 | 页面不崩、数据完整、性能正常是三个不同验收项 | 返回空成员列表只能证明防崩；仍要单独检查真实成员数据 |
| 续记中的坐标几何失败、搜索截断与 CPU 样本 | 取证失败也要记录；换工具或缩小范围，并保留未验证项 | CUA 几何不可用时实验记未执行；rg 限定文件和行数；单次 CPU 不用于性能归因 |

原记录入口：[主调查](/D:/ragPdfSystem++agent/runtime/dsh-autonomous-ops-investigation-20261117.md)、[续记](/D:/ragPdfSystem++agent/runtime/dsh-autonomous-ops-investigation-20261117-followup.md)、[兼容复现脚本](/D:/ragPdfSystem++agent/runtime/dsh-evidence-20261117/reproduce-team-projection.mjs)。

基础工具直接复用本机 PowerShell、rg、项目 Python 虚拟环境和 Node；本轮没有为此新增安装。持续性能归因可选 Electron DevTools Performance，必要时再用 WPR/WPA；本次没有完成这些 profiler 对照，不把工具建议写成执行结果。

## 工具结果的统一格式

以下是参考记录契约，包含建议补充的关联字段，不是当前协议已全部实现的声明。每条现场证据建议关联：

    evidence_id, run_id, target_id, operation, arguments
    collected_at, data_source, platform, payload
    raw_hash, truncated, provenance, readable

每条工具调用建议关联：

    call_id, thread_id, step_index, proposed_arguments, executed_arguments
    started_at, completed_at, status, reason, elapsed_ms
    result, result_truncated, evidence_ids

每个鉴别检查建议关联（stop_condition 是参考扩展字段，不是当前 CandidateCheck 必填字段）：

    hypothesis_id, next_check, next_tools, next_arguments
    discriminating_question, expected_observation, stop_condition

当前 Probe 原始信封已有 target_id、platform、operation、collected_at、collector_version、data_source、payload、raw_hash 和可选 truncated；run/thread、调用参数、证据 ID 等由存储和调用账本关联。应复用这些关联，不为文档强行修改旧协议。

记录还应注明 evidence_mode（live、source_snapshot、simulation 或 historical_statement）、input_evidence_ids、result_evidence_ids、父调用、下一步理由和原文文件位置。长结果写独立文件，保存脱敏副本与哈希，摘要里明确截断。重读证据不重复标成新采集，模拟不得混入真实验收。

## 建议配置

下面这些是当前项目已经支持、适合形成只读诊断基线的配置：

| 配置 | 建议值 | 作用 |
| --- | --- | --- |
| PROBE_ENABLED | true | 开启 Windows 只读现场证据 |
| PROBE_TARGET_ID | 每个环境唯一 | 绑定目标，防止串环境 |
| MCP_PROBE_URL | 实际 Probe 网关地址 | 读取 inventory、日志、进程、端口等 |
| PROBE_TOKEN | 私有环境变量 | Probe 鉴权，不写入报告 |
| PROBE_EVIDENCE_DIR | 独立目录 | 保存原始证据和哈希 |
| MONITOR_BACKEND | prometheus | 使用真实指标，不回退 mock |
| PROMETHEUS_URL | 实际地址 | 持续监察和性能指标来源 |
| OPS_WATCH_ENABLED | 配好数据源后再 true | 启用持久监察 worker；示例默认 false，避免把模板误当已部署监察 |
| OPS_WATCH_SERVICES | 登记服务名 | 监察对象 |
| OPS_WATCH_AUTO_DIAGNOSE | false 起步 | 先确认事件和证据，再开启自动诊断 |
| ENABLE_STEP_SNAPSHOTS | true | 保存每步状态，便于回放 |
| EXPERIENCE_KB_IDS | 专用运维案例库 | 限制 RAG 来源，避免知识污染 |
| EXPERIENCE_MIN_SCORE | 保留当前默认 0.30 | 检索分数需按具体检索路径核验，不视为所有 BM25/本地降级路径统一阈值 |
| ENABLE_RAW_EVIDENCE_FOR_JUDGE | 按使用的策略核验 | 是已有裁判配置，不是开启 DSH 取证的总开关 |
| INVESTIGATION_HYPOTHESIS_PROTECTION | true | 防止候选被弱证据覆盖 |
| INVESTIGATION_CONTRADICTION_TRIGGER | true | 出现矛盾时触发复核 |
| INVESTIGATION_PROTECTION_STEPS | 2 | 暂时保护候选的步数 |
| ENABLE_HITL | true 用于报告审核 | 它只负责报告草稿的人审；外部命令仍由 TERMCP 的逐命令审批或专用受控操作适配器负责 |
| TERMCP_ENABLED | false 起步 | 先只读调查，确认后再开放受控操作 |

配置必须同时覆盖四层，仅改环境变量还不够：

1. 应用层：沿用已有 SECRET_KEY、数据库、身份和模型私有配置；设置独立证据目录与 AIOPS_CHECKPOINT_DB_PATH。模型凭据不写入案例或报告，本轮不激活任何付费请求。
2. 目标层：PROBE_TARGET_ID、Probe 本地 TOML 的 target_id 和 DIAGNOSTIC_TARGET_CATALOG.target_id 必须一致。TOML 中登记准确进程名/参数片段、日志路径、配置文件与允许键、依赖地址；业务目录不能替代采集端白名单。
3. 观测层：先验证网关连接、鉴权、inventory、时间戳和原始证据存取，再启用持续监察。Prometheus 的服务标签必须与实际查询匹配，up 只说明对应采集目标可抓取，不自动代表 DSH 插件或业务健康。
4. 操作层：只读取证和修改分别配置。报告审核由 ENABLE_HITL 控制；修改插件、重载和重启应走已有适用授权、TERMCP 逐命令批准或专用操作适配器，不重复索取已授予的权限。

Probe 配置复用 [配置样例](/D:/ragPdfSystem++agent/docs/windows-probe-config.example.toml)。DSH 是进程应用，应按现场登记 kind=process；这类 service_status 为 not_applicable，需结合进程、窗口、日志和入口判断，不能当 Windows 服务 stopped。没有 DSH 日志文件时不编造 text_logs 路径。

业务目录结构由 target_catalog.py 校验，包含 version=1、target_id、services；每个服务可登记 aliases、probe_service、log_refs、expected_ports、dependencies、entries。先从 inventory 核实对象，再填目录，不复制示例中的地址、端口或库 ID 当现场事实。

建议新增但当前未接入 Settings 的 DSH 配置如下，名称先作为接口约定：

    DSH_RUNTIME_EVIDENCE_ENABLED=true
    DSH_TARGET_ID=dsh-desktop-01
    DSH_PLUGIN_ALLOWLIST=dsh-better-sidebar
    DSH_PLUGIN_MANIFEST_PATHS=<受控清单，不允许任意路径>
    DSH_CONSOLE_ERROR_SOURCE=<桌面运行时日志适配器>
    DSH_PERF_SAMPLE_SECONDS=10
    DSH_CPU_SAMPLE_INTERVAL_MS=500
    DSH_EVENT_LOOP_MAX_LAG_MS=100
    DSH_EVIDENCE_MAX_AGE_SECONDS=180
    DSH_EVIDENCE_RETENTION_DAYS=30
    DSH_EXPERIMENTS_ENABLED=false
    DSH_REPAIR_MODE=approval_required

这些 DSH_ 配置在实现前不能直接写进生产 .env；应先加入 Settings、配置校验和免费预检。

10 秒采样、500ms 间隔和 100ms 延迟阈值只是实验参数示例，未在当前 DSH 正常基线上标定。性能实验还须固定窗口大小、可见性、工作负载和预热条件，每次只改变一个因素；修前修后保存相同定义的指标，并区分单核百分比与整机百分比。

## 以这次 DSH 插件故障为例的最小闭环

1. desktop_console_errors 取到真实异常栈，并保存时间和来源。
2. desktop_plugin_manifest 取插件版本、宿主版本、入口文件和 bundle 哈希。
3. 从栈定位表达式，形成候选：字段缺失、版本不兼容、数据为空、其他插件污染。
4. 用保存的源码快照做修前复现；输入形状必须标记为模拟。
5. 只执行已批准的兼容保护或回滚，保存修前备份哈希。
6. 重新加载真实窗口，检查异常 overlay、成员数据和 console 警告。
7. 如果只是不崩但数据显示 0 成员，要报告“防崩成功、数据语义未确认”，不能写成完全恢复。
8. 如果要判断卡顿，必须再做固定时长的最小化/遮挡/插件开关对照；只有单次 CPU 样本不能下根因结论。

## 统一停止规则

- 没有唯一目标：停止具体检查，先补 inventory。
- 证据过期、哈希不匹配、来源不明：停止结论升级。
- 工具未加载、参数不完整、超出白名单：记录 blocked，不偷偷替换参数。
- 工具结果未写入账本：停止诊断，不继续假设调用成功。
- 没有新证据：不能重复同一查询来制造“进展”。
- 只有历史经验、没有现场事实：最多输出候选，不输出 confirmed_cause。
- 只有恢复 200 或页面不再报错：只能报告恢复观察，不能自动写成根因已证实。

## 经验移交和重做检查

本次移交先检查流程是否可重做、工具是否可调用、记录是否齐全，不以模型内部推理或换模型作为前提。项目后续重做时核对：

1. 通过固定工作流、API 或 Agent 执行相同的可观察步骤；把执行者和人工介入记清，不以谁完成调查替代步骤验收。
2. 每个工具调用都能在页面或 API 中看到提议、实际参数、结果、失败和耗时。
3. 每条结论都能回到原始证据 ID、采集时间和哈希。
4. 至少一个替代解释被实际鉴别，而不是只在报告中列名字。
5. 修前失败、修复动作、修后观察和恢复清理全部保留。
6. 性能根因有控制变量对照；没有对照就明确写未确认。
7. 下一次相同问题能从经验库检索到上次证据范围、有效检查和已知限制。

这套设计的核心不是增加更多图节点，而是让每个节点都有可验证的输入、工具范围、证据产物和停止条件。
