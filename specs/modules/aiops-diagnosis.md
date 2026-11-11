# spec · aiops-diagnosis（AIOps 诊断链路）

- 模块：`aiops-diagnosis`，规则前缀 `RULE-DIAG-`，断言前缀 `ASRT-DIAG-`，功能前缀 `FEAT-DIAG-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（`main`，2026-11-11）
- 需求依据：`requirements/modules/aiops-diagnosis.md`（REQ-DIAG-001 ~ REQ-DIAG-013）
- 所有 `source` 均为 `完整相对路径:行号`；`basis=observed` = 读源码核实。
- **本模块只有 1 条 `confirmed` 级规则**：RULE-DIAG-018（改判定逻辑前必须过零成本回放门禁），依据是 `docs/aiops-goal-handover-20261108.md:186-200` 与 `requirements/project-card.md` 的 D3——都有写明理由与适用条件。其余规则全部 `observed`，**不得据此判正式 PASS/FAIL**。
- 流程引用：`FLOW-DIAG`（提交→图执行→SSE→报告）、`FLOW-DIAG-RESUME`（终态挂起→审批校验→续跑）。

---

## 1. 交互与接口状态

### 1.1 用户动作 → 接口映射

| 用户动作 | 前端判定 | 接口 | 输出形态 | source |
|---|---|---|---|---|
| 输入现象并点「开始诊断」 | `query` 非空、未在跑、无挂起审批 | `POST /api/v1/aiops` | SSE，`event: message` + `data:<JSON>` | `frontend/src/views/AIOps.vue:794-827`、`src/api/routers/aiops.py:40-44` |
| 输入框内 Ctrl+Enter | 同上 | 同上 | 同上 | `frontend/src/views/AIOps.vue:13` |
| 勾选「终端诊断」再提交 | `terminalEnabled` 为真 | 同上，多带 `terminal_enabled: true` | `TERMCP_ENABLED=false` 时直接 503 | `frontend/src/views/AIOps.vue:808`、`src/api/routers/aiops.py:55-56` |
| 点「继续诊断」（Termcp 审批卡） | `pendingApproval` 非空 | `POST /api/v1/aiops/runs/{thread_id}/continue` | SSE 续跑 | `frontend/src/views/AIOps.vue:46,829-854`、`src/api/routers/aiops.py:146-166` |
| 页面刷新后恢复挂起 | `localStorage.aiops_pending_thread` 命中 | `GET /api/v1/aiops/runs/{thread_id}` | JSON（`status=pending_terminal` 才恢复审批卡） | `frontend/src/views/AIOps.vue:856-890`、`src/api/routers/aiops.py:132-143` |
| 中止诊断（关闭/abort） | `AbortController.abort()` | — | 状态行显示「诊断已取消」 | `frontend/src/views/AIOps.vue:794-827` |

### 1.2 请求/响应契约

**请求体**（`AIOpsRequest`，`src/api/routers/aiops.py:32-37`）

| 字段 | 类型 | 必填 | 约束 | 越界后果 |
|---|---|---|---|---|
| `query` | `str` | 是 | **无声明层校验**（无 `min_length`） | 空串不在路由层报错，由图层回 `error/validation_error` |
| `session_id` | `str \| None` | 否 | 无校验；`None` → `"default"` | `src/api/routers/aiops.py:54` |
| `terminal_enabled` | `bool` | 否 | 默认 `False` | 为真且 `TERMCP_ENABLED=false` → **503**「受控终端诊断尚未启用」 |

**响应**：SSE。帧格式固定为 `{"event": "message", "data": "<json 字符串>"}`（`src/api/routers/aiops.py:76-79`）。`data` 反序列化后的对象以 `type` 区分（见 1.3）。

**`usage` 帧字段**（`src/utils/token_meter.py:132-141` + `src/api/routers/aiops.py:107`）：`type="usage"`、`llm_calls`、`input_tokens`、`output_tokens`、`total_tokens`、`by_model`、`cost_cny_estimated`、`count_errors`（最多 3 条）、`elapsed_s`。

**`complete` 帧字段**（`src/agent/aiops/events.py:282-309`）：`type`、`stage`、`message`、`response`、`hypothesis_space[]`、`sidebar_branches[]`、`belief_history[]`、`evidence_source_availability[]`，以及可选 `thread_id`、`diagnosis`、`investigation`。

**`pending_terminal_approval` 帧字段**（`src/agent/aiops/graph.py:396-407`）：`type`、`stage`、`thread_id`、`request_id`、`session_id`、`command`、`expires_at`、`termcp_ui_url`、`message`。

### 1.3 端点表（7 个，全部在 `/api/v1/aiops` 前缀下）

| 方法 | 路径 | 用途 | 关键约束 | source |
|---|---|---|---|---|
| POST | ``（即 `/api/v1/aiops`） | 提交诊断，SSE | `terminal_enabled` 与服务端开关不一致 → 503 | `src/api/routers/aiops.py:40-120` |
| GET | `/runs/{thread_id}` | 读运行状态与报告 | 需 run 存在且属于本人；默认配置下一律 404 | `src/api/routers/aiops.py:132-143` |
| POST | `/runs/{thread_id}/continue` | 续跑（只处理 `pending_terminal`） | `pending_review` → 409；其它状态 → 409 | `src/api/routers/aiops.py:146-166` |
| GET | `/runs/{thread_id}/steps` | 步级快照 | 默认开关关闭 → `total: 0` | `src/api/routers/aiops.py:169-181` |
| GET | `/runs/{thread_id}/evidence` | 证据台账 | 返回 `can_read_raw` | `src/api/routers/aiops.py:184-190` |
| GET | `/runs/{thread_id}/evidence/{evidence_id}` | 单条证据 | 非 admin/auditor 剥掉 `raw_ref` | `src/api/routers/aiops.py:193-206` |
| GET | `/targets/{target_id}/status` | 探针注册状态 | 只认 `settings.PROBE_TARGET_ID` | `src/api/routers/aiops.py:209-218` |

除第 1 个之外，后 6 个端点的数据/权限语义属 `aiops-audit` 模块，本文只登记到"诊断链路会写入什么"为止。

### 1.4 功能单元（FEAT-DIAG-\*，供 `cases/aiops-diagnosis.json` 的 `feature_id` 解析）

| feature_id | 用户目标 | 主入口 | requirement_refs | 源码锚点 |
|---|---|---|---|---|
| FEAT-DIAG-001 | 一句话提交诊断并看着进度跑完 | `/aiops` 页输入框 + `POST /api/v1/aiops` | REQ-DIAG-001, REQ-DIAG-002 | `src/api/routers/aiops.py:40-120`、`frontend/src/views/AIOps.vue:794-827` |
| FEAT-DIAG-002 | 计划短、可执行、不乱编名字 | planner 节点 | REQ-DIAG-004, REQ-DIAG-005 | `src/agent/aiops/planner.py:303-418` |
| FEAT-DIAG-003 | 报告每句话都能挂到证据上 | `reporting.finalize_report` | REQ-DIAG-006, REQ-DIAG-007 | `src/agent/aiops/reporting.py:133-422` |
| FEAT-DIAG-004 | 某个工具服务挂了别的还能用 | `load_agent_tools` → `load_mcp_tools_safe` | REQ-DIAG-008 | `src/agent/mcp_client.py:85-134`、`src/agent/aiops/tools.py:94-132` |
| FEAT-DIAG-005 | 缺哪类证据要写在报告里 | 报告 `## 证据来源` 段 | REQ-DIAG-009 | `src/agent/aiops/evidence_sources.py:49-126` |
| FEAT-DIAG-006 | 刷新/重启后还能查到这次诊断 | 受管运行 + sqlite checkpoint | REQ-DIAG-010 | `src/agent/aiops/graph.py:106,140-156,348-359` |
| FEAT-DIAG-007 | 报告草稿先给我看一眼 | human_review 节点 | REQ-DIAG-011 | `src/agent/aiops/human_review.py:23-52` |
| FEAT-DIAG-008 | 受控终端每条命令都要我批 | terminal_review 节点 + `/continue` | REQ-DIAG-012 | `src/agent/aiops/graph.py:165-228`、`src/agent/aiops/termcp_tools.py:43-83` |
| FEAT-DIAG-009 | 知道这次诊断花了多少 | `usage` 帧 | REQ-DIAG-013 | `src/api/routers/aiops.py:103-118` |

