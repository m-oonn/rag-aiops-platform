# spec · aiops-audit（运行记录 / 证据 / 审计 / 探针）

- 模块：`aiops-audit`，规则前缀 `RULE-AUDIT-`，断言前缀 `ASRT-AUDIT-`，功能前缀 `FEAT-AUDIT-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（`main`，2026-11-11）
- 需求依据：`requirements/modules/aiops-audit.md`（REQ-AUDIT-001 ~ REQ-AUDIT-010）
- 所有 `source` 均为 `完整相对路径:行号`；`basis=observed` = 读源码核实。
- **本模块没有 `confirmed` 级规则与断言**：没有一条产品文档为这些审计能力写明了"为什么这么做 + 什么条件下这么做"。因此**任何断言都不得用于判正式 PASS/FAIL**，只能作为事实核对清单。
- 流程引用：`FLOW-AUDIT`（运行记录 / 证据读取 / 步快照）、`FLOW-DIAG-RESUME`（挂起后的审批校验，审计侧只能观察到状态判定）。

---

## 1. 交互与接口状态

### 1.1 用户动作 → 接口映射

| 用户动作 | 前端判定 | 接口 | 输出形态 | source |
|---|---|---|---|---|
| 刷新页面后恢复上次诊断 | `localStorage.aiops_pending_thread` 或 `aiops_last_thread` 存在 | `GET /runs/{thread_id}` | JSON；`pending_terminal` 恢复审批卡，否则展示 `report`/`diagnosis` | `frontend/src/views/AIOps.vue:856-890` |
| 点「刷新证据状态」 | 有 `currentThreadId` | `GET /runs/{thread_id}/evidence` | JSON 含 `evidence[]` 与 `can_read_raw` | `frontend/src/views/AIOps.vue:395`、`:622-642` |
| 打开某条证据的「查看现场证据（脱敏）」 | `canReadRaw && item.raw_available` | `GET /runs/{thread_id}/evidence/{evidence_id}` | JSON，含 `raw`（admin/auditor） | `frontend/src/views/AIOps.vue:415`、`:657-670` |
| 证据源卡片加载 | 渲染证据源列表时 | `GET /targets/{target_id}/status` | JSON，含 `status`/`stale` | `frontend/src/views/AIOps.vue:645` |
| 点「继续诊断」 | `pendingApproval` 非空 | `POST /runs/{thread_id}/continue` | SSE 或 409/410/503 | `frontend/src/views/AIOps.vue:829-854` |
| 查看步级快照 | **前端没有入口** | `GET /runs/{thread_id}/steps` | JSON `{total, steps}` | `src/api/routers/aiops.py:169-181` |

> 最后一行的重点是：`/steps` 只有后端端点，前端 `AIOps.vue` 全文没有引用 `/steps`（`frontend/src/views/AIOps.vue` 无该字符串），所以即使打开 `ENABLE_STEP_SNAPSHOTS`，页面上也看不到。

### 1.2 请求/响应契约

**`GET /runs/{thread_id}`**（`src/api/routers/aiops.py:132-143`）

| 字段 | 来源 | 说明 |
|---|---|---|
| `thread_id` | `aiops_runs.thread_id` | 与提交时流里的 `thread_id` 一致 |
| `status` | `aiops_runs.status` | 7 个常量之一（见 RULE-AUDIT-016） |
| `report` | `aiops_runs.report` | 落库的报告文本；`mark_failed` 时缺省写 error 文本 |
| `terminal_approval` | `aiops_runs.terminal_approval` | 非 dict 时归一为 `null` |
| `termcp_ui_url` | `settings.TERMCP_UI_URL` | **仅当 `terminal_approval` 非空才给值**，否则 `null`（`src/api/routers/aiops.py:141`） |
| `diagnosis` / `investigation` / `investigation_failure` | 持久 checkpoint | 来自 `run_details`（`src/agent/aiops/graph.py:140-146`） |

**错误码约定（6 个审计端点通用）**

| 场景 | 状态码 | detail |
|---|---|---|
| `thread_id` 不匹配 `[A-Za-z0-9_.-]{1,64}` | 400 | `thread_id 非法` |
| run 不存在 / 不属于当前用户 | 404 | `诊断不存在` |
| `evidence_id` 不匹配 `ev-[A-Za-z0-9]{16,80}` | 400 | `evidence_id 非法` |
| 证据行不存在或不属于该 run | 404 | `证据不存在` |
| `target_id` 不匹配 `[A-Za-z0-9_.-]{1,128}` | 400 | `target_id 非法` |
| `target_id` 不是配置里那一个 | 404 | `目标不存在` |
| 该 target 从未注册过 | 404 | `目标尚未注册` |
| `/continue` 时 run 处于 `pending_review` | 409 | `此诊断等待的不是 Termcp 命令审批` |
| `/continue` 时 run 处于其它状态 | 409 | `诊断当前不处于可续跑状态` |

### 1.3 端点表

| 方法 | 路径 | 鉴权 | 是否要求 run 存在 | source |
|---|---|---|---|---|
| GET | `/api/v1/aiops/runs/{thread_id}` | 登录 | 是（否则 404） | `src/api/routers/aiops.py:132-143` |
| POST | `/api/v1/aiops/runs/{thread_id}/continue` | 登录 | 是 + 状态必须 `pending_terminal` | `src/api/routers/aiops.py:146-166` |
| GET | `/api/v1/aiops/runs/{thread_id}/steps` | 登录 | 是（否则 404），但结果可为空 | `src/api/routers/aiops.py:169-181` |
| GET | `/api/v1/aiops/runs/{thread_id}/evidence` | 登录 | 是 | `src/api/routers/aiops.py:184-190` |
| GET | `/api/v1/aiops/runs/{thread_id}/evidence/{evidence_id}` | 登录（角色影响返回字段） | 是 | `src/api/routers/aiops.py:193-206` |
| GET | `/api/v1/aiops/targets/{target_id}/status` | 登录 | **否**（不查 run） | `src/api/routers/aiops.py:209-218` |

`/targets/{target_id}/status` 是 7 个端点里唯一不经过 `_owned_run` 的，因此**任何登录用户都能查探针状态**，只被 `PROBE_TARGET_ID` 白名单限制到一台机器。

### 1.4 功能单元（FEAT-AUDIT-\*，供 `cases/aiops-audit.json` 的 `feature_id` 解析）

| feature_id | 用户目标 | 主入口 | requirement_refs | 源码锚点 |
|---|---|---|---|---|
| FEAT-AUDIT-001 | 刷新后能查回这次诊断的状态与结论 | `GET /runs/{thread_id}` | REQ-AUDIT-001, REQ-AUDIT-002, REQ-AUDIT-003 | `src/api/routers/aiops.py:132-143`、`frontend/src/views/AIOps.vue:856-890` |
| FEAT-AUDIT-002 | 看每一步的决策与观测快照 | `GET /runs/{thread_id}/steps` | REQ-AUDIT-004 | `src/api/routers/aiops.py:169-181`、`src/agent/aiops/graph.py:292-296` |
| FEAT-AUDIT-003 | 逐条核对报告引用了哪些现场证据 | `GET /runs/{thread_id}/evidence` | REQ-AUDIT-005 | `src/api/routers/aiops.py:184-190` |
| FEAT-AUDIT-004 | 审计/管理员取原始证据文件 | `GET /runs/{thread_id}/evidence/{evidence_id}` | REQ-AUDIT-006, REQ-AUDIT-007 | `src/api/routers/aiops.py:193-206`、`src/agent/aiops/evidence_reader.py:38-79` |
| FEAT-AUDIT-005 | 确认现场探针是活的 | `GET /targets/{target_id}/status` | REQ-AUDIT-008 | `src/api/routers/aiops.py:209-218` |
| FEAT-AUDIT-006 | 重启后端后仍能读到同一诊断 | 受管运行 + 持久 checkpoint | REQ-AUDIT-001, REQ-AUDIT-003 | `src/agent/aiops/graph.py:140-156` |
| FEAT-AUDIT-007 | 知道哪些审计数据会自己过期 | 探针基线保留策略 | REQ-AUDIT-010 | `src/agent/aiops/run_store.py:300-339` |
| FEAT-AUDIT-008 | 知道审计面上哪些事查不到 | 审批 / 费用 / 续传缺口 | REQ-AUDIT-009 | `src/agent/aiops/run_store.py:98-131`、`docs/aiops-run-store.md:55` |

---

## 2. 规则

### RULE-AUDIT-001 运行记录仅在受管运行时创建
- **要求**：只有当 `ENABLE_HITL or TERMCP_ENABLED or PROBE_ENABLED` 为真时才 `create_run` 写 `aiops_runs`；否则只复用进程内 `MemorySaver`，不写任何 run 行。
- **适用条件**：每次诊断提交。
- **可观察**：默认配置下拿流里的 `thread_id` 请求 `GET /runs/{id}` → 404「诊断不存在」，`aiops_runs` 无该行；三开关任一为真后同一请求 → 200。
- **source**：`src/agent/aiops/graph.py:348-359`、`src/agent/aiops/graph.py:106`、`src/settings.py:187`
- **requirement_refs**：REQ-AUDIT-001　**basis**：observed

### RULE-AUDIT-002 `thread_id` 格式先于存在性校验
- **要求**：`_owned_run` 必须**先**用 `re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", thread_id)` 校验格式并返回 400，**再**查库返回 404；不能先查库。
- **适用条件**：所有带 `{thread_id}` 的端点（`/runs/{id}`、`/continue`、`/steps`、`/evidence`、`/evidence/{eid}`）。
- **可观察**：`GET /runs/中文id` → **400「thread_id 非法」**（不是 404）；`GET /runs/abcdef` → 404「诊断不存在」。
- **source**：`src/api/routers/aiops.py:123-129`
- **requirement_refs**：REQ-AUDIT-003　**basis**：observed

