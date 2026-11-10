# 两故障四组真实预实验（三服务夹具）结果

上一批（2026-11-03，两服务夹具）八场全部停在 `localized_fault`，因为夹具结构上无法产出 `downstream_stopped_after_request` 所需的入口服务日志。本批按用户放行（「b，总共10；放行，触及到逻辑修改和架构等需要和我确认」「按此执行」）把夹具改成 edge→localapp→downstream 三服务拓扑，八场重跑。**新批次与 11-03 批次不合并统计。**

八场真实诊断及工程比较已完成，八场人工语义审核待审。结论：**三服务夹具确实让下游场的直接原因可达——下游四场里三场给出 `confirmed_cause` + `downstream_stopped_after_request`；配置错误四场仍全部停在 `localized_fault`。机制层假设保护依旧零机会、零改向；矛盾触发有 17 次机会，实际改向 3 次且只出现在 G01。**

## 授权、条件与实际执行

用户先选 B（改夹具让下游场可达直接原因，总预算 10 CNY），再选 B1-b（完整三服务重构），逐条批准了八项夹具改动，之后两次批准只放宽审计判据（`dfcb0e2`、`84dbaa7`），最后一次批准把「结构化输出解析器遇到未知工具名」判为格式失败（`c2685a3`）。每次放行原话与范围记录在 `runtime/e2-b1b-20261110/human-smoke-review.json`、`human-smoke-review-continue.json`、`human-smoke-review-final.json`。

账本从 11-03 批次的 636 条 / 20.087316 CNY 续到 762 条 / 26.847636 CNY，累计上限 30.087316。本批新增 126 次请求、6.760320 CNY，**低于授权的 10 CNY**，估算余 3.239680 CNY。全部请求 HTTP 200、usage 完整、供应商账单未核。

套件 `e2-fault-pair-v1`，输入 `candidate-opportunity`，症状文本 hash `83e42b79e3cfdc9ff5129ea89656407196378899548ba7aee414d13574f65417`（与 11-03 的 `9f4b7ec9…` 不同：入口由 localapp 改为 edge）。每场独立目录、`runs.sqlite`、`checkpoints.sqlite`、thread 与观测时间边界；组别与控制器故障答案不在模型上下文里。

## 夹具改动（`eeb1cb2`）

1. `config.toml` 增加 `[services.edge]` 与 `[dependencies.edge]`，端口 4→5，形成 edge(业务入口)→localapp→downstream 三跳。
2. `application()` 支持 `--runtime-config`；edge 的连接文件指向 localapp，downstream 的连接文件 `downstream_port=null`（只为产出 `service_started`/`service_exited`）。
3. **localapp 的启动连接文件就是 `app.mode` 本身**（`{"max_attempts":3,"downstream_port":<dep_port>,"upstream_timeout_seconds":0.5}`），使配置快照哈希与日志里的 `configuration.source_sha256` 天然一致——否则配置错误场的交叉核对会失效。
4. `set_model_case` 的 `downstream_unreachable` 场：先启动 downstream（写 `service_started`）→ 立刻优雅停（写 `shutdown_requested` + `service_exited`，中间不做任何探测，避免 `_observation_conflicts` 判同 scope 多值冲突）→ 再打一次 edge 的 `/api/availability` 业务请求，产生同 `request_id` 的 localapp 503 与 edge 503 日志。
5. `serve()` 的 `request_completed` 事件带 `error_type`，且 `configuration` 优先取配置错误字典。
6. 症状文本 `candidate-opportunity` 由「localapp 当前不可用」改为「edge 业务入口当前不可用」——`in_business_scope` 只允许读被 `resolve_target` 命中的服务的日志，不提 edge 就读不到 edge 日志。
7. 期望层 `downstream_unreachable` 由 `['localized_fault']` 扩为 `['localized_fault','confirmed_cause']`。
8. `evaluation_preflight` 的条数断言 5/6/5 → 7/8/7。

另加一条**零成本门禁** `downstream_stopped_cause_derivable`：付费前先用真实 Probe 采集 8 条证据，直接调 `_direct_cause_evidence` 断言 `downstream_stopped_after_request` 可达。它在本批第一次通过时是侥幸——edge 与 localapp 的上游超时都是 0.5 秒，edge 会比 localapp 早 15 毫秒放弃，导致「edge 的 `at` 不早于 localapp 的 `at`」这条门槛随机失败；把 edge 超时改成 1.5 秒后才稳定。

