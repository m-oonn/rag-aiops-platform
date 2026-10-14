# AIOps 运行记录 / 审批 / 步级快照（run_store）

> 版本：2026-10-12（B3 新增 `aiops_step_snapshots`）
> 实现：`src/agent/aiops/run_store.py`（读写封装）；表定义 `src/database/models.py`
> 存储：SQLite（`settings.DATABASE_URL`；测试环境为内存库）
> 纪律：全部写操作 **best-effort**——异常只告警，不阻断诊断主流程（沿用项目降级约定）

## 三张表

### 1. `aiops_runs` —— 诊断运行记录（HITL 支撑）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| thread_id | str unique | 诊断线程 ID（`{session_id}-{毫秒时间戳}`） |
| user_id | int? | 发起用户 |
| query | text | 故障现象原文 |
| status | str(32) | `running` → `pending_review` → `approved` / `rejected` → `completed`；异常 → `failed` |
| report | text? | 最终报告（或挂起中的草稿） |
| degraded | str(64)? | 降级标记 |
| created_at / updated_at | datetime | |

> 仅 `ENABLE_HITL=true` 时创建（`create_run`）；状态常量与状态机见 run_store 模块头。

### 2. `aiops_approvals` —— 人工审批记录（HITL）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| run_id | int | 关联 `aiops_runs.id` |
| reviewer_id | int? | 审批人 |
| action | str(16) | `approve` / `reject` |
| instruction | text? | 审批意见 |
| created_at | datetime | |

### 3. `aiops_step_snapshots` —— 步级快照（B3 新增：可回放 / 可审计）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| thread_id | str(64) idx | 诊断线程 ID（**独立于 HITL**，不依赖 `aiops_runs`） |
| step_index | int | 图内事件序号（0 起，按 `astream(updates)` 顺序；`__interrupt__` 不计数） |
| node | str(32) | `planner` / `executor` / `replanner` / `human_review` |
| payload | text | JSON 摘要：planner=`{plan}`；executor=`{last_step, result_digest(200字)}`；replanner=`{remaining_plan, response_digest(200字)}` |
| created_at | datetime | |

**写入**：`AIOpsService._stream_events` 在 `ENABLE_STEP_SNAPSHOTS=true` 时逐节点落库（默认 **False** = 零开销）。
**读取**：`run_store.list_step_snapshots(thread_id)` → `[{step_index, node, payload, created_at}]`；
**API**：`GET /api/v1/aiops/runs/{thread_id}/steps`（登录用户；thread_id 白名单校验 `[A-Za-z0-9_.-]{1,64}`）。

## 用途与后续

- **回放**：实验 / 答辩时按 `step_index` 复盘每一步的决策与观测（与 SSE 事件流互补：事件流是实时视角，快照是持久视角）；
- **审计**：每步"看到什么、决策了什么"留痕（对齐 pi 会话条目 / durable cursor 思路的轻量版）；
- **未做（展望）**：断线续传（Last-Event-ID 游标）、从第 k 步重放诊断——见《pi 思路全量结合优化方案》第六节。
