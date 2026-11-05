# 调查深度修复与独立配置取证（2026-11-03）

配置错误调查已从“日志说配置异常”推进到独立读取当前配置：真实模型主动执行 `probe_config_snapshot(service=localapp)`，取得 `max_attempts=invalid`，文件来源哈希与应用错误日志一致；入口 HTTP 503、下游 HTTP 200。可以确认当前非法配置及对应报错，尚不能确认修改者、变更历史或修复后的因果效果。下游场只确认停止请求文件存在，触发者仍未知。

## 用户判断与验收边界

用户对旧三场判断已登记：诊断“至少一场调查不充分”、引用“supported：支持有限结论”、建议“appropriate：可作有前提的人工清单”。回执为 `runtime/diagnostic-depth-20261103/human-decision.json`，绑定旧审核包哈希，38份来源/副本核对通过。用户未指明场景，不逐场代填 incomplete 或通过；旧包 pending 是历史快照。

本次新场另建 `runtime/diagnostic-depth-20261103/config-snapshot-human-review/review-package.json`，11份模型报告、工具轨迹、机械审核及现场证据副本哈希一致，无控制器答案。新场语义判断仍待用户审核，不套用旧判断，`smoke_passed=false`。持续目标仍 active，三场G11不代替正式四组完成。

## 问题与修改

1. 原工具能读报错日志，但没有独立配置取证能力。新增 `probe_config_snapshot(service)`，对应 Probe `configuration`；服务名映射到预配置的精确JSON文件和字段，模型不能传路径或额外键。限制16KiB，字段筛选、脱敏、来源哈希和mtime_ns随证据保存；坏JSON、未配置、超限明确失败，复用打开句柄路径校验以拒绝reparse/越界。
2. 调用链已接通 Windows 配置/采集器、Probe协议与证据、MCP gateway、Agent工具/观测/证据消费/执行器及具体检查守卫。只读配置路径由部署配置规定，不开放任意文件读取。
3. 四组共用策略增加一次配置日志交叉核对：当前成功日志有结构化配置异常、服务和工具在允许范围、未成功读取且未失败时才可补查；精确重复、失败重试、参数与范围守卫保留。这是通用调查能力，不计保护或矛盾收益。本次最终真实场模型自己选择该工具，三个决策的 `policy_selected_check` 均为 null。
4. 修复结果消费错误：有限条件已被证据反驳，却因原文与条件不绑定再次列为未查。现在保留独立有限条件状态，原始因果文字仍未验证；完整结论仍要求关键排除解释与条件绑定，不放宽健康/根因门槛。对应反例先失败后通过。
5. 测试业务日志保存配置来源、指定字段/值及source_sha256；停止日志保存stop_request路径、mtime_ns、initiator=unknown，不推断触发者。
6. 新工具暴露多个验证入口写死工具数量的问题，改为核对协议工具名称集合。修正新测试inventory哈希、旧预检空工具及固定决策机制夹具；未绕过生产校验。

主要实现：`src/probe/windows/config.py`、`collector.py`、`src/probe/protocol.py`、`evidence.py`、`mcp_servers/probe_gateway.py`、`src/agent/aiops/{tools,observations,evidence_sources,executor,probe_checks}.py`、`strategies/investigation.py`；相关入口和调用者同步修改。

## 本轮三个真实场与费用

| 运行ID / G11场景 | 累计请求链 | 新请求 | 峰值估算CNY | 结果与版本限制 |
|---|---|---:|---:|---|
| aa7d5320351141458d4ff3a33ff043db / 配置错误 | 395→402 | 7 | 0.230838 | 有限定位；尚未加入独立配置工具，不能算最终版通过 |
| a3d4846704f44e05acec379319fb1538 / 下游不可达 | 402→413 | 11 | 0.628352 | 读到停止请求，initiator未知；早于最终配置/条件消费修复 |
| 16b2420a9ac149f092a246d82979f7c6 / 配置错误 | 413→419 | 6 | 0.171080 | 最终版真实执行并消费独立配置证据，localized_fault |

本轮24请求/1.030270 CNY；本批授权基数318条/9.969390 CNY，现419条/14.053104 CNY，新增101请求/4.083714 CNY，10元新增授权估算余量5.916286 CNY。单场5元、累计上限19.969390、请求数上限均null。所有新增请求HTTP200且usage完整；账本395→402→413→419的每段旧前缀逐行不变。历史61条未知价格保留，以上是已核价峰值估算/预留，供应商账单未核，总实际费用仍未知。

