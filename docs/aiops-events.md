# AIOps 诊断事件契约（SSE）

> 版本：2026-10-12（B4 事件契约显式化）
> **单一事实来源**：[src/agent/aiops/events.py](../src/agent/aiops/events.py)（类型常量 + TypedDict 判别联合 + 构造函数）
> 产出链路：`src/agent/aiops/graph.py` → `POST /api/v1/aiops`（SSE；`event: message`，`data: <JSON>`）
> 契约红线：字段与历史版本**逐字段兼容**（本次集中化未改任何字段语义）；新增字段必须可选。

## 事件流顺序

```
plan → step_complete ×N（中途可由 status 提示）→ report / draft
     → [pending_review]（仅 HITL 开启）→ complete
任意阶段异常 → error
```

## 事件目录

| type | stage | 触发时机 | 关键字段 | 前端用途 |
|---|---|---|---|---|
| `plan` | `plan_created` | planner 产出计划 | `plan: string[]` | 渲染计划列表 |
| `step_complete` | `step_executed` | executor 完成一步 | `done / total: int`、`current_step: str`、`remaining_steps: int` | 进度条按 `done/total` 对齐；步骤日志 |
| `status` | `executor` / `replanner` / 其他节点名 | 节点进行中 / 继续执行 | `message`；replanner 附 `remaining_steps` | 状态提示行 |
| `draft` | `draft_ready` | HITL 开启、报告草稿生成 | `report: string` | 审批预览 |
| `report` | `final_report` | 报告生成（非 HITL） | `report: string` | 结果展示 |
| `pending_review` | `pending_review` | HITL 挂起，等待人工审批 | `thread_id: str`、`draft: str` | 审批入口（配合 resume） |
| `complete` | `complete` | 诊断终态 | `response: str` + 4 个元数据数组 | 终态报告 + 可视化 |
| `error` | `error` / `validation_error` / `not_found` | 异常 / 输入校验 / 恢复失败 | `message: str` | 错误提示 |

> **附：`usage` 事件**（API 层附加，非图内事件）——诊断结束后由
> `src/api/routers/aiops.py` 追加推送 `{"type": "usage", ...}`（本次 LLM 调用次数 /
> token 消耗 / 折算费用），前端可选择性展示。字段定义见 `src/utils/token_meter.py` 的 `as_dict()`。

## 字段明细（JSON 示例）

```jsonc
// plan
{"type": "plan", "stage": "plan_created", "role": "planner", "message": "诊断计划已制定,共 4 步", "plan": ["...", "..."]}

// step_complete
{"type": "step_complete", "stage": "step_executed", "role": "executor", "message": "步骤完成 (2/5)",
 "done": 2, "total": 5, "current_step": "确认服务器CPU占用是否偏高", "remaining_steps": 3}

// status（executor 空闲态 / replanner 继续态）
{"type": "status", "stage": "replanner", "role": "replanner", "message": "继续执行剩余步骤，旁开支线 1 条", "remaining_steps": 2}

// report / draft
{"type": "report", "stage": "final_report", "role": "replanner", "message": "诊断报告已生成", "report": "..."}
{"type": "draft", "stage": "draft_ready", "role": "replanner", "message": "报告草稿已生成", "report": "..."}

// pending_review（HITL）
{"type": "pending_review", "stage": "pending_review", "thread_id": "sess-1710000000000", "message": "报告草稿已生成, 等待人工审批", "draft": "..."}

// complete
{"type": "complete", "stage": "complete", "message": "诊断完成", "response": "...",
 "hypothesis_space": [], "sidebar_branches": [], "belief_history": [], "evidence_source_availability": []}

// error
{"type": "error", "stage": "error", "message": "诊断出错: ..."}
{"type": "error", "stage": "validation_error", "message": "诊断输入不能为空,请描述当前遇到的故障现象"}
{"type": "error", "stage": "not_found", "message": "诊断 xxx 不存在或已过期"}
```