---

## 2. 规则

### RULE-DIAG-001 空输入只在图层拒绝，HTTP 状态仍是 200
- **要求**：`query` 为空串时，路由层不得报 4xx；必须由 `execute` 产出 `{"type":"error","stage":"validation_error","message":"诊断输入不能为空,请描述当前遇到的故障现象"}`，且**不建 run、不调模型**。
- **适用条件**：`POST /api/v1/aiops`，`query` 为 `""` 或全空白。
- **可观察**：HTTP 200 + SSE 一帧 `error`，`stage` 恰为 `validation_error`；`aiops_runs` 无新增行。
- **source**：`src/api/routers/aiops.py:35`、`src/agent/aiops/graph.py:341-343`、`src/agent/aiops/graph.py:364-369`
- **requirement_refs**：REQ-DIAG-001　**basis**：observed

### RULE-DIAG-002 终端开关不一致必须前置拒绝，不建 run
- **要求**：`terminal_enabled=true` 且 `settings.TERMCP_ENABLED=false` 时，在进入图之前抛 `HTTPException(503, "受控终端诊断尚未启用")`。
- **适用条件**：默认配置（`TERMCP_ENABLED=False`）下的任意登录用户。
- **可观察**：HTTP **503**，`detail` 恰为「受控终端诊断尚未启用」；数据库中无该次 run；没有 SSE 帧。
- **source**：`src/api/routers/aiops.py:55-56`、`src/settings.py:213`
- **requirement_refs**：REQ-DIAG-012　**basis**：observed

