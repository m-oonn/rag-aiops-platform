# 延迟类单一故障的两场真实诊断（2026-11-11）

> 目的：补上开题报告技术路线里"设置停机、延迟和配置错误等单一故障"中唯一没有夹具支持的**延迟**类故障，为第五章"不同故障类型下的诊断效果"提供第三组现场证据。
> 本文只记录本轮实际做了什么、花了多少、得到什么，以及不能据此宣称什么。所有数字都来自 `runtime/windows-local-faults-3f6f8bc54dee4fa6868b7b54e295d4fc` 下的记录文件。

## 一、授权与花费

- 授权：用户 2026-11-11 选择"改夹具加延迟类故障 + 再跑 2 场（约 2 元）"，明确同意为此改代码。
- 实际：**2 场、29 次模型请求、1.627330 元**（累计预留 28.648352 → 30.275682 元；本次账本上限传入 31.648352 元，未触发 `budget_stopped`）。
- 每场分列（`summary.json` 的 `cost_scope.this_run`）：

| 场次 | 模型请求 | 本场费用/元 | 累计请求 | 累计预留/元 | 耗时/毫秒 |
| --- | --- | --- | --- | --- | --- |
| 第 1 场（`model-546d2f41262049d19deb4ff4d63508ff`） | 16 | 0.906992 | 810 | 29.555344 | 100045 |
| 第 2 场（`model-befcca8474c74cf283767512cd8d8c46`） | 13 | 0.720338 | 823 | 30.275682 | — |

累计侧仍有 61 条历史请求价格未知（`pricing_unknown_requests: 61`）、`supplier_bill_verified: false`，故累计金额是**预留/峰值上界，不是供应商账单**；本场两条记录的 `pricing_verified` 为 `true`。

## 二、为什么需要新增夹具能力

改动前，夹具只支持停机（`downstream_unreachable`）、配置错误（`application_config_error`）、端点错配（`localapp_wrong_endpoint`）与正常（`normal`）四类。开题报告要求的三类单一故障里，**延迟完全没有注入能力**，第五章只能写"本轮未覆盖延迟"。

延迟与停机的区别不在于"能不能诊断出来"这种笼统判断，而在于**症状链不同**：

| 观测项 | 停机（既有） | 延迟（本轮新增） |
| --- | --- | --- |
| 依赖端口 | 无监听 | 仍在监听 |
| 依赖进程 | 已退出 | 仍存活 |
| 应用侧失败阶段 | 连接未建立（`connection_established=false`） | 连接已建立（`connection_established=true`）、失败在读响应 `receive_headers` |
| 应用侧异常 | `ConnectionRefusedError` / 连接失败 | `TimeoutError`，`timeout_seconds=0.5` |
| 依赖自身日志 | `shutdown_requested` → `service_exited` | `request_completed` 且 `duration_ms ≈ 1200` |

因此延迟必须能产生"连接通、响应慢"的现场，才能检验系统是否把它与"连不上"区分开。

## 三、夹具改动（本轮新增，均为业务外脚本）

1. `scripts/verify_windows_local_faults.py`
   - `serve()` 支持 mode 文件里的 `{"mode": "slow_response", "delay_ms": N}`（`0 < delay_ms <= 5000`，默认 1200），在响应前 `time.sleep`；原有 `max_attempts` 配置注入分支保持不变。
   - `verify_case_state()` 新增 `downstream_slow` 状态断言：入口 503、依赖 TCP ok、本地日志 `error_type in {TimeoutError, timeout}` 且 `upstream_request.connection_established is True`、`timeout_seconds == 0.5`。
   - `review_model_artifacts()` 允许的结果层为 `['localized_fault', 'confirmed_cause']`（与其它单故障用例同口径）。
   - `set_model_case('downstream_slow')` 写 `downstream.mode`，无需重启依赖进程。
   - 新增 `--model-stage latency`：跑 2 场，账本按 `--previous-cost` 串接；与 `--mechanism-group`、`--knowledge-disabled` 互斥。
   - `--evaluation-preflight` 用例循环加入 `downstream_slow`。
