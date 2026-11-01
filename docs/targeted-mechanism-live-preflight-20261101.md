# 机制适用场景现场控制器预检（2026-11-01）

## 目的与边界

在不调用模型、不增加费用的前提下，验证保护和矛盾触发在有明确候选条件及现场反证时，是否能改变实际检查选择；同时验证无反证对照和控制器恢复。四组都使用固定决策，结果只证明规则接线与行为可区分，不证明模型会自主生成这些候选，也不证明机制提高诊断准确率。

## 场景与结果

运行目录：`runtime/windows-local-faults-0d182812caec40ebb78696916172b447`。机制场景通过真实临时 Windows Probe 与测试应用采集证据，模型调用为 0。

- 保护场景：应用配置错误，入口 HTTP 503、下游健康。四组都出现保护机会；G00/G01 继续查下游，G10/G11 按保护事件改查入口并实际完成检查。
- 矛盾场景：入口仍为 HTTP 503、下游探测为 TCP/HTTP 正常，与候选“下游不可达”相矛盾。四组都出现矛盾机会；G00/G10 继续查日志，G01/G11 记录 `contradiction_triggered` 并实际改查入口。
- 无现场反证对照：四组均无矛盾改向事件；G00 在所有场景均无机制选择事件。
- 12 次机制调查的行为审计全部通过，36 条机制证据 ID 独立且各组知识条件前后核对一致。机制前置门检查通过。

完整控制器免费预检也通过：汇总 `ok=true`、`model_calls=0`、55 条控制器证据；最终现场恢复 HTTP/TCP 200，所属临时进程已停止、监听端口已释放、清理错误为 0。两个无效证据注入被 Probe 身份校验拒绝，对应负向安全检查通过。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_live_probe_mechanisms.py tests/test_investigation_mechanisms.py tests/test_mechanism_behavior.py
git diff --check -- scripts/verify_probe_mechanisms.py scripts/verify_windows_local_faults.py tests/test_live_probe_mechanisms.py
```

结果：`132 passed`；仅有既有 PyMilvus 弃用警告。`git diff --check` 通过，只有 Git 对 LF/CRLF 的提示。

## 后续 D 阶段复核

复用既有且仍在工作区的真实运行材料，避免重复重启服务和重复浏览器回放：`docs/ops-knowledge-free-verification-20261023.md` 记录三份 PDF、8 个相关检索查询及 1 个无关空结果、主页面与 HTTP MCP 同片段/页码和 PDF 原文跳转；`docs/investigation-browser-replay-20261026.md` 记录实际前端中途输出、完成报告、刷新恢复和引用呈现。两份记录引用的关键运行产物均存在。

为覆盖之后改动过的当前页面代码，另运行 `npm.cmd test -- --run src/views/AIOps.test.js src/views/AIOps.matching503.test.js`：20 项通过；`npm.cmd run build` 通过。D 阶段现有验收范围完成。仍未验证常驻 Planner 自动消费知识库 15，也未验证向量混检；历史材料明确记录了这些边界。

## 结论

C2 和 D 的免费工作块已完成。C2 解决了此前场景与候选预期不贴合、关闭矛盾触发时兜底检查可能掩盖组间差异的问题。D 复用已有真实页面/检索运行证据，并对当前 AIOps 页面做定向回归与构建。下一步 E1 是一次修复后 G11 真实模型闭环；当前累计请求上限为 195，已使用 194，继续前需用户另行授权并明确提高请求上限。不得自动使用剩余单次请求。