### RULE-DIAG-003 事件类型全集 11 种，`data.type` 才是判别字段
- **要求**：SSE 帧的 `event` 字段恒为 `"message"`；事件种类一律看 `data.type`。全集为 `plan / step_complete / status / draft / report / pending_review / complete / error / evidence`（`events.py` 的 9 个常量）+ `usage`（路由层直出）+ `pending_terminal_approval`（graph 层直出）。
- **适用条件**：所有 `POST /api/v1/aiops` 与 `/continue` 响应。
- **可观察**：任一帧 `event` 字段都是 `message`；`data.type` 取值落在上述 11 个之内。
- **source**：`src/agent/aiops/events.py:66-86`、`src/api/routers/aiops.py:76-79,113-116`、`src/agent/aiops/graph.py:396-407`
- **requirement_refs**：REQ-DIAG-002　**basis**：observed

### RULE-DIAG-004 流结束必推 `usage`，且计量失败不影响诊断
- **要求**：`finally` 中必须打三组指标并推一帧 `usage`（含 `elapsed_s`）；计量过程异常只记 warning，不得改变 `final_result`、不得中断已完成的诊断。
- **适用条件**：每次 `POST /api/v1/aiops`（含异常结束）。
- **可观察**：流的最后一帧是 `{"type":"usage", …}`；`llm_calls`/`input_tokens`/`output_tokens`/`cost_cny_estimated`/`elapsed_s` 均存在；指标 `aiops_diagnosis_total{result}` 自增。
- **source**：`src/api/routers/aiops.py:95-118`、`src/utils/token_meter.py:132-141`
- **requirement_refs**：REQ-DIAG-013　**basis**：observed

### RULE-DIAG-005 planner 计划长度硬上限 6，超长截断
- **要求**：模型返回的计划超过 6 步时截断到前 6 步并记 warning；不得透传超长计划。
- **适用条件**：planner 正常调用模型返回。
- **可观察**：`plan` 事件的 `plan` 数组长度 ≤ 6；日志出现「计划 N 步超过上限 6,截断」。
- **source**：`src/agent/aiops/planner.py:39,392-394`
- **requirement_refs**：REQ-DIAG-004　**basis**：observed

### RULE-DIAG-006 业务目标未唯一核实时不调模型、直接出 unlocated
- **要求**：`resolve_target` 返回 `ambiguous` / `unmatched` / `invalid_catalog` 时，直接返回 `plan=[]` + 「业务目标尚未唯一核实…」+ `diagnosis(kind='unlocated')`，**不得调用模型**。
- **适用条件**：`DIAGNOSTIC_TARGET_CATALOG` 无法唯一匹配用户描述的服务/入口。
- **可观察**：`complete` 帧的 `plan` 为空、`response` 含「业务目标尚未唯一核实」、`diagnosis.kind == 'unlocated'`；`usage.llm_calls == 0`。
- **source**：`src/agent/aiops/planner.py:362-370`
- **requirement_refs**：REQ-DIAG-004　**basis**：observed