## 消费建议

2026-10-23 增加可选 investigation 摘要：自主调查的 replanner status/report/draft 和 complete 事件可携带同一投影。内容包括 candidates（稳定 ID、解释、状态、必要预期、关联证据）、累计 events（保护、到期、改向及理由）、下一检查、鉴别问题、预期观察和阻塞原因。投影来自 investigation_memory.hypothesis_tracking，终态兼容 diagnosis.mechanisms；不包含候选 proposal、观测去重 token 或原始工具返回，并通过现有 redact 脱敏。

GET /api/v1/aiops/runs/{thread_id} 在既有拥有者校验后，从 checkpoint 返回同一 investigation 摘要。旧状态或结构化判断失败时可为空/缺省，不生成机制事件。前端按完整快照替换累计记录，不重复追加；引用仍通过原证据时间线定位，原文权限不变。状态支持必要预期不等于已确认因果，机制未触发不自动判定失败或成功。

2026-10-26投影新增两个可选数组：`observed_findings` 是共享裁决产生的故障发现；`evidence_summaries` 是截至当前业务范围内最新有效Probe观测的简要描述，包含正常观测，最多八条。每条字段为 `evidence_id`、`operation`、`subject`、`collected_at`、`summary`、`status`、`truncated` 和 `error`，不包含原始payload；整个投影经过 `redact`。`status` 用 `observed`、`partial`、`unavailable`、`not_applicable` 描述检查覆盖和适用性，不代表根因判断；`error` 是经过长度限制的错误文本，不能单独证明对象正常或异常。旧checkpoint缺 `status` 时前端继续按旧 `error`/`truncated` 字段兼容展示。摘要记录在调查记忆中，不能假设后续模型输入不变；摘要也不能替代完整证据账本或因果裁决。当前代码24项正式历史输出测试及两场浏览器回放的范围见[浏览器回放验收](investigation-browser-replay-20261026.md)，状态语义另行见[Probe摘要状态与错误边界](probe-summary-semantics-20261026.md)。

- 按 `type` 判别事件（判别联合）；`stage` 用于细分场景（如 error 的三类来源）；
- `complete` 的四个元数据数组**缺省为 `[]`**，消费方勿假设非空；
- `pending_review` 之后调用方应转入审批流程（`AIOpsService.resume` / 实验脚本），事件流在该点暂停；
- 更细的断线续传 / durable cursor（对齐 pi 的会话条目游标）列入后续 B3（步快照）批次。

## 变更纪律

2026-10-28 增加可选 `investigation_failure`，区分正常完成但未定位与模型决策故障导致提前停止。结构为 `{code, message, error_type?}`；code 为 `model_request_failed` 或 `invalid_model_decision`，不传递供应商异常正文。失败链路为 `report → error(stage=investigation_failed)`，不发送 `complete`，也不进入报告审批；report 的存在只表示有可阅读材料。终止 error 同时携带 `thread_id`、`response`、`diagnosis` 与可用调查摘要，方便保留证据及刷新定位。运行记录为 `failed`，报告仍保存；拥有者刷新接口从 checkpoint 返回相同失败标记。正常 `unlocated` 诊断不自动算失败，旧 checkpoint 缺此字段保持兼容。评测分别保存 `has_final_report` 与 `workflow_completed`，失败有文字仍记 incomplete；失败标记与完成事件冲突时拒绝成功评分。

改事件字段 = 改契约。任何字段增删改必须：
1. 更新 `events.py`（构造函数 + TypedDict）与本文件；
2. 跑 `tests/test_aiops_events.py`（快照断言）与全量离线测试；
3. 新字段保持可选（默认值），不破坏既有前端。

2026-10-27摘要覆盖补充：进程覆盖统计缺失保留unknown并标partial，端口/进程区分returned和matched；不回填旧checkpoint。[四类状态串联验收](probe-summary-flow-20261027.md)覆盖正式SSE、重开读取与浏览器显示。