### RULE-AUDIT-003 归属不符与不存在同码同文案
- **要求**：run 不存在、或 `run.user_id != user.id`，都必须返回 **404「诊断不存在」**，不得区分。
- **适用条件**：任意登录用户访问他人 `thread_id`。
- **可观察**：用他人 `thread_id` 请求 → 404，`detail` 与不存在的 id 完全一致；无法据此枚举有效 id。
- **source**：`src/api/routers/aiops.py:126-128`
- **requirement_refs**：REQ-AUDIT-003　**basis**：observed

### RULE-AUDIT-004 checkpoint 归属校验由调用方负责，函数内部不校验
- **要求**：`AIOpsService.run_details(thread_id)` 不得自带归属校验；调用方必须先 `_owned_run` 再调它。
- **适用条件**：`GET /runs/{thread_id}`。
- **可观察**：`run_details` 的 docstring 明写 "Caller must check run ownership before reading its checkpoint"；函数体内无 user 参数。
- **source**：`src/agent/aiops/graph.py:140-146`、`src/api/routers/aiops.py:134-142`
- **requirement_refs**：REQ-AUDIT-003　**basis**：observed

### RULE-AUDIT-005 步快照端点默认返回 `total: 0` 而不是报错
- **要求**：`GET /runs/{id}/steps` 在 `ENABLE_STEP_SNAPSHOTS=false` 或无记录时必须返回 HTTP 200 + `{"thread_id", "total": 0, "steps": []}`，不得 404、不得 500。
- **适用条件**：默认配置。
- **可观察**：受管运行（run 存在）下 `total == 0`、`steps == []`；若 run 不存在仍先 404。
- **source**：`src/api/routers/aiops.py:169-181`、`src/settings.py:154`
- **requirement_refs**：REQ-AUDIT-004　**basis**：observed