### RULE-DIAG-007 planner 异常兜底固定 3 步
- **要求**：planner 内模型调用抛异常时，记 `logger.exception("[planner] 生成计划失败,用默认计划")` 并返回固定三步「收集相关指标和日志 / 分析数据定位问题 / 生成诊断报告」。
- **适用条件**：模型不可用、结构化输出解析失败。
- **可观察**：`plan` 事件恰为这 3 条文案。
- **source**：`src/agent/aiops/planner.py:408-418`
- **requirement_refs**：REQ-DIAG-004　**basis**：observed

### RULE-DIAG-008 报告证据引用校验失败 → 降级为 failed 记录 + 保守正文，不崩溃
- **要求**：`build_bundle` 发现 `evidence_id` 不在记录内、或 `quote` 不是该证据 payload 的子串时抛 `ValueError('report_source_reference_invalid')`；`finalize_report` 必须捕获它，把 `record.status` 置 `failed`、`fallback_reason` 置 `report_source_reference_invalid`，并把正文整段替换为「报告证据核验未通过，不能可靠整理处置建议。调查原结果和证据保留在详情，需核对引用后再处理。」；**流仍以 `complete` 结束**。
- **适用条件**：`diagnosis.kind ∈ {localized_fault, confirmed_cause}` 且无 `investigation_failure`。
- **可观察**：`complete` 帧 `response` 恰为上述文案；run 的 `report` 字段（落库版本）中 `status="failed"`、`fallback_reason="report_source_reference_invalid"`；HTTP 仍 200，无 `error` 事件。
- **source**：`src/agent/aiops/reporting.py:138-145,403-405`
- **requirement_refs**：REQ-DIAG-006　**basis**：observed

### RULE-DIAG-009 `managed_run` 由三开关决定，默认不建 run、用内存 checkpointer
- **要求**：仅当 `ENABLE_HITL or TERMCP_ENABLED or PROBE_ENABLED` 为真时建 `aiops_runs` 行并使用 `AsyncSqliteSaver`；否则复用进程内 `MemorySaver`，不落任何 run 行。
- **适用条件**：所有诊断提交。
- **可观察**：默认配置下 `GET /api/v1/aiops/runs/{thread_id}` 返回 **404「诊断不存在」**，`aiops_runs` 无新增行，`data/aiops_checkpoints.sqlite` 不产生该 thread 的 checkpoint；三开关任一为真后同一请求返回 200 且 `status` 存在。
- **source**：`src/agent/aiops/graph.py:106,148-156,348-359`、`src/settings.py:187,213,220`
- **requirement_refs**：REQ-DIAG-010　**basis**：observed

### RULE-DIAG-010 默认配置下诊断不可跨重启恢复
- **要求**：默认配置（`ENABLE_HITL` / `TERMCP_ENABLED` / `PROBE_ENABLED` 全 `False`）下，重启后端不得恢复任何诊断状态。
- **适用条件**：默认配置。
- **可观察**：重启前拿到的 `thread_id` 重启后 `GET /runs/{id}` → 404；受管配置下同样操作返回 200 且 `report` 与重启前一致、`usage` 无新增模型调用。
- **source**：`src/agent/aiops/graph.py:106,148-156`、`docs/aiops-run-store.md:55`
- **requirement_refs**：REQ-DIAG-010　**basis**：observed

### RULE-DIAG-011 HITL 挂起只有图内 interrupt，没有 HTTP 审批端点
- **要求**：`pending_review` 状态下，平台内**不得**存在任何 HTTP 端点可写入审批结论；`/continue` 对该状态必须返回 409「此诊断等待的不是 Termcp 命令审批」；`aiops_approvals` 表不得有新增行。
- **适用条件**：`ENABLE_HITL=true` 且图停在 `human_review`。
- **可观察**：`POST /runs/{id}/continue` → **409** 且 detail 恰为「此诊断等待的不是 Termcp 命令审批」；枚举 `src/api/routers/aiops.py` 无审批写入路由；`aiops_approvals` 行数不变。
- **source**：`src/api/routers/aiops.py:146-166`、`src/agent/aiops/run_store.py:98-131`
- **requirement_refs**：REQ-DIAG-011　**basis**：observed