## 八场表

机会列「保护/矛盾」，改向与执行列同为「保护/矛盾」。耗时为各子场模型工作流耗时，不含场景复位与末尾免费固定图检查。

| 序号 | 故障 | 组 | 机会 | 改向 | 执行检查 | 请求 | 估算费用/元 | 耗时/秒 | 故障层 | 原因码 | 引用精确 |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|---:|
| 1 | 配置错误 | G00 | 0/2 | 0/0 | 0/0 | 8 | 0.359568 | 63.792 | localized_fault | - | 24/24 |
| 2 | 配置错误 | G01 | 0/5 | 0/3 | 0/4 | 13 | 0.737048 | 103.580 | localized_fault | - | 23/23 |
| 3 | 配置错误 | G11 | 0/3 | 0/0 | 0/3 | 12 | 0.693214 | 94.288 | localized_fault | - | 26/26 |
| 4 | 配置错误 | G10 | 0/3 | 0/0 | 0/0 | 10 | 0.452574 | 74.827 | localized_fault | - | 26/26 |
| 5 | 下游不可达 | G10 | 0/1 | 0/0 | 0/0 | 11 | 0.559024 | 85.014 | localized_fault | - | 13/13 |
| 6 | 下游不可达 | G01 | 0/1 | 0/0 | 0/1 | 9 | 0.459240 | 69.568 | confirmed_cause | downstream_stopped_after_request | 16/16 |
| 7 | 下游不可达 | G11 | 0/1 | 0/0 | 0/1 | 15 | 0.918792 | 120.275 | confirmed_cause | downstream_stopped_after_request | 11/11 |
| 8 | 下游不可达 | G00 | 0/1 | 0/0 | 0/0 | 10 | 0.524064 | 81.572 | confirmed_cause | downstream_stopped_after_request | 16/16 |

八场流程完成、结果层与构造场景相符、机制行为审计与记录完整性检查全部通过（`all_audits_passed=true`、`all_mechanical_passed=true`）。**155 条引用逐条落在被引证据的原文里（155/155）**，用评测侧自己的 `_citation_in_evidence` 校验。`capability_passed=false` 仍表示语义待审，诊断正确率保持 null。

## 观察差异

**下游场：三场给出直接原因，一场停在故障层。** G01/G11/G00 三场的结论都写清了同一形态：downstream 进程（pid、instance、listen_port）先 `service_started`，随后收到 `file_presence` 通道的 `controlled_stop`，再 `service_exited/shutdown_completed`；此后端口无监听、配置身份进程缺失、TCP 探测 `ConnectionRefusedError`；localapp 按配置的 `downstream_port` 在 connect 阶段失败返回 503，edge 转发该 503 到入口。三场都把「停止发起者 initiator=unknown」明确划出结论范围，没有越界。

G10 只到 `localized_fault`：结论只列了现场条件（入口 503、downstream TCP 失败、端口无监听、无匹配进程），没有把 lifecycle 三件套提升为解释。这是模型侧的收束差异，不是夹具不可达——同一批 G00/G01/G11 都做到了。

**配置错误场：四场全部停在 `localized_fault`，但都引到了真凭据。** 四场的结论都是同一条：`max_attempts='invalid'` 的配置错误日志 + 当前独立配置快照的字段与哈希一致（`configuration_error_log_matches_snapshot`）。四场都读了 `downstream_port` 并确认它指向真实监听端口，说明本批新增的「app.mode 兼作 runtime-config」这一硬约束生效。没有一场越界声称知道「谁在何时把配置写坏」。

**机制层：假设保护零机会，矛盾触发有 17 次机会但改向只出现在 G01。** 保护机会在八场里全为 0，与 11-03 批次一致——本批仍没有「模型漏了但仍存在合法鉴别检查」的自然样本。矛盾机会 17 次（配置场 13、下游场 4），实际改向 3 次、执行检查 9 次，全部集中在 G01（配置场 3 次改向 / 4 次执行检查，下游场 1 次执行检查）与 G11（配置场 3 次执行检查、下游场 1 次执行检查）。**G00 与 G10 的改向与执行检查都是 0**，与「关闭触发组由模型自行转查」的 11-03 观察一致。