2. `scripts/competing_hypothesis_fixture.py`：故障白名单加入 `downstream_slow`，`reset()` 写入慢响应 mode 文件。
3. `scripts/aiops_test_environment.py`：`--scenario latency` 映射到 `downstream_slow`。
4. `tests/test_windows_local_faults.py`：新增两条单测——慢响应确实延迟返回 200；慢下游必须凭"连接已建立 + 超时"这组证据通过状态校验，换成连接未建立则必须判失败。

验证（零成本）：`pytest tests\test_windows_local_faults.py -q` → **123 passed, 1 deselected**；`--evaluation-preflight` → `ok: true`、`model_calls: 0`、**33 个用例全 passed**（含新增 `controller_preflight_downstream_slow`）、`ports_released: true`、`cleanup_errors: []`。

付费运行命令：

```
.\.venv\Scripts\python.exe scripts\verify_windows_local_faults.py --run-model --model-stage latency \
  --previous-cost runtime\windows-local-faults-65e6e409ec494f28be77f3cb7173b0e2\model-2ee9745b64f24a399e2508d7ee9b5839\cost.json \
  --budget-limit-cny 31.648352
```

`--budget-limit-cny` 是**累计账本上限**，不是单轮上限；首次尝试误传 5 元，被 `read_cost_ledger(..., for_resume=True)` 以 `prior scenario has exhausted or uncertain cost` 拒绝（目录 `runtime/windows-local-faults-d716154caffe4661a912bbcbb281835c` 保留为证据，`cost_records: []`，未产生模型调用）。

## 四、两场结果

两场结构完全一致：`scenario=provided_symptom`、`has_final_report=true`、`workflow_completed=true`、`report_generation={mode: rules, status: ready}`、`investigation_failure=null`、`tool_calls=15`（`probe_dependency_probe`×3、`probe_process_snapshot`×3、`probe_text_log`×3、`probe_inventory`×2、`probe_list_evidence`×2、`probe_resource_snapshot`×1、`probe_config_snapshot`×1）、`knowledge_mcp_calls=0`、`knowledge_conditions.passed=true`。

| 项 | 第 1 场 | 第 2 场 |
| --- | --- | --- |
| `report_kind` / `diagnosis.kind` | `localized_fault` | `localized_fault` |
| 直接原因码 | 空 | 空 |
| 报告字符数 | 5215 | 5283 |
| 机械审核 `passed` | true（11 个门全 true） | true（11 个门全 true） |
| `level_matches_scenario` | true（期望 `localized_fault` / `confirmed_cause`） | true |
| `capability_passed` | false（语义待人工审核） | false |
| `mechanism_audit` 机会/改向/检查 | 保护0 矛盾6 / 改向4 / 检查5 | 保护0 矛盾5 / 改向4 / 检查4 |
| 执行步数 / 被阻事件 | 11 / 1 | 9 / 1 |
| 矛盾事件计数 | 触发5 被阻1 | 触发4 被阻1 |

两场报告开头逐字相同：

```
已定位故障层：已有异常，优先处理对象尚不能确定
故障对象与影响：需要继续区分异常对象及处理顺序
其他异常对象：localapp、edge；与优先对象的因果关系尚未确认，处理后须分别复测。
```

报告"证据支持的解释"写的是"已观察到异常；仅凭这些事实尚不能确定故障原因。"，结尾三个固定小节为：

```
剩余未知：更深原因尚未确认，未核验的因果解释仍保留。
校验提示：仍有校验未通过的提议，不能作为已确认结论；具体问题见诊断详情。
停止原因：现有候选检查已完成或受阻；已复核保存候选及通用补查，没有通过守卫的新检查。 仅覆盖系统当前可识别的有限检查，不代表所有可能检查已穷尽。
```

报告里落进引用的事实与夹具真值是对得上的：localapp 入口 503、依赖 edge/localapp TCP ok、downstream TCP ok 且 HTTP 200、localapp 日志 `error_type=TimeoutError` + `upstream_request={"phase": "receive_headers", "connection_established": true}`、downstream 日志同 `request_id` 返回 200、配置快照 `downstream_port=10040` 与登记一致。