### RULE-DIAG-012 HITL 挂起没有超时自愈（`HITL_TTL_SECONDS` 无消费者）
- **要求**：`HITL_TTL_SECONDS` 只作为配置项存在，`src/` 下不得有任何读取点；因此挂起不会超时落库。
- **适用条件**：`ENABLE_HITL=true`。
- **可观察**：`grep -rn "HITL_TTL_SECONDS" src/` 只命中 `src/settings.py:189`；挂起超过 600 秒后 `GET /runs/{id}` 的 `status` 仍为 `pending_review`。
- **source**：`src/settings.py:188-189`
- **requirement_refs**：REQ-DIAG-011　**basis**：observed

### RULE-DIAG-013 Termcp 审批校验 8 条，且只在可重试失败时保留 run
- **要求**：`verify_terminal_approval` 的 8 条校验按序执行；**只有**「审批接口不可达（503）」与「仍待审批（409）」两类 `terminal=False`，不把 run 标 failed；其余 `terminal=True` 的失败必须先 `mark_failed` 再抛出相同状态码。
- **适用条件**：`run.status == pending_terminal` 且调用 `/continue`。
- **可观察**：审批仍在 pending → 409「命令仍待 Termcp UI 审批」且 run 仍 `pending_terminal`；审批已过期 → 410「审批未通过或已过期，诊断已停止」且 run 变 `failed`；Termcp 接口不可达 → 503 且 run 仍 `pending_terminal`。
- **source**：`src/agent/aiops/termcp_tools.py:43-83`、`src/api/routers/aiops.py:150-155`
- **requirement_refs**：REQ-DIAG-012　**basis**：observed

### RULE-DIAG-014 `/continue` 没有驳回语义
- **要求**：`/continue` 不读请求体；`decision` 恒为 `{"action":"approve"}`。
- **适用条件**：任意状态下调用 `/continue`。
- **可观察**：请求体传 `{"action":"reject","instruction":"…"}` 与传空 body 的行为完全一致；驳回只能来自 Termcp UI（由 RULE-DIAG-013 第 7 条兜住）。
- **source**：`src/api/routers/aiops.py:146-166`
- **requirement_refs**：REQ-DIAG-012　**basis**：observed

### RULE-DIAG-015 MCP 两层降级，任何情况都不抛异常
- **要求**：整体加载失败 → 逐服务加载；部分成功返回成功工具 + `部分服务不可用: …`；全部失败返回空列表 + `全部 MCP 服务不可用: …`（或「无配置」）。`load_mcp_tools_safe` 不得向外抛异常。
- **适用条件**：任一 MCP 服务不可用。
- **可观察**：停掉某个 MCP 服务后诊断仍能跑完；`load_mcp_tools_safe()` 返回二元组而非抛错；无工具时报告含「未取得真实数据」类表述。
- **source**：`src/agent/mcp_client.py:85-134`、`src/agent/aiops/executor.py:81-86`
- **requirement_refs**：REQ-DIAG-008　**basis**：observed

### RULE-DIAG-016 `PROBE_ENABLED` 或 Termcp 启用时移除 4 个原生网络探测工具
- **要求**：`PROBE_ENABLED=true` 时从工具清单移除 `check_website` / `check_ports` / `check_service_health` / `check_api_endpoint`；`include_termcp` 且 `TERMCP_ENABLED=true` 时同样移除这 4 个。
- **适用条件**：上述开关任一为真。
- **可观察**：工具清单（`investigation_tool_catalog` 产物或 `plan` 前后的工具列表）不含这 4 个名字；`PROBE_ENABLED=false` 且未启终端时它们存在。
- **source**：`src/agent/aiops/tools.py:108-119`、`src/settings.py:220`
- **requirement_refs**：REQ-DIAG-008　**basis**：observed

### RULE-DIAG-017 `autonomous_investigation` 为真时步数上限不生效
- **要求**：默认策略的 8 步、动态分类策略的 12 步强制收束条件都必须带 `and not autonomous_investigation`；`autonomous_investigation = terminal_enabled or PROBE_ENABLED`。
- **适用条件**：`PROBE_ENABLED=true` 或终端已启用。
- **可观察**：同一症状在默认配置下最多 8 步内收束；打开 `PROBE_ENABLED` 后可以超过 8 步（由调查策略自行决定何时停）。
- **source**：`src/agent/aiops/strategies/default.py:197`、`src/agent/aiops/strategies/dynamic_classification.py:708`、`src/agent/aiops/graph.py:372-383`
- **requirement_refs**：REQ-DIAG-005　**basis**：observed