最新账本：`runtime/windows-local-faults-16b2420a9ac149f092a246d82979f7c6/model-eed7220f70b04914a0f1aa8eb5908b5e/cost.json`。SHA256：`ff7b1d4230cc18cbdb079b821750dd3ceece279a8bad03a83239833cbad21bf6`。后续必须继承419条，不回退旧账本或清零。

## 最终真实场可核对证据

| 证据ID | 实际观测 |
|---|---|
| ev-82345bbf1de543b3bd60c5438a60b4e2 | localapp TCP通、HTTP503 |
| ev-f55b2c273d79412bb449d42cbe04556c | 6571监听，PID12052 |
| ev-475a015cfc6b4a0ea96a106281f2028d | 匹配配置身份的应用进程存在 |
| ev-4621d2aad45f4061bc731e3f731a1134 | downstream HTTP200 |
| ev-8abacfd8c7cd4fe8a102cba0890b2c54 | ValueError、max_attempts非法及配置来源哈希 |
| ev-54407589397b42b5adb45f869c508db8 | 独立快照values={max_attempts: invalid}、missing_keys=[] |

配置与日志来源哈希均为 `8bbb6e42a88cae96ee51d4dda228d5f912c4f8b1372721528c3c887fd04ad9a2`。这里比对的是调查时保存的证据，未拿恢复后的app.mode冒充故障时文件。

最终场3执行步、8有效Probe返回，报告实际引用配置值和完整来源哈希。流程、结果层、机械、记录完整性及机制行为审计通过；保护/矛盾机会均0、知识MCP0，不证明机制有效或RAG有效。控制器ok=true、38控制器证据、normal_restored、所属进程停止、端口释放、errors/cleanup_errors为空。控制器恢复仅用于夹具收尾，不能当成Agent实施修复并证明因果。

## 免费验证与失败保留

- 默认离线全量最终1649 passed / 99 integration deselected，仅既有PyMilvus警告。最初4 failed / 1645 passed暴露工具目录旧断言，已修。更早相关回归333 passed；扩大范围出现6项夹具失败，修后对应两文件142 passed。各轮不相加。
- 最后固定机制夹具调整由完整免费 `--evaluation-preflight` 实际验证：运行 `runtime/windows-local-faults-10f6264d23834f78902c0dd7c8161e73`，退出0、30项case通过、56控制器证据，窗口13轮/52证据、固定机制12场/44证据，model_calls=0；独立配置取证、日志哈希交叉匹配、正式执行器、证据落盘/重开、知识隔离、恢复/清理通过。固定决策不算自主样本。
- 免费现场失败目录保留：`7c1b991d3ec543e492d8341520420602`（旧9工具断言）、`b238e432966b4e4a92c69a1e8e278f8c`（知识目录旧10工具断言）、`f551b909a79f482a93f0274bb9d80cc9`（新增通用补查与固定夹具预期冲突）。均0模型调用，清理成功，不回填成功。
- 最终免费核对 `runtime/diagnostic-depth-20261103/verify_closeout.py` 退出0，结果 `final-verification.json`：136份运行源码与当前代码一致，8份模型现场证据、15份原模型产物哈希、账本链及11份审核副本核对通过，0新模型/0新观测。
- 未运行本轮浏览器、外部integration、TLS现场或已安装Probe现场；未提交推送。

## 仍不足与下一入口

当前可以读到真实配置，不能追溯谁改过；下游有停止请求，但没有独立的操作者审计来源。工具不足是实际缺口，不是请求数量限制。报告仍有笼统重复的机械边界说明，影响可读性；不能为改文案原样重复付费。

下一入口是审核新配置场的有限结论、调查深度和建议；扩展/四组不代填人审。若继续追配置变更者或停止触发者，应先补合法、可追溯的现场变更/控制事件来源，再做有新增信息价值的复验。不能把控制器私有答案喂给Agent，也不能用再次读取同样日志冒充深入。系统已完成上述取证与回归，用户尚未亲手复现，不据此认定已掌握新增调用链。

## 后续免费补查：宿主机历史审计来源（2026-11-03）

已实际查询宿主机，不再只凭Probe未配置事件通道就判断没有系统记录。该补查使用控制器已知时间/PID缩小读取范围，属于开发者事后诊断，不是原Agent自主取得的证据，不加入原报告或四组得分。