### RULE-AUDIT-006 证据列表按 `user_id` 过滤且不含 `raw_ref`
- **要求**：`list_evidence(thread_id, user_id)` 在 `user_id is not None` 时必须追加 `AiopsEvidence.user_id == user_id` 过滤；返回的每条字典**不得**包含 `raw_ref` 键。
- **适用条件**：`GET /runs/{id}/evidence`。
- **可观察**：响应 `evidence[*]` 的键集合不含 `raw_ref`；只有该 user 自己产生的行出现在列表里（端点本身已传 `current_user.id`）。
- **source**：`src/agent/aiops/run_store.py:245-257`、`src/api/routers/aiops.py:188`
- **requirement_refs**：REQ-AUDIT-005　**basis**：observed

### RULE-AUDIT-007 `fresh` 是读取时算出来的，不是落库字段
- **要求**：`fresh` 必须由 `fresh_until > now` 实时计算；`fresh_until` 在写入时取 `collected_at + ttl_seconds`，默认 `ttl_seconds=180`。
- **适用条件**：`list_evidence` 与 `get_evidence`。
- **可观察**：同一条证据在 180 秒前查 `fresh=true`，180 秒后查 `fresh=false`，但数据库行不变（只有 `fresh_until` 一个字段）。
- **source**：`src/agent/aiops/run_store.py:223`、`src/agent/aiops/run_store.py:238`、`src/agent/aiops/run_store.py:254`、`src/agent/aiops/run_store.py:273`
- **requirement_refs**：REQ-AUDIT-005　**basis**：observed

