# 工具部分可用条件下的诊断对照（2026-11-11）

本文记录一次真实付费的**工具可用性对照**：在同一三服务夹具（edge → localapp → downstream）上，用两次同名故障、同一症状、同一模型参数，分别让"知识检索工具与规划参考资料可用"和"完全停用"两种情况各跑一轮，用于第五章「系统测试与结果分析」之（二）"不同工具条件下的诊断效果"。

## 一、授权与花费

| 项 | 值 |
| --- | --- |
| 授权 | 用户选择"补工具不可用场次"，预算 5–10 元 |
| 实际新增 | **32 次模型请求 / 1.800716 元**（18 + 14 次） |
| 累计预留 | 26.847636 → **28.648352 元**（本批上限参数 34.847636） |
| 账单口径 | 全部为**新增预留/估算上界**，`supplier_bill_verified: false`，供应商最终账单未核 |

## 二、条件定义

- 阶段：`--model-stage knowledge-control`。该阶段固定 `set_model_case('downstream_unreachable')`，两种模式（知识可用/停用）经 `secrets.SystemRandom().shuffle` 打乱顺序，逐场串接累计账本。见 `scripts/verify_windows_local_faults.py:1360-1371`。
- 停用侧实际移除了**两样东西**（`scripts/evaluate_windows_probe.py:509-511`）：`args.local_runbooks = None`（规划参考资料）与 `args.knowledge_mcp_url = None`（知识检索 MCP 工具）。因此对照的是"规划参考资料 + 知识工具是否可用"，不是"是否使用知识"。
- 两场都固定 `ENABLE_EXPERIENCE_CONTEXT=false`（`scripts/evaluate_windows_probe.py:508`），经验上下文不参与。
- **工具可用性轴不能与四组机制轴交叉**：`docs/windows-probe-fault-acceptance.md` 要求"机制组禁止搭配 `--knowledge-disabled` 或 knowledge-control 阶段"，`scripts/evaluate_windows_probe.py:203-204` 与 `scripts/verify_windows_local_faults.py:401-403` 都会直接拒绝。因此本轮不标 `mechanism_group`，只按默认机制开关运行。

## 三、执行过程

| 步骤 | 结果 | 目录 |
| --- | --- | --- |
| 免费预检 `--evaluation-preflight` | `ok: true`、`model_calls: 0`、31 个用例全 passed、`ports_released: true` | `runtime/windows-local-faults-7c3e86f09da44018a0b793ba3279d5d3` |
| 第一次付费尝试（上限误传 5） | **被前置条件拒绝，0 次模型调用**，`RuntimeError: prior scenario has exhausted or uncertain cost; stopping` | `runtime/windows-local-faults-d716154caffe4661a912bbcbb281835c`（`cost_records: []`） |
| 第二次付费尝试（上限 34.847636） | exit 0、`ok: true`、两场完成、`owned_processes_stopped: true`、`ports_released: true` | **`runtime/windows-local-faults-65e6e409ec494f28be77f3cb7173b0e2`** |

失败原因记录（供复现者避免同错）：`--budget-limit-cny` 是**累计账本上限**而非单轮上限。上一轮账本 `reserved_cny=26.847636`，传 5 时 `read_cost_ledger(..., for_resume=True, limit_cny=5)` 判定"已耗尽"（`scripts/evaluate_windows_probe.py:361-387`）。

复现命令：

```
.\.venv\Scripts\python.exe scripts\verify_windows_local_faults.py --run-model \
  --model-stage knowledge-control \
  --budget-limit-cny 34.847636 \
  --previous-cost runtime\windows-local-faults-4cddc36563b4402e9bcb46cd9de0b820\model-061d716a232d472d96d03685633bf669\cost.json
```

## 四、两场结果