- `auditpol /get`只读查询：进程创建 `{0CCE922B-69AE-11D9-BED3-505054503030}`、进程终止 `{0CCE922C-69AE-11D9-BED3-505054503030}`、文件系统 `{0CCE921D-69AE-11D9-BED3-505054503030}` 当前均为 `No Auditing`。这证明当前设置，不能证明历史上从未开启。
- Security通道可读取、已启用且有32965条记录；Sysmon/Operational不存在，PowerShellCore/Operational不存在。Windows PowerShell/Operational可读取，但最新事件早于这两场。
- 下游窗口2026-11-02T23:38:20Z至23:41:00Z；配置窗口2026-11-03T00:09:45Z至00:10:45Z。实际查询Security事件4688/4689/4656/4663/4660/4657、Application事件1000/1001、Windows PowerShell事件4103/4104，六个组合均明确返回NoMatchingEventsFound，未把查询错误当空结果。Security和Application保留时间范围跨越两场；这仍不证明日志连续、没有其他来源或没有发生变更。
- 证据保存在 `runtime/diagnostic-depth-20261103/audit-source-availability.json`、`historical-audit-query.json`、`powershell-core-audit-query.json`。仅保存通道状态、查询窗口、计数和错误标识，不输出其他业务日志正文。

因此，本轮剩余障碍已进一步核实为：现有已查询审计来源没有可用于归因的事件；当前相关审计未开启，Sysmon也未提供记录。不能事后补开审计还原过去，更不能用控制器知道的触发行为代替独立证据。未改审计策略、SACL或系统服务；未新增模型请求，账本仍419条。新配置场的语义审核请求已发出，未收到新回答前不进入扩展/四组，也不重复发问。

## 最新配置错误场后的只读事件核对（2026-11-03）

新真实运行 `runtime/windows-local-faults-526b7c5e651b4bc899b1bf4f0d8e5518/model-4564e0f9b9f548f18f88dfed7ce979a2/` 在本地时间13:12:37观察到入口503。开发者随后只读查询13:11:30–13:14:30窗口：Security有4条事件，但仅4624、4672、5379；没有4688/4689进程创建/终止或4656/4663/4660/4657文件审计事件。Application与Windows PowerShell窗口内无事件，PowerShell Operational窗口内无事件，Sysmon Operational通道不存在。按subcategory GUID重新读取的当前策略显示Process Creation、Process Termination、File System均为`No Auditing`。

这是本次运行后的开发者补查，不是Agent现场证据，也未写入本次报告或得分；它进一步确认该时间窗口没有可用于归因的已查询事件，但不能证明不存在其他审计来源。命令调用期间有一次AuditPol参数格式错误，未用于结论；之后逐个GUID的只读查询成功。没有修改审计策略、SACL或服务。旧账本544→550，新增6次模型请求、峰值预留0.121332 CNY；Agent报告停止于模型未提出下一检查且系统未验证检查穷尽，工作流/机械门/结果层/清理通过，能力未通过，人审pending。继续查历史变更人必须先让未来测试在故障发生前记录变更事件；不能用再次付费重跑相同缺失审计的场景解决。

## 测试注入故障的事后因果核对（2026-11-03）

为判断本场直接503是否仍有未查原因，独立检查运行源码快照及当前测试夹具：`scripts/verify_windows_local_faults.py` 的 `application_config_error` 分支写入 `{"max_attempts":"invalid"}`；`serve()` 每个请求解析该字段并调用 `int(...)`，异常捕获后设置HTTP503并记录ValueError、配置路径与哈希。对应夹具 `tests/test_windows_local_faults.py` 还验证同场下游HTTP200、日志/配置哈希一致，并在恢复为有效整数后验证应用恢复。当前定向复验该文件116项全部通过。

因此，测试场的直接技术原因已由测试生成器、应用处理代码和恢复用例确认：控制器注入不可转整数的配置值，应用按设计返回503；不是下游故障。此为事后控制器/代码层证据，不是Agent现场观测，不回写 `summary.json` 的 `capability_passed=false`、原始报告或pending人工审核。Agent的可见证据已足以定位配置字段及错误表现，但它在报告中没有提出下一检查，且通用系统停止原因仍未验证检查穷尽。谁在真实生产中修改配置属于另一问题；本次测试中该值由测试控制器写入，无需改本机审计策略即可解释这个受控故障。