### RULE-AUDIT-008 `raw_ref` / `raw` 只给 admin 与 auditor
- **要求**：`include_raw` 与是否剥除 `raw_ref` 都必须由 `role in {"admin", "auditor"}` 决定；非该角色一律 `row.pop("raw_ref", None)`。
- **适用条件**：`GET /runs/{id}/evidence/{evidence_id}`。
- **可观察**：`role=user` 的响应无 `raw_ref`、无 `raw`；`role=auditor` 的响应有 `raw_ref`（可能还有 `raw`）；两种角色的 `can_read_raw` 在列表端点分别为 `false` / `true`。
- **source**：`src/api/routers/aiops.py:190`、`src/api/routers/aiops.py:198-205`、`src/agent/aiops/run_store.py:274-278`
- **requirement_refs**：REQ-AUDIT-006　**basis**：observed

### RULE-AUDIT-009 `evidence_id` 格式先于查库
- **要求**：`evidence_id` 不匹配 `ev-[A-Za-z0-9]{16,80}` 时返回 **400「evidence_id 非法」**，且必须发生在 `get_evidence` 之前。
- **适用条件**：`GET /runs/{id}/evidence/{evidence_id}`。
- **可观察**：`GET .../evidence/ev-123` → 400（长度不足 16），不是 404。
- **source**：`src/api/routers/aiops.py:196-197`
- **requirement_refs**：REQ-AUDIT-006　**basis**：observed

### RULE-AUDIT-010 原始证据读取的 8 道护栏与 3 个异常文本
- **要求**：`read_run_evidence` 必须依次满足：run 归属 → 有 `raw_ref` → 路径非符号链接、父级无 reparse point、父目录等于 `PROBE_EVIDENCE_DIR` 解析结果、文件名等于 `{evidence_id}.json`、大小 ≤ 1 MB → 打开后复核真实路径 → 读取不超过 1 MB → 完整性六项比对。异常文本固定为 `invalid evidence identity` / `invalid evidence page` / `invalid literal query` / `evidence unavailable for this run` / `unsafe evidence reference` / `opened evidence escaped storage` / `evidence exceeds stored size limit` / `evidence integrity check failed`。
- **适用条件**：任何调用 `read_run_evidence` 或 `read_run_evidence` 工具的路径。
- **可观察**：把 `raw_ref` 指向 `PROBE_EVIDENCE_DIR` 之外的文件 → `PermissionError('unsafe evidence reference')`；篡改文件内容 → `ValueError('evidence integrity check failed')`。
- **source**：`src/agent/aiops/evidence_reader.py:13-19`、`src/agent/aiops/evidence_reader.py:38-79`
- **requirement_refs**：REQ-AUDIT-007　**basis**：observed

### RULE-AUDIT-011 读旧证据必须标 `new_observation: False`
- **要求**：`read_run_evidence` 的返回值必须含 `new_observation: False`，供判定层区分"回读旧证据"与"本轮新采集"。
- **适用条件**：任意证据回读。
- **可观察**：返回字典中 `new_observation` 键存在且值为 `False`；`data_source == "evidence_excerpt"`。
- **source**：`src/agent/aiops/evidence_reader.py:76-79`
- **requirement_refs**：REQ-AUDIT-007　**basis**：observed