## 五、三条观察

1. **两场都没到 `confirmed_cause`，连"优先处理对象"也没落到 localapp。** 第 1 场 `scope=localapp`，第 2 场 scope 写"localapp 入口及其两个登记依赖的采样窗口"；两场都把 localapp 与 edge 并列写进"其他异常对象"。与停机场对比：八场里 downstream 停机 3/4 能给 `confirmed_cause` + `downstream_stopped_after_request`。

2. **模型其实想到了正确的方向，但缺一个可核验的现场条件。** 第 2 场的 `limitations` 原文："downstream TCP ok、HTTP 200、配置进程存在；仅反驳不可达/进程缺失，**不排除 downstream 在特定请求下响应慢**。" 但工具集只有 `probe_dependency_probe`（返回的是该次探测的 `elapsed_ms`，不是对特定请求的响应时间谓词）、`probe_text_log`、`probe_process_snapshot`、`probe_config_snapshot`、`probe_resource_snapshot`，**没有"下游响应时间是否超过应用超时阈值"这类可判定条件**，因此该解释只能留在 `unresolved`。第 1 场的 `limitations` 同样写明"日志显示连接已建立，失败在 receive_headers 阶段"。

3. **日志去重守卫在这里起了决定性作用。** 两场的 `stop_reason` 都是"首选检查受阻（相同日志检查已完成；复查须关联旧日志之后同服务有变化的新证据…）"：模型想再读一次 localapp 日志以区分"内部错误"与"上游超时"，被"同一对象同一参数的检查不重复"守卫拒绝，可替代的鉴别检查又不存在，于是按"保留未知后结束"处理。这一行为与设计一致（不允许重复用同一结果抬升可信度），但也说明**延迟类故障需要新的取证工具，而不是放宽守卫**。

## 六、口径限制（第五章必须同时写出）

1. **样本量 2 场、单一故障、单一夹具**，不构成统计结论；只能陈述"两场都停在 `localized_fault`，未给出直接原因"。
2. 两场的 `capability_passed` 仍为 `false`、`semantic_status=pending_manual_review`、`manual_verdict=pending`——**尚未做人工语义审核**，因此本节不声明"诊断正确"或"诊断错误"，只陈述结果层与所引事实。
3. 本批未统计逐条引用命中数（机械门的 `quotes_observed`、`evidence_for_assertion` 均为 true）；与 11-10 八场"155/155 逐条精确"的口径不可直接混用。
4. 夹具真值（downstream 响应 1.2 秒 > localapp 0.5 秒超时）只用于说明"现场应当支持什么"，不用于给模型结论打分；打分需按《人工语义审核》口径另做。
5. 延迟是**脚本层注入**（mode 文件 + sleep），不是网络层延迟、不是系统负载造成的延迟；不能据此推断真实慢调用的表现。
6. 本轮改动只涉及测试与夹具脚本（`scripts/`、`tests/`），没有改业务代码（`src/`）。

## 七、材料索引

- 批次目录：`runtime/windows-local-faults-3f6f8bc54dee4fa6868b7b54e295d4fc/`
- 第 1 场：`model-546d2f41262049d19deb4ff4d63508ff/`（`summary.json`、`report.txt`、`mechanical-review.json`、`evaluation-record.json`、`tool_trace.json`）
- 第 2 场：`model-befcca8474c74cf283767512cd8d8c46/`（同上）
- 被前置条件拒绝的尝试：`runtime/windows-local-faults-d716154caffe4661a912bbcbb281835c/`
- 免费预检：`runtime/windows-local-faults-907b31b9687b40b790a7404090a8f75f/`
- 核对脚本：`runtime/docs-tools/inspect_latency.py`、`inspect_latency2.py`、`inspect_latency3.py`、`check_slow.py`（均在 `runtime/`，不进入 Git）
- 相关文档：`docs/fault-pair-preexperiment-result-20261110.md`（八场停机场与人工语义审核）、`docs/tool-availability-control-20261111.md`（工具可用性对照）、`docs/windows-probe-fault-acceptance.md`（夹具与验收口径）