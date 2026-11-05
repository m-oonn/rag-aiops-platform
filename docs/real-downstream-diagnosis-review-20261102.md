# 2026-11-02 真实下游故障语义审核包

对象：`runtime/windows-local-faults-05470499e792485181a07e44e811555c/model-8d138cd570a0471bbeee7d6ae934b009/`

请把下面三项分开判断，不要把“定位正确”当成“根因已查清”。

1. 诊断：是否接受“localapp 入口返回 503，配置 downstream 当前 TCP 被拒、9633 无监听、未发现匹配进程；更深停止原因未确认”的有限定位？
   - 候选：`correct_localization` / `incomplete` / `wrong_cause_or_false_positive`
   - 证据：`ev-438a91a6b360415e856071c29bb13605`、`ev-ba6ec5cf9f294b1488faf2fb3c7c1534`、`ev-240d834c3ba74300a653f16a84b5033f`、`ev-f04067c351d24f88af776f1e6a2b4bd6`

2. 引用支持：上述有限定位的引用是否支持对应事实？
   - 候选：`supported` / `insufficient` / `unsupported`
   - 限制：支持现场事实不等于支持“谁停止、为什么停止”的因果解释。

3. 建议适用性：报告中的人工核查/恢复建议是否可作为“有前提的排查清单”？
   - 候选：`appropriate` / `insufficient` / `inappropriate`
   - 限制：建议不能直接执行；下游端口、进程和依赖三条建议内容有重复。

控制器事后真值（`process-lifecycle.json`、`controller-observations.jsonl`）仅用于核对测试注入，不算 Agent 证据。`ev-096a14f35afa4048ad15aceb19ac15b4` 只证明日志出现 `shutdown_requested/controlled_stop`，不能证明触发者。