### RULE-AUDIT-012 `target_id` 三段校验：格式 → 白名单 → 是否注册
- **要求**：`/targets/{target_id}/status` 必须依次：格式不匹配 → **400「target_id 非法」**；不等于 `settings.PROBE_TARGET_ID` → **404「目标不存在」**；查无记录 → **404「目标尚未注册」**。
- **适用条件**：任意登录用户。
- **可观察**：三个错误文案互不相同，可据此判断是哪种情况；查别的机器名一律 404「目标不存在」（不是 403）。
- **source**：`src/api/routers/aiops.py:209-218`
- **requirement_refs**：REQ-AUDIT-008　**basis**：observed

### RULE-AUDIT-013 探针新鲜度窗口 [-30s, 180s]，读取时算、不写回
- **要求**：`stale = not last_seen or not -30 <= (now - last_seen).total_seconds() <= 180`；`status` 仅在 `row.status == "online"` 时被改写成 `"stale"`；判定结果不得持久化。
- **适用条件**：`get_probe_target` 与 `list_probe_snapshots` 的 `fresh` 计算。
- **可观察**：同一行数据在 181 秒后查询 `stale=true`，但数据库 `probe_targets.status` 仍是 `online`；时钟偏差导致 `last_seen` 在未来 30 秒内仍算新鲜。
- **source**：`src/agent/aiops/run_store.py:291-297`、`src/agent/aiops/run_store.py:336`
- **requirement_refs**：REQ-AUDIT-008　**basis**：observed

### RULE-AUDIT-014 探针基线保留 24 小时
- **要求**：`save_probe_snapshot` 写 `expires_at = collected_at + timedelta(hours=24)` 并顺手删除已过期行；`list_probe_snapshots` 只返回 `expires_at > now`。
- **适用条件**：探针 baseline 上报与读取。
- **可观察**：24 小时后同一 target 的 baseline 不再出现在列表里；`probe_snapshots` 表在下次写入时被清理。
- **source**：`src/agent/aiops/run_store.py:313-323`、`src/agent/aiops/run_store.py:326-339`、`src/database/models.py:332`
- **requirement_refs**：REQ-AUDIT-010　**basis**：observed

### RULE-AUDIT-015 审批表与 `approved`/`rejected` 状态无写入方
- **要求**：`add_approval` / `mark_approved` / `mark_rejected` 必须保持"只有定义、无调用方"的现状（即平台内无法写入审批结论）；不得凭空声称审批闭环可用。
- **适用条件**：审计模块的资料与断言。
- **可观察**：全仓检索 `mark_approved(`、`mark_rejected(`、`add_approval(` 只在 `src/agent/aiops/run_store.py` 里出现定义；`aiops_runs.status` 永不等于这两个值。
- **source**：`src/agent/aiops/run_store.py:98-131`
- **requirement_refs**：REQ-AUDIT-009　**basis**：observed

### RULE-AUDIT-016 状态机 7 个常量，文档只写 6 个
- **要求**：资料必须写 7 个状态常量；同时记录 `models.py:276`、`run_store.py:3`、`docs/aiops-run-store.md:23` 三处均漏 `pending_terminal` 这一事实。
- **适用条件**：所有涉及 run 状态的资料与断言。
- **可观察**：`src/agent/aiops/run_store.py:25-31` 有 7 行常量；三处文档各只有 6 个值。
- **source**：`src/agent/aiops/run_store.py:25-31`、`src/database/models.py:276`、`docs/aiops-run-store.md:23`
- **requirement_refs**：REQ-AUDIT-002　**basis**：observed

### RULE-AUDIT-017 费用不落库、`degraded` 列无写入方
- **要求**：`usage` 数据只随 SSE 帧推一次，不写任何表；`aiops_runs.degraded` 列存在但 `src/` 下无写入点。资料不得声称能从数据库查到费用或降级标记。
- **适用条件**：审计查询能力描述。
- **可观察**：`grep -rn "degraded" src/` 只命中 `src/database/models.py:280`；查完一次诊断后 `aiops_runs.degraded` 仍为 `NULL`；数据库里无任何金额字段。
- **source**：`src/api/routers/aiops.py:113-118`、`src/database/models.py:280`
- **requirement_refs**：REQ-AUDIT-009　**basis**：observed