### RULE-DIAG-018 改判定逻辑前必须先跑零成本回放门禁（confirmed）
- **要求**：任何改动 `src/agent/aiops/strategies/investigation.py` 判定逻辑的提交，必须先在本地跑通 `python -m pytest -q tests/test_recorded_round_replay.py`；CI 必须保留步骤 `Decision-rule gate (recorded paid rounds must not regress)`。四条不变量：曾通过的轮次不得回放失败；039/049 必须被当天规则接受；仍被拒的 041/044/050 必须写明 `blocked_reason`；每轮必须落到终态诊断。
- **适用条件**：改动 `investigation.py` 的判定/校验分支；不适用于纯文案、纯日志、纯测试改动。
- **可观察**：`python -m pytest -q tests/test_recorded_round_replay.py` 退出码 0、零模型调用、约 2 秒；`.github/workflows/tests.yml` 第 46-47 行步骤存在且名字一致。
- **source**：`docs/aiops-goal-handover-20261108.md:186-200`、`.github/workflows/tests.yml:46-47`、`tests/test_recorded_round_replay.py:1`
- **requirement_refs**：REQ-DIAG-007　**basis**：`confirmed`（文档写明了理由「改判定规则不许把已通过的轮次改坏」与适用条件）

### RULE-DIAG-019 报告版本与契约标识固定
- **要求**：报告 `version` 恒为 `1`，`mode` 恒为 `rules`，模型契约标识为 `core-facts-v1`；`kind ∈ {localized_fault, confirmed_cause}` 才构建 bundle。
- **适用条件**：所有出报告的场景。
- **可观察**：`aiops_runs.report`（JSON 文本）中 `version=1`、`mode="rules"`；`input_sha256` / `report_sha256` 存在。
- **source**：`src/agent/aiops/reporting.py:21-22,384-392,420-421`
- **requirement_refs**：REQ-DIAG-006　**basis**：observed