因此本批**仍不能**给出机制收益证据：保护机制没有机会，矛盾机制只在少数组出现，且八场是八条不同自主轨迹，费用与耗时差异不能归因于机制。

## 三处系统侧缺陷（本批发现并已修，均有回放证据）

1. **`dfcb0e2`「机制停止 ≠ 没有计划」** —— 第 2 场崩在 `contradiction_blocked` 审计：引擎在同一轮既发了机制层停止（「无替代鉴别检查」），又按模型给出的合法 Probe 参数排了可执行检查（`9e178b4`「参数即意图」），审计却要求 blocked 必须与「无计划」同现。修法是把审计的「可用替代」判据逐字镜像引擎自己的谓词（补 `relation != 'contradict'` 与 `condition_binding == 'bound'`），并允许「模型给出的合法参数检查」与停止同轮共存。回放该失败场 → `passed=True`。
2. **`84dbaa7`「回退有两种」** —— 第 3 场崩在「不可执行检查后的候选回退与前轮状态不一致」：审计只认「保存候选回退」，而引擎在三服务拓扑下还会走 `_uncovered_scope_followup`（为每个未覆盖的登记依赖/服务各排一次检查），产出的 `blocked_check_recovery.kind` 是 `uncovered_scope_check`。修法是按 `kind` 分流校验。回放该失败场 → `passed=True`。
3. **`c2685a3`「解析器未知工具名」** —— 第 7 场崩在 `KeyError('read_run_evidence')`：模型在 replanner 里没按 schema 返回决策，而是发了一个它能看到的工具调用，LangChain 的 `PydanticToolsParser` 用 `name_dict[res['type']]` 查不到类就抛裸 `KeyError`；`_format_failure()` 不认 `KeyError`，异常绕过 JSON 降级直接崩掉整轮。修法是用 traceback 帧精确识别来自 `output_parsers/openai_tools.py` 的 `KeyError` 并归入可降级集合，无关 `KeyError` 仍上抛。补 3 条测试。

三次失败都是**系统侧**，不是模型或夹具问题，共花 2.056796 CNY / 38 请求（占本批 30%）。每次修完都跑了免费门禁（`--scenario-preflight`、`--evaluation-preflight`，零模型调用）与全量回归（2102→2105 passed / 0 failed），再回放失败场确认判据正确。

## 重复 finding 与重复未决问题（已修，`cbe9375`）

配置场四场的报告里，同一个矛盾被报了四遍。根因有两层，都属系统侧：

1. **一条日志证据里有四条失败请求。** 一次 `probe_text_log` 返回整个日志尾部，而配置错误的 localapp 每次失败请求都会写一行 `error_type=ValueError` 的 `request_completed`；该场日志里有 4 行，且 4 行的 `service`/`field`/`source_sha256` 完全相同。`_configuration_error_findings` 对每行 append 一个 finding，于是同一个「`max_attempts` 与快照矛盾」变成 4 条 finding。
2. **未决问题按 finding 逐条生成。** `investigation_gaps` 对每条 finding 各 append 一个 `gap-config-history-<hash(service)>`，4 条 finding 就产生 4 条 id 相同、问题文本相同的未决问题；`unresolved_questions` 只是把它们原样 `extend` 进结果。

修法：finding 按 `(service, field, source_sha256)` 去重——一次日志读取里的同一处矛盾只保留第一条，其余仍留在证据原文里；未决问题按 `gap id` 去重（同一服务的配置变更历史只有一个「谁在何时改的」未知）。**不同字段仍然各自成条**，不合并。

用该批四场的存档证据回放（`runtime/e2_b1b_dedup_replay.py`）：修复前每场 4 条 finding + 4 条未决问题（合计 16/16），修复后每场 1 + 1（合计 4/4）；下游四场本就没有该 finding，前后都是 0。新增两条回归测试，其中一条专门断言「同文件不同字段仍是两条 finding」。

## 仍然存在的缺陷（未修）

