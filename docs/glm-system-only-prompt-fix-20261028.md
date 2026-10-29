# GLM 失败根因定位与 prompt 形态修复（2026-10-28）

## 结论

**根因是调用形态，不是供应商故障，也不是配置错误。** `InvestigationStrategy` 的 `_PROMPT` 只有一条 system 消息；在 RightAPI 上，**仅含 system、没有 user 轮**的 chat/completions 请求会长时间等待后返回 HTTP 502 或读超时。保持其他一切不变，只要存在 user 轮就恢复正常。

修复：把 `_PROMPT` 拆为 system（规则）+ user（数据/上下文）两条消息，与同项目 `planner_prompt` 的既有形态一致。修改后重新实测，强制工具调用成功且决策可解析。

## 本轮实测矩阵（全部同一端点、模型、凭据、UA、无重试、单次发送）

| 时间顺序 | 轮次角色 | max_tokens | HTTP | 耗时 | finish_reason | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | user | 32 | 200 | 2.27s | stop | 正常 |
| 2 | system | 32 | **502** | 83.7s | — | 失败 |
| 3 | user | 32 | 200 | 4.85s | stop | 正常（排除时间劣化） |
| 4 | system,user | 32 | 200 | 2.79s | stop | 正常 |
| 5 | system | 32 | **502** | 102.7s | — | 失败（复现） |

5 次交错请求跨越约 5 分钟，user 与 system+user 全部 200，system-only 两次全部 502。时间因素、限流、凭据、模型名、UA 均可排除。

## 生产影响面

- `src/agent/aiops/strategies/investigation.py` 的 `_PROMPT` 原为单条 system，承载全部指令与数据；`InvestigationStrategy.decide()` 每次重规划都走这个形态。
- 历史冒烟失败的四次成功、三次超时正好与之相容：规划阶段（`planner_prompt`，system+user）成功，进入 `InvestigationDecision` 重规划（system-only）后开始 502/超时。
- `planner_prompt`、`Act`、`Response` 等其他 prompt 已是 system+user，未受影响。

## 修复内容

```python
_PROMPT = ChatPromptTemplate.from_messages([("system", """...规则..."""),
                                            ("user", """症状：{input} ... 采样前后对比：{progress}""")])
```

仅移动消息边界，规则文本与全部 `{占位符}` 内容均未改写，`decide()` 的 `prompt_input` 键未变，调用方无需改动。

## 验证

- `_PROMPT.format_messages(...)` 返回 `['system','human']`，system 2589 字符（仅规则）、user 237 字符（数据），占位符全部落在 user。
- 定向回归：`test_investigation_strategy.py`、`test_investigation_fusion.py`、`test_investigation_mechanisms.py`、`test_investigation_failure_flow.py` 共 **177 项通过**（`runtime/glm-prompt-split-tests-20261028.xml`）。
- 全量离线回归：`pytest tests/` **1222 项通过、0 失败**，保留 1 条既有 PyMilvus 弃用警告（`runtime/glm-prompt-split-full-20261028.xml`）。integration 标记按 `pytest.ini` 默认排除，未运行。
- 端到端真实请求（`runtime/glm-prompt-split-verify-20261028-a/`）：修复后的 system+user 形态 + `InvestigationDecision` 强制工具 + `max_tokens=4096`，HTTP 200、10.34 秒、`finish_reason=tool_calls`、**decision_parsed=true**，返回字段含 hypothesis/alternatives/conclusion_level/outcome/scope/blocked_reason。输入 1359、输出 289 Token。

## 顺带澄清：256 Token 不是生产缺陷

`evaluate_windows_probe.py` 与 `verify_windows_local_faults.py` 的 `--max-output-tokens` 默认均为 **4096**；历史冒烟里的 256 是该次显式传入的冒烟上限。用 256 跑 18 字段 schema 会 `finish_reason=length` 且拿不到工具调用（本轮已复现），但这属于测试参数选择，不是代码缺陷。真实实验与演示应使用默认 4096 或更高。

## 未验证与限制

- 只验证了 `glm-5.3-flash` + RightAPI 组合；其他供应商是否需要 user 轮没有实测。加 user 轮是通用无害形态，不依赖该供应商特性。
- 未跑完整 Agent 故障调查闭环，未验证完整四组实验；本轮只验证单次决策请求形态。
- 各次实际费用未知，未修改旧账本；未启动或重启任何服务，未注入新故障。
- 生产 `decide()` 还叠加 `ainvoke_with_retry`；重试逻辑本轮未改动，重试仍会在 502/超时下发生，但根因已不是它。