### RULE-DIAG-020 调查失败与"正常跑完但未定位"必须可区分
- **要求**：有 `investigation_failure` 时链路为 `report → error(stage=investigation_failed)`，run 记 `failed`，**不发 `complete`**；`conclusion_level=unlocated` 但无 `investigation_failure` 时链路正常 `complete`、run 记 `completed`。
- **适用条件**：调查策略返回失败分支（`model_output_truncated` / `invalid_model_decision` / `evaluation_budget_exceeded` / `model_request_failed`）。
- **可观察**：前者最后一帧是 `error` 且 `stage="investigation_failed"`、`investigation_failure.code` 有值；后者最后一帧是 `complete`、`diagnosis.conclusion_level == "unlocated"`。
- **source**：`src/agent/aiops/graph.py:318-330,391`、`src/agent/aiops/strategies/investigation.py:3756-3799`、`docs/aiops-events.md:78`
- **requirement_refs**：REQ-DIAG-005, REQ-DIAG-007　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis | 执行方式 |
|---|---|---|---|---|---|
| ASRT-DIAG-001 | 登录后 `POST /api/v1/aiops` body `{"query":""}` → HTTP **200**，流内出现 `data.type=="error"` 且 `stage=="validation_error"`、`message` 为「诊断输入不能为空,请描述当前遇到的故障现象」；`GET /runs/{thread_id}` 无从获得（无 thread_id 帧），`aiops_runs` 行数不变 | RULE-DIAG-001 | REQ-DIAG-001 | observed | live_api |
| ASRT-DIAG-002 | 默认配置（`TERMCP_ENABLED=false`）下 `POST /api/v1/aiops` body `{"query":"下游超时","terminal_enabled":true}` → HTTP **503**，`detail` 恰为「受控终端诊断尚未启用」；响应 `Content-Type` 非 `text/event-stream`；`aiops_runs` 行数不变 | RULE-DIAG-002 | REQ-DIAG-012 | observed | live_api |
| ASRT-DIAG-003 | 正常诊断一次，收集全部 SSE 帧：每帧 `event=="message"`；`data.type` 序列以 `plan` 开头、以 `complete` 结束，且 `complete` 之前出现过已截帧的 `report`；`data.type` 全部落在 11 种之内 | RULE-DIAG-003 | REQ-DIAG-002 | observed | live_api（**产生模型费用**） |
| ASRT-DIAG-004 | 同一次诊断的最后一帧 `data.type=="usage"`，且同时含 `llm_calls`、`input_tokens`、`output_tokens`、`total_tokens`、`cost_cny_estimated`、`count_errors`、`elapsed_s` 七个键 | RULE-DIAG-004 | REQ-DIAG-013 | observed | live_api |
| ASRT-DIAG-005 | 在 `/aiops` 页提交一次诊断：页面上步骤列表逐条变"已完成"，`[并行]` 前缀**不出现**在步骤文案里；整页不出现「本次诊断消耗」或任何费用数字 | RULE-DIAG-005 | REQ-DIAG-004, REQ-DIAG-013 | observed | live_ui（**产生模型费用**） |
| ASRT-DIAG-006 | 任一次正常诊断的 `plan` 事件里 `len(plan) <= 6`；若模型给出超过 6 条，日志出现「计划 N 步超过上限 6,截断」 | RULE-DIAG-005 | REQ-DIAG-004 | observed | live_api（**产生模型费用**） |
| ASRT-DIAG-007 | 把 `DIAGNOSTIC_TARGET_CATALOG` 配成无法唯一匹配用户描述（如空 `{}` 且用户描述含多个候选）后提交 → `plan`/`complete` 中计划为空、`response` 含「业务目标尚未唯一核实」、`diagnosis.kind=="unlocated"`，且 `usage.llm_calls==0` | RULE-DIAG-006 | REQ-DIAG-004 | observed | controlled_fixture（需预置 catalog） |
| ASRT-DIAG-008 | 构造一条 `quote` 不在证据 payload 内的引用后走 `finalize_report` → `complete` 帧 `response` 恰为「报告证据核验未通过，不能可靠整理处置建议。调查原结果和证据保留在详情，需核对引用后再处理。」；落库 `report` 中 `status=="failed"`、`fallback_reason=="report_source_reference_invalid"`；**不出现** `error` 帧 | RULE-DIAG-008 | REQ-DIAG-006 | observed | controlled_fixture（需注入坏引用） |
| ASRT-DIAG-009 | 默认配置（三开关全 `false`）下跑完一次诊断后，用流里拿到的 `thread_id` 请求 `GET /api/v1/aiops/runs/{thread_id}` → **404**，`detail` 恰为「诊断不存在」；`aiops_runs` 无该 thread 行 | RULE-DIAG-009 | REQ-DIAG-010 | observed | live_api（**产生模型费用**） |
| ASRT-DIAG-010 | 打开 `ENABLE_HITL=true` 重启后端后跑一次诊断 → 同一 `thread_id` 的 `GET /runs/{id}` 返回 **200** 且 `status` 非空；重启后端再请求一次仍 200 且 `report` 内容一致；两次请求期间 `usage` 无新增模型调用（以 `cost.json` 或日志 `llm_calls` 判定） | RULE-DIAG-009, RULE-DIAG-010 | REQ-DIAG-010 | observed | live_api（**产生模型费用**；需改配置重启） |
| ASRT-DIAG-011 | 只读核对三件事同时成立：(a) `src/api/routers/aiops.py` 全文无审批写入路由（7 个路由中无 approve/reject）；(b) `grep -rn "HITL_TTL_SECONDS" src/` 仅命中 `src/settings.py:189`；(c) 路由 docstring 只列 5 种事件而 `events.py` 定义 9 个常量、实际另有 `usage` 与 `pending_terminal_approval` 两类 | RULE-DIAG-011, RULE-DIAG-012, RULE-DIAG-003 | REQ-DIAG-011, REQ-DIAG-002 | observed | static_review |
| ASRT-DIAG-012 | `ENABLE_HITL=true` 下诊断跑到 replanner 出稿 → 流内 `data.type=="draft"`（不是 `report`），随后 `data.type=="pending_review"` 且含 `thread_id`；此时 `GET /runs/{id}` 的 `status=="pending_review"`；`POST /runs/{id}/continue` → **409**，`detail` 恰为「此诊断等待的不是 Termcp 命令审批」；`aiops_approvals` 行数不变 | RULE-DIAG-011 | REQ-DIAG-011 | observed | controlled_fixture（需开 HITL） |
| ASRT-DIAG-013 | `TERMCP_ENABLED=true` 下命中终端命令 → 流内 `data.type=="pending_terminal_approval"` 且含 `request_id`/`command`/`expires_at`/`termcp_ui_url`；此时 `/continue`：Termcp 侧仍 pending → **409**「命令仍待 Termcp UI 审批」且 run 仍 `pending_terminal`；审批过期后 → **410**「审批未通过或已过期，诊断已停止」且 run 变 `failed` | RULE-DIAG-013 | REQ-DIAG-012 | observed | controlled_fixture（需伪造过期审批） |
| ASRT-DIAG-014 | 停掉全部 MCP 服务后提交诊断 → 流正常走到 `complete`（无 `error`）；`complete` 帧 `evidence_source_availability` 中至少一项 `status != "callable"`；报告正文含「未取得真实数据」或「## 证据来源」段 | RULE-DIAG-015 | REQ-DIAG-008, REQ-DIAG-009 | observed | controlled_fixture（制造 MCP 缺席） |
| ASRT-DIAG-016 | `PROBE_ENABLED=true` 重启后端后提交诊断，工具清单中不含 `check_website`/`check_ports`/`check_service_health`/`check_api_endpoint` 四个名字；关掉开关重启后这四个名字重新出现 | RULE-DIAG-016 | REQ-DIAG-008 | observed | static_review（对比两次工具清单输出即可，无需真实探测） |
| ASRT-DIAG-017 | `python -m pytest -q tests/test_recorded_round_replay.py` 退出码 0，输出中无 failed；整个过程零模型调用（耗时约 2 秒量级）；`.github/workflows/tests.yml` 存在名为 `Decision-rule gate (recorded paid rounds must not regress)` 的步骤 | RULE-DIAG-018 | REQ-DIAG-007 | `confirmed` | live_cli |