1. **下游场的「证据支持的解释」仍偏通用**：`confirmed_cause` 三场写得具体，但 `localized_fault` 的 G10 只堆现场条件，没有把 lifecycle 三件套提升为解释。
2. **配置错误场只到 `localized_fault`：不是证据缺环，是原因码只有两个。** 用四场存档证据回放（`runtime/e2_config_chain.py`）：每场都能在**同一 request_id** 上凑齐「配置快照 `source_sha256` → 应用日志同哈希、同字段、同值、`error_type=ValueError`、`/api/availability`、`status>=500` → edge 同 request_id、同 status 的 503」这条链，四场各有一条（`22f42ad3cecd…`、`84513f082f0c…`、`3bc3859f0a68…`、`52bcb463c8a2…`），`statuses_match=true`。也就是说证据形态与 `configured_downstream_endpoint_mismatch` 完全同构，缺的只是一个原因码：`InvestigationDecision.root_cause_code` 的 `Literal` 只有 `configured_downstream_endpoint_mismatch` 与 `downstream_stopped_after_request`，`_direct_cause_evidence()` 也只登记这两把钥匙，因此 `decide_from_evidence` 的「根因缺少受支持的原因码或完整同请求证据链」分支必然把 `confirmed_cause` 打回 `unlocated`。G00 那场模型在 `root_cause` 里原话写了「该解释不属于两类可确认直接原因码，故仅定位到故障层，不升级为 confirmed_cause」——它在按契约办事，不是判断失误。**要不要加第三个原因码（如 `configuration_value_rejected`）属逻辑/架构改动，须先确认再做。**

## 费用、审核与验证

新增 126 次请求全部 HTTP 200、usage 完整，估算新增 6.760320 CNY，低于整批 10 CNY 与每场 1.25 CNY 的等额上限。账本从 636 条 / 20.087316 续到 762 条 / 26.847636，累计上限 30.087316，估算余 3.239680；历史 61 条未知价格用量保留，供应商最终账单未核。最新账本 `runtime/windows-local-faults-4cddc36563b4402e9bcb46cd9de0b820/model-061d716a232d472d96d03685633bf669/cost.json`。

四次控制器运行的清理全部干净：`owned_processes_stopped=true`、`ports_released=true`、`remaining_listeners=[]`、`cleanup_errors=[]`；每个失败场都保留了完整产物（`mechanism_trace.json`、`events.json`、`checkpoints.sqlite`、`runs.sqlite`、`report.txt`）供复核。

免费门禁：`--scenario-preflight --four-group-suite e2-fault-pair-v1`（`runtime/windows-local-faults-1a0725f5…`，8 轮 / 32 观测 / 0 模型调用）与 `--evaluation-preflight`（`runtime/windows-local-faults-cad2d141…`，31 项全过、`evidence_count=64`、0 模型调用）在付费前后各跑一次。全量回归 `pytest -q -m "not integration"` → 2105 passed / 106 deselected / 0 failed。

初步（非约束）语义审核：`runtime/e2-b1b-20261110/preliminary-review.json`，`binding=false`、`written_to_manual_review=false`。它只核对了引用是否逐字落在证据里、机械门与审计是否通过、报告是否包含原因码，**没有**替人做诊断正确性判断。八场的人工三维语义审核仍为 pending。

## 阶段决定

1. **夹具目标已达成**：三服务拓扑让下游场的 `downstream_stopped_after_request` 从「结构上不可达」变成「3/4 场实际产出」，且付费前有零成本门禁守着。这条能力在产品链路上（029/033 轮）本来就通，本批只是让四组夹具也能产出同一形态。
2. **机制层仍无收益证据**：保护零机会、矛盾只在少数组改向，且样本量（八场、每组两场）不支持任何统计结论。与 11-03 批次结论一致：暂不扩大场数、保留机制、不追加机制开发。
3. **下一批若继续，应先补两件事**：一是修掉未决问题/finding 的去重缺陷（否则每份报告都带重复条目）；二是把「配置错误场为何只能到 localized_fault」单独查清——四场都引到了 `configuration_error_log_matches_snapshot`，模型却没有把它提升为 `confirmed_cause`，需要判断是提示词门槛过高还是证据链缺一环。