### RULE-AUDIT-018 没有断线续传，也没有从第 k 步重放
- **要求**：不得声称支持 `Last-Event-ID` 续传或按步重放；`docs/aiops-run-store.md:55` 明确列为"未做（展望）"。
- **适用条件**：任何"断了怎么办"的描述。
- **可观察**：`grep -rn "Last-Event-ID" src/` 无命中；SSE 断开后唯一恢复手段是重新提交一次诊断（会产生新的模型调用与费用）。
- **source**：`docs/aiops-run-store.md:55`、`docs/aiops-events.md:71-74`
- **requirement_refs**：REQ-AUDIT-009　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis | 执行方式 |
|---|---|---|---|---|---|
| ASRT-AUDIT-001 | 默认配置（三开关全 `false`）下跑完一次诊断，用流里的 `thread_id` 请求 `GET /api/v1/aiops/runs/{thread_id}` → **404**，`detail` 恰为「诊断不存在」；`aiops_runs` 表中无该 `thread_id` 行 | RULE-AUDIT-001 | REQ-AUDIT-001 | observed | live_api（**产生模型费用**） |
| ASRT-AUDIT-002 | 打开 `ENABLE_HITL=true` 重启后端后跑一次诊断 → `GET /runs/{id}` 返回 **200**，`status` 落在 7 个常量之内（实际为 `completed` 或 `pending_review`）；再次重启后端后同一请求仍 200 且 `report` 一致 | RULE-AUDIT-001 | REQ-AUDIT-001, REQ-AUDIT-002 | observed | live_api（**产生模型费用**；需改配置重启） |
| ASRT-AUDIT-003 | `GET /api/v1/aiops/runs/中文非法id` → **400**，`detail` 恰为「thread_id 非法」；`GET /api/v1/aiops/runs/deadbeef` → **404**，`detail` 恰为「诊断不存在」。两者状态码不同 | RULE-AUDIT-002 | REQ-AUDIT-003 | observed | live_api |
| ASRT-AUDIT-004 | 用户 A 的 `thread_id` 由用户 B 请求 → **404**，`detail` 与请求一个随机不存在 id 完全相同（两响应 body 逐字节一致） | RULE-AUDIT-003 | REQ-AUDIT-003 | observed | live_api |
| ASRT-AUDIT-005 | 受管运行下，未打开 `ENABLE_STEP_SNAPSHOTS` 时 `GET /runs/{id}/steps` → **200**，`total == 0` 且 `steps` 为空数组；打开该开关重启后再跑一次诊断 → `total > 0` 且每条含 `step_index`/`node`/`payload` | RULE-AUDIT-005 | REQ-AUDIT-004 | observed | controlled_fixture（需开关对比） |
| ASRT-AUDIT-006 | `GET /runs/{id}/evidence` 的每条 `evidence[*]` 键集合不含 `raw_ref`；响应顶层 `can_read_raw` 对 `role=user` 为 `false`、对 `role=auditor` 为 `true` | RULE-AUDIT-006, RULE-AUDIT-008 | REQ-AUDIT-005, REQ-AUDIT-006 | observed | live_api |
| ASRT-AUDIT-007 | `role=user` 请求 `GET /runs/{id}/evidence/{evidence_id}` → 响应**无** `raw_ref` 键、**无** `raw` 键；`role=auditor` 请求同一条 → 响应**有** `raw_ref` | RULE-AUDIT-008 | REQ-AUDIT-006 | observed | live_api |
| ASRT-AUDIT-008 | `GET /api/v1/aiops/runs/{id}/evidence/ev-123` → **400**，`detail` 恰为「evidence_id 非法」（长度不足 16，先于查库）；`.../evidence/ev-0123456789abcdef` 在无该行时 → **404**「证据不存在」 | RULE-AUDIT-009 | REQ-AUDIT-006 | observed | live_api |
| ASRT-AUDIT-009 | 同一条证据在写入后 180 秒内查询 `fresh == true`，180 秒后查询 `fresh == false`；两次查询之间 `aiops_evidence` 行内容不变 | RULE-AUDIT-007 | REQ-AUDIT-005 | observed | controlled_fixture（需等待 180 秒） |
| ASRT-AUDIT-010 | `GET /api/v1/aiops/targets/{坏格式}` → **400**「target_id 非法」；`GET .../targets/other-machine` → **404**「目标不存在」；`GET .../targets/{PROBE_TARGET_ID}` 在从未有探针上报时 → **404**「目标尚未注册」；探针上报后 → **200** 且响应含 `status` 与 `stale` 两键 | RULE-AUDIT-012 | REQ-AUDIT-008 | observed | controlled_fixture（需启停探针） |
| ASRT-AUDIT-011 | 探针最后一次 hello 后 181 秒查询 → `stale == true` 且 `status == "stale"`；同一次查询后直接读 `probe_targets` 表，`status` 列仍为 `online`（判定未写回） | RULE-AUDIT-013 | REQ-AUDIT-008 | observed | controlled_fixture（需等待 181 秒） |
| ASRT-AUDIT-012 | 只读核对四件事同时成立：(a) `grep -rn "mark_approved(\|mark_rejected(\|add_approval(" src/` 只命中 `src/agent/aiops/run_store.py` 的定义行；(b) `grep -rn "HITL_TTL_SECONDS" src/` 只命中 `src/settings.py:189`；(c) `grep -rn "degraded" src/` 只命中 `src/database/models.py:280`；(d) `grep -rn "Last-Event-ID" src/` 无命中 | RULE-AUDIT-015, RULE-AUDIT-017, RULE-AUDIT-018 | REQ-AUDIT-009 | observed | static_review |
| ASRT-AUDIT-013 | `src/agent/aiops/run_store.py:25-31` 共 7 个 `STATUS_` 常量；`src/database/models.py:276` 的注释、`src/agent/aiops/run_store.py:3` 的 docstring、`docs/aiops-run-store.md:23` 三处都只列 6 个值且均缺 `pending_terminal` | RULE-AUDIT-016 | REQ-AUDIT-002 | observed | static_review |
| ASRT-AUDIT-014 | 只读核对证据读取护栏：`src/agent/aiops/evidence_reader.py` 中存在 8 个固定异常文本 `invalid evidence identity`/`invalid evidence page`/`invalid literal query`/`evidence unavailable for this run`/`unsafe evidence reference`/`opened evidence escaped storage`/`evidence exceeds stored size limit`/`evidence integrity check failed`，且返回字典含 `new_observation: False` | RULE-AUDIT-010, RULE-AUDIT-011 | REQ-AUDIT-007 | observed | static_review |