> 断言编号不连续（001–014、016、017）是有意的：ASRT-DIAG-015 预留给"`evidence` 事件缺 `raw_hash`"这一待决口径（见 §4 第 2 条），在 `specs/questions.md` Q-17 定性前不写判据，避免用未定口径造断言。

---

## 4. 未决（供 `specs/questions.md` 汇总）

1. **`HITL_TTL_SECONDS` 无消费者**（`src/settings.py:189`）：注释承诺与实现不一致。→ Q-13。本模块以 RULE-DIAG-012 记录"当前无超时"这一事实，但"应不应该有超时"是产品决定，未定。
2. **`evidence` 事件缺 `raw_hash`**（`src/agent/aiops/events.py:316-320`）：签名收参数但实体未写入。是漏写还是有意精简，未核实。→ Q-17。因此不写 ASRT-DIAG-015。
3. **HITL 无 HTTP 审批端点 + 审批表无写入方**（`src/api/routers/aiops.py:146-166`、`src/agent/aiops/run_store.py:98-131`）：`approved`/`rejected` 状态不可达。产品上是否要补端点未定，建议 Q-31。
4. **`/continue` 无 reject 分支**（`src/api/routers/aiops.py:156`）：是否要支持平台内驳回未定，建议 Q-33。
5. **`docs/aiops-run-store.md:47` 与代码冲突**（文档说仅 `ENABLE_HITL` 建 run，代码是三开关任一）：建议 Q-32。
6. **前端不渲染 `usage` / `draft` / `pending_review`**（`frontend/src/views/AIOps.vue:715-792`）：是"刻意不展示费用"还是"未做"，未核实，建议 Q-34。
7. **需要 `controlled_fixture` 的断言**：ASRT-DIAG-007（预置 catalog）、008（注入坏引用）、012（开 HITL）、013（伪造过期审批）、014（停 MCP）。这 5 条都要求改配置或注入故障，**执行成本高于普通 live 用例**，且其中 4 条需要真实模型参与才走到目标分支。
8. **`evaluation_mode` 口径**：ASRT-DIAG-003/005/006/009/010 都会**产生模型费用**（每轮约 0.4–0.9 元，`docs/aiops-goal-handover-20261108.md:263`），因此对应用例的 `resource_requirements` 必须写清"需要模型配额与付费授权"；但它们仍是 `binary`（事件顺序/字段存在性可判定），不设"成功率"阈值。
9. **"诊断结论正确率"不写成 binary**：15 轮 10 通过（`docs/aiops-goal-handover-20261108.md:161`）是历史观测，不是当前构建的通过线；任何"准确率"类用例只能 `graded` 或 `measurement`，且不得编造阈值。
10. **`ENABLE_SUPERVISOR` 端点不存在**（`src/settings.py:184-185`）：本模块不含该能力，列入 `platform` 模块问题（Q-14）。