| 项 | 场 A（知识可用） | 场 B（知识停用） |
| --- | --- | --- |
| 结果目录 | `model-224f932755e84c11a9e118dbeae959b9` | `model-2ee9745b64f24a399e2508d7ee9b5839` |
| 结论层 `report_kind` | `confirmed_cause` | `confirmed_cause` |
| 工作流 | `workflow_completed: true`、`budget_stopped: false` | 同左 |
| 工具调用次数 | 17（全为 `probe_*`） | 13（全为 `probe_*`） |
| 知识 MCP 调用 `knowledge_mcp_calls` | **0** | **0** |
| 模型输入中"运维手册"出现 | 18 个输入文件中 17 个命中 | **0 个命中** |
| 模型输入中列出 `search_knowledge_base` | 有 | 无 |
| 本场请求 / 费用 | **18 次 / 1.119334 元** | **14 次 / 0.681382 元** |
| 耗时 | — | 78.6 秒 |
| 报告长度 | 8243 字符 | 6687 字符 |
| 机械审核 | `passed: true`、`level_matches_scenario: true` | 同左 |
| 能力状态 | `capability_passed: false`、`semantic_status: pending_manual_review` | 同左 |
| 机制审计（场 A） | `opportunities={protection:0, contradiction:1}`、`executed_changes={0,1}`、`completed_executor_steps=9`、`event_counts={contradiction_triggered:1}`、`mechanism_effectiveness_verified: false` | — |
| 端口 | 8185–8189（edge 8186 / localapp 8187 / downstream 8188 / 知识 MCP 8189） | 同左（不含知识 MCP 工具） |

两场结论文字（摘要，原文见各自 `report.txt`）：

- 场 A："诊断结论（已确认直接原因）：downstream 服务在 2026-11-11T07:32:07 收到受控停止请求（file_presence 通道，initiator=unknown）后完成退出（PID 25372，service_exited/shutdown_completed）……localapp 在连接 127.0.0.1:8188 阶段失败（phase=connect、connection_established=false、TimeoutError）……edge 的 503 是连接已建立后收到 localapp 的 503，与 localapp 同源。停止发起者与动机未知。"
- 场 B："诊断结论（已确认直接原因）：localapp（127.0.0.1:8187）本次 503 的直接运行原因：其配置上游 downstream（127.0.0.1:8188）在 2026-11-11T07:34:15 收到 controlled_stop 停止请求后正常退出（shutdown_completed），8188 无监听、配置身份进程缺失，localapp 连接上游失败（phase=connect, connection_established=false）返回 503。不裁决停止发起者、变更者或完整历史。"

## 五、观察与口径限制

1. **两场结论同层同因**，停用侧反而少用 4 次请求、少花 0.44 元。这只说明在本夹具上结论没有因知识工具缺席而改变，**不能**据此宣称"工具降级无害"：单条件两场，样本不支持任何统计结论。
2. **知识工具在两场都未被真正调用**（`knowledge_mcp_calls=0`，场 A 的 17 次调用全是 `probe_*`）。因此本轮实际检验的是"规划参考资料与知识工具**是否可用**"，而不是"用知识 vs 不用知识"。要检验知识工具的实际贡献，需要构造必须依赖它的样本（改夹具或注入知识专属线索），本轮未做，也没有为此改代码。
3. **证据源缺席有记录、但未进入给人看的报告**：两场的 `complete` 事件都带 `evidence_source_availability`（场 B 的 `knowledge: available=false, status=unavailable`），但两场 `report.txt` 里"知识"出现 0 次、"降级"出现 0 次（"缺失"3/4 次、"未知"12/9 次）。即记录层已具备标注能力，结论输出层尚未把"本次缺了哪类证据源"显式写进报告正文。这是第五章可如实引用的实现缺口。
4. **本夹具的"工具正常"本身已是"部分工具不可用"**：两场（以及此前八场真实付费轮次）的 `evidence_source_availability` 都是 `metrics / logs / changes` 与 RAG 侧 `probe` 不可用、`host_probe` 可用、`knowledge` 场 A 可用。所以第五章描述"工具正常条件"时必须限定为"主机 Probe（及知识检索）可用"，不能写成"全部工具可用"。
5. `capability_passed` 仍为 `false`、语义三维未审 → 本文件不产生任何诊断正确率；正确率口径仍以八场人工语义审核（8/8 `correct_localization`）为准，且那 8 场同样只有 2 类故障、每组 2 场。
6. 费用均为预留/估算上界，`supplier_bill_verified: false`，不得当作账单金额。

## 六、材料索引

| 内容 | 路径 |
| --- | --- |
| 成功批次（两场完整证据、账本、检查点、源码快照） | `runtime/windows-local-faults-65e6e409ec494f28be77f3cb7173b0e2/` |
| 免费预检 | `runtime/windows-local-faults-7c3e86f09da44018a0b793ba3279d5d3/` |
| 被前置条件拒绝的尝试（0 模型调用） | `runtime/windows-local-faults-d716154caffe4661a912bbcbb281835c/` |
| 八场人工语义审核结果 | `runtime/review-e2-b1b/review-summary.json`、[八场预实验结果](fault-pair-preexperiment-result-20261110.md) |
| 机制轴与知识条件互斥的约定 | [Windows Probe 故障验收](windows-probe-fault-acceptance.md) |