---

## 4. 未决（供 `specs/questions.md` 汇总）

1. **审批闭环缺失**：`mark_approved` / `mark_rejected` / `add_approval` 无调用方，`approved`/`rejected` 状态不可达。要补端点还是彻底删掉这段死代码，未定。建议 Q-31。
2. **`HITL_TTL_SECONDS` 无消费者**（`src/settings.py:189`）：→ Q-13，状态 `resolved_in_docs`。
3. **状态机 6 vs 7**：三处文档漏 `pending_terminal`。→ Q-18，状态 `open`。
4. **`docs/aiops-run-store.md:23` 与代码冲突**（文档说仅 `ENABLE_HITL`，代码是三开关）。建议 Q-32。
5. **`auditor` 不在角色注释里**（`src/database/models.py:14`）：代码判定含 auditor，注释只有 `admin, user, editor`。建议 Q-35。
6. **`aiops_runs.degraded` 列无写入方**（`src/database/models.py:280`）：用途未核实。
7. **`/steps` 端点无前端入口**：`frontend/src/views/AIOps.vue` 全文无 `/steps` 引用，即使打开开关也看不到。→ Q-28。
8. **证据与 run 无清理策略**：`aiops_evidence` 与 `data/aiops-evidence/` 永久累积；探针基线有 24h 但证据没有。是否要加保留期未定。
9. **需要 `controlled_fixture` 的断言**：ASRT-AUDIT-005（开关对比）、009（等 180 秒）、010（启停探针）、011（等 181 秒）。这 4 条都需要改配置、启停进程或等待时钟推进，**执行成本显著高于普通 live 用例**；其中 009/011 还需要能读写数据库以核对"未写回"。
10. **没有任何 `confirmed` 级断言**：本模块的能力全部只有"代码这么写"级别的事实，没有产品文档为它们写明理由。因此这些断言只能做事实核对，不能作为正式验收判据。
11. **`/targets/{id}/status` 不校验 run 归属**（`src/api/routers/aiops.py:209-218`）：任何登录用户都能问这台探针的在线状态。这是有意的便利还是权限过宽，未核实。
