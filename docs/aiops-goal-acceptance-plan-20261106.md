# AIOps goal 小阶段验收方案（2026-11-06）

## 目标

在一个独立测试轮次中，验证真实产品闭环：前端发起诊断，正式 SSE 推进，真实模型通过 Windows Probe → Gateway → MCP → 诊断执行器取证并在发现缺口时继续调查，系统只依据有效证据确认直接根因，生成完整报告，保存到数据库并在刷新、后端重启后读取；读取阶段不得产生模型请求。

本方案不把 `workflow completed`、`localized_fault` 或环境 `ready` 当作通过。每个场景单独判定，失败材料保留，不能回写历史成功。

## 小阶段边界

本轮只做两道门：

1. **免费门**：修复并只读回放 034 `normal` 失败，确认反馈能区分“已采集但模型漏引用”和“尚未采集”，然后完成免费环境、Probe、日志时序和恢复清理验收。
2. **单轮真实门**：在免费门通过后，使用全新轮次验证 `endpoint` 的真实根因闭环。`endpoint` 的直接原因是 `configured_downstream_endpoint_mismatch`，因为它能够验证模型是否会主动检查配置、请求失败链和登记下游健康状态，并形成可引用报告。

本方案不在未取得本轮明确真实模型授权前发送付费请求。

## Goal 基线与确认点

- 当前 Git 基线为 `main` HEAD `3a4bd4a`；执行记录还必须包含当时的 `git status --short --branch` 和相关未提交 diff。2026-11-06 的 034 回放是在 `scripts/replay_aiops_decision.py`、`src/agent/aiops/strategies/investigation.py` 及对应测试存在未提交改动时完成，不能表述为干净 main 已验证。
- 本任务已有一个 active Goal；本文件是它的小阶段执行方案，不另建重复 Goal。
- 每完成一个用户要求的阶段，先用简短中文报告证据和结论，再给“继续 / 暂停”选择；收到继续后才进入下一阶段。第5点完成后，先询问是否启动免费门。
- 免费门通过后，建立 035 的账本和预检材料；真实模型门仍须用户对该轮明确授权。授权按单轮有效，不能从历史轮次或此前笼统授权推定。
- 每轮最多新增预留 5 元，历史账本只继承、不计入新轮额度；未知 usage/无法定价立即停止。失败后保留账本和材料，修复及下一轮需使用新目录并继承最新账本。

## 通过条件

### A. 免费门

- 034 原始材料文件 hash 不变，历史失败仍保留。
- 回放反馈至少明确区分：
  - 已有有效证据但模型没有引用；
  - 目标类别尚未采集；
  - 已采集证据与提议结论不一致。
- 反馈不自动填写根因、引用、状态或工具参数。
- 相关单元/回放测试通过；免费环境的真实请求、同 `request_id` 的 edge/localapp 日志、Probe/MCP 可读性、旧日志排除、恢复三入口 200、所属进程停止、端口释放和 `cleanup_errors=[]` 全部通过。

### B. 真实 endpoint 门

- 使用新输出目录和 035 轮次，继承 034 最新 `cost.json` 的 hash、条数和历史未知项。
- 真实模型请求总新增预留不超过 5 元，包含调查、报告、重试和备用模型；未知 usage 或未知价格不得按 0 元处理，出现新增未知 usage 时停止后续发送。
- 前端正式页面发起一次诊断，SSE 事件、工具执行、模型输入和结果文件均保存。
- 模型必须通过合法工具取得并引用：
  - 应用加载的下游端口及配置 hash；
  - 同一请求的应用失败日志；
  - 错误端口不可达或未监听；
  - 登记下游健康；
  - edge/localapp 同一 `request_id` 的失败链。
- 最终结果必须是 `completed` + `confirmed_cause`，原因码为 `configured_downstream_endpoint_mismatch`；所有主引用可由正式接口读取并在页面定位。
- 报告必须包含：结论、根因证据、影响范围、处理建议、复测方法和未知项；不得把配置变更者、部署动机等无来源历史写成事实。
- 刷新页面和同轮后端停止/重启后，报告、诊断对象、证据元数据和 hash 一致；读取期间 `cost.json` 请求数不增加，数据库读取不调用模型。
- 最后恢复三业务接口 200，确认所属进程停止、端口释放和 `cleanup_errors=[]`。

## 执行顺序

1. **固定基线**：记录当前 commit、工作区状态、034 `cost.json` 字节 hash 和原始材料 hash；确认没有旧后端或业务进程占用端口。
2. **免费回放 034**：只运行回放和相关回归，不启动真实模型；若回放或回归失败，停止在此，不创建付费轮次。
3. **免费环境验收**：新目录启动 `endpoint`/`normal` 所需夹具，验证真实业务请求、Probe/Gateway/MCP 证据读取、旧日志隔离和恢复清理。
4. **建立 035 轮次**：从 034 最新账本继承，不复制或重建历史请求；生成 `run-budget.json`，核对本轮 5 元上限。
5. **取得本轮真实授权后**：保持环境 `ready`，只启动一次带 `--run-model --previous-cost` 的正式后端；登录页面并点击一次诊断。
6. **模型调查期间**：观察每次提议、守卫结果、执行证据和反馈；发现工具缺口、无效参数、重复查询或引用错误时，让系统反馈并由模型选择下一次合法检查，不人工替模型填答案。
7. **报告与持久化验收**：保存页面/接口结果，记录报告和证据 hash；停止并重启同轮后端，再读取 `/runs/{thread_id}` 和证据接口，确认零新增模型请求。
8. **收尾**：恢复环境并检查进程、端口、日志归档和费用账本；任何一项不满足都标记该场景失败，保留全部原始材料。

### 可直接执行的 PowerShell 入口

在工作区根目录执行。输出目录必须不存在；每次回放和每个环境使用全新目录。

```powershell
$py = '.\.venv\Scripts\python.exe'
$replayOut = 'runtime/aiops-goal-034-replay-20261106-b'
& $py scripts/replay_aiops_decision.py runtime/aiops-goal-034 --output $replayOut
if ($LASTEXITCODE -ne 0) { throw '034 historical replay failed; stop before environment or paid run' }
& $py -m pytest tests/test_decision_replay.py tests/test_investigation_strategy.py -q
if ($LASTEXITCODE -ne 0) { throw 'free regression failed; stop before paid run' }

$envOut = 'runtime/aiops-goal-free-endpoint-20261106-a'
& $py scripts/aiops_test_environment.py start --output $envOut --scenario endpoint --duration-seconds 3600
```

环境报告 `status=ready` 后，按 `docs/aiops-test-environment.md` 免费启动正式后端（不带 `--run-model`），验证页面登录/刷新、免费诊断 403、真实业务请求、Probe/Gateway/MCP 日志读取及恢复清理。需要验证 normal 时另用新目录并设 `--scenario normal`；不能把 endpoint 的环境通过复用为 normal 通过。每个环境停止后核验 `environment.json` 的恢复、进程、端口和清理字段。

034 回放的预期是忠实重现其 `unlocated` 决策、`model_calls=0`、`new_observations=0` 且原材料 hash 不变；它不要求把历史失败“回放成通过”。回归测试应证明反馈可以区分证据漏引、尚未采集和证据冲突，并且不替模型填根因、引用、状态或工具参数。历史结果目前满足上述回放预期；再次运行是基线确认，不是新的模型验收。

免费门通过后，035 真实门的账本源固定为 `runtime/aiops-goal-034/product-model/cost.json`（启动前再次确认它仍是最新完整账本并记录字节 SHA256）。由正式环境入口生成 `product-model/run-budget.json`；核对其继承 hash/条数/预留与源账本一致、本轮上限为 5 元，再停在付费启动前等待本轮明确授权。之后按环境文档启用 `--run-model --previous-cost <该账本>`，前端仅提交一次诊断；同一 035 重启只能续用本轮账本，不得重新初始化额度。

### 每道门的验收记录

Goal 进度以本文件和每轮目录中的材料为准，每道门记录 `pending / passed / failed / not_run`，附证据路径和 hash：

| 阶段 | 状态 | 必需证据 | 通过条件 |
|---|---|---|---|
| 1. 项目现状 | passed | main HEAD、工作区状态、测试及历史运行记录 | 明确区分当前 HEAD、未提交改动、历史真实通过和当前未验收项 |
| 2. 用户需求 | passed | 用户提出的链路、报告字段、刷新/重启读取和费用约束 | 需求条目完整进入验收条件 |
| 3. 测试环境 | passed | endpoint/normal 环境记录、浏览器、业务日志、Probe/MCP、恢复清理 | 对每个场景单独判定；ready 不作为产品验收 |
| 4. 现状差距 | passed | 现有证据对照需求矩阵 | 每项标为已证实、未通过、未验收或缺证，不把历史结果冒充当前通过 |
| 5A. 免费门 | passed | 回放 JSON、原材料 hash、JUnit XML/日志、环境报告 | 回放/回归边界通过，环境证据链可读且清理通过；不需要付费请求 |
| 5B. 真实门（036 轮次 + 干净 main 复跑 037 轮次） | passed | 预算清单、SSE/工具轨迹、脱敏模型输入、报告与证据 hash、数据库重启读取、费用账本 | 全链路、根因门槛、六项报告内容、刷新/重启一致及零读取模型调用全部通过，费用与清理符合约束；036 在未提交工作区跑通，提交后在干净 main 上以 037 轮次（5 元上限重置）完整复跑一次 |

各阶段的落盘证据：

- **1. 项目现状**：`runtime/aiops-goal-freegate-20261106-b/HEAD.txt`（`3a4bd4ac605fd948ad2370b8ff1578f682161359`）、`git-status.txt`（`## main...origin/main [ahead 69]` + 4 改 2 未跟踪）、`worktree.diff`（21747 B，SHA256 `9e5cd3a3edda…`）、`ledger-sha256.txt`。034 历史失败材料见 `runtime/aiops-goal-034/`，其"历史通过"仅限该目录自身的 `environment_acceptance`，不冒充本次验收。
- **2. 用户需求**：第「通过条件」A/B 两节把链路、报告六项字段、刷新/重启读取、费用上限与停止条件逐条转成检查项，5B 验收表逐行对应。
- **3. 测试环境**：`endpoint` 场景见 `runtime/aiops-goal-freeenv-20261107-c/`（`environment.json`、`preflight.json` 6960 B、`control-check.json` 3788 B、`browser-check.json` 1414 B、`frontend.png`）；`normal` 场景见 `runtime/aiops-goal-freeenv-20261107-d/`（`normal-check.json` 2695 B、`environment-ready.json`、`environment.json` 1362 B、`preflight.json` 6997 B，`rounds/1` 与 `rounds/2` 归档）；`runtime/aiops-goal-freeenv-20261107-b/` 为 `endpoint` 首轮控制验证（同一脚本二次运行）。两个场景各自用全新目录独立判定，`endpoint` 的通过未复用到 `normal`。
- **4. 现状差距**：免费门执行记录的表格（10 行）与 5B 验收表（19 行）就是需求矩阵，每行给出 `passed` 与证据文件/ev-id；未能证实项单独列入「剩余限制」。

> 轮次编号说明：035 轮次仅用于步骤 4 的预算构建（零请求），因其 3600 秒有效期剩余不足 200 秒，真实门改在新建的 036 轮次执行，账本由 035 轮次账本继承（等价于 034 最新账本 + 零新增）。

任何失败均保留原记录并停止当前门；不能以修复后的回放覆盖真实失败。5B 未获授权时记为 `not_run`，Goal 保持 active，不标记整体验收完成。

## 停止条件

出现以下任一情况立即停止本轮后续模型请求：新增 usage 未知、价格未知且无法定价、预算守卫拒绝、目标轮次/hash 不一致、证据越权或来源泄漏、报告引用无效、模型输出无法解析、数据库或 checkpoint 不一致、读取阶段产生模型请求、环境恢复/清理失败。

## 交付材料

至少保留：`environment.json`、`preflight.json`、`result-summary.json`、`decision-audit.json`、`latest-state.json`、`product/runs.sqlite`、`product/checkpoints.sqlite`、`product/tool_trace.json`、`product/knowledge_trace.json`、`product-model/cost.json`、脱敏 `model-inputs/`、回放/测试 XML 与日志，以及报告/证据 hash 清单。

## Goal 状态记录方式

- `free_replay`: 免费回放及回归状态。
- `free_environment`: 环境和证据可达性状态。
- `paid_run`: 本轮真实模型是否获授权、请求数、预留和未知项。
- `root_cause`: 原因码、主引用、替代解释和未决项。
- `report_persistence`: 报告/证据读取一致性及新增模型请求数。
- `cleanup`: 恢复、进程、端口和清理结果。

只有所有门均通过，goal 才能标记完成；否则保留失败原因和材料，下一轮使用新目录、新轮次和继承账本继续。

## 当前执行记录（2026-11-06）

- `tests/test_decision_replay.py` 与 `tests/test_investigation_strategy.py`：163 passed，1 条既有 PyMilvus 弃用警告。
- 034 只读历史回放保存于 `runtime/aiops-goal-034-replay-20261106-a/`：`model_calls=0`、`new_observations=0`，结果仍为 `unlocated`，没有根因码或主证据；原始失败保持不变。回放期间在临时副本读取 SQLite，034 原始材料前后哈希一致。
- 当前策略反馈测试覆盖四类登记依赖状态：有效证据且已作主引用、有效证据但漏作主引用、采集不完整、尚未采集。测试证明系统可构造区分反馈；不能证明真实模型收到反馈后会自主收敛。
- 下一步待确认是否进入免费环境验收。真实模型门尚未启动，未新增模型请求或费用；须另行取得本轮真实调用授权。
- 本文所述 Goal 方案已整理为执行步骤、可复制入口、阶段验收证据和确认点；当前未启动新的环境或真实模型轮次。执行前需重新核对上述 main/worktree 基线及账本最新性。

## 免费门执行记录（2026-11-07）

基线：HEAD `3a4bd4ac605fd948ad2370b8ff1578f682161359`（`main...origin/main [ahead 69]`），未提交改动 4 个文件（`scripts/replay_aiops_decision.py`、`src/agent/aiops/strategies/investigation.py`、`tests/test_decision_replay.py`、`tests/test_investigation_strategy.py`，+180/−25）及 2 个未跟踪文件。**本门所有结论均在未提交工作区下产生，不构成干净 main 的验证。**证据目录 `runtime/aiops-goal-freegate-20261106-b/`。

| 项 | 结果 | 证据 |
|---|---|---|
| 034 原材料完整性 | passed，75 个文件 SHA256 全匹配 | `runtime/aiops-goal-baseline-20261106-b/material-manifest.json`（1d67fc58…984e3） |
| 历史失败保持 | passed，回放仍 `unlocated`、`model_calls=0`、`new_observations=0`、`original_artifacts_unchanged=true` | `replay/replay.json`（6225780b…4918）、`replay/report.txt`（b8be15cb…a689） |
| 回归测试 | passed，165 passed / 1 条既有 PyMilvus 警告 | `pytest-free-gate-final.xml` |
| 反馈三类区分 | passed（单测），漏引用/未采集/不完整/矛盾各有状态与断言；矛盾态为 `collected_contradicts_proposed_conclusion` | `tests/test_investigation_strategy.py:381`、新增两个测试 |
| 反馈不代填 | passed，反馈中不含根因码、引用文本、工具名或工具参数 | 同上断言 |
| 空闲环境真实性 | passed，`request` 503 / `restore` 200 / `inject` 503，同一 `request_id` 在 edge 与 localapp 日志唯一命中且状态一致 | `runtime/aiops-goal-freeenv-20261107-c/control-check.json`（8e90fe80…28bf） |
| 旧日志隔离 | passed，两次轮次切换后上一 `request_id` 残留行数为 0 | 同上 `rounds_rotated=2`、`old_logs_excluded=true` |
| 前端与只读面 | passed，真实登录 + `/aiops` 页面渲染，诊断 POST 返回 403，私有文件均返回 HTML | `browser-check.json`（b79d9edc…de5b）、`frontend.png`（0d123c33…2561） |
| 环境恢复与清理 | passed，`status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0` | `runtime/aiops-goal-freeenv-20261107-c/environment.json`（b83233d3…df2c） |
| `normal` 场景单独判定 | passed，独立新目录 `--scenario normal`；`request` 200 / `inject` 200 两轮，同一 `request_id` 在 edge 与 localapp 日志唯一命中且状态 200，轮次切换后上一请求残留行数 0，停止后三入口 200 恢复 | `runtime/aiops-goal-freeenv-20261107-d/normal-check.json`（66815eae…9630）、`environment.json`（49fbd1e8…4657）、`environment-ready.json`（41e587dc…cfe1）、`preflight.json`（ffa458a7…b58a） |

要点：免费门只证明回放/回归边界、环境证据链可读、恢复清理正确，以及系统能构造出区分反馈；**不能证明真实模型收到反馈后会自主收敛**。`endpoint`（目录 c）与 `normal`（目录 d）分别用全新目录独立判定，未把 endpoint 的通过复用到 normal；两个环境停止后都核验了恢复、进程、端口与 `cleanup_errors`。本轮免费门未启动真实模型，未新增模型请求或费用（`environment_model_calls=0`、`model_calls=0`）。

035 账本源仍为 `runtime/aiops-goal-034/product-model/cost.json`（2151539 B，SHA256 `e741747b7c246e9d49e98545747d5d96d4af7927c5721266e66e47cbdbf3a018`），同目录既有 `run-budget.json` 属于更早轮次，须由正式环境入口重新生成后再停在付费启动前。

## 035 轮次预算构建记录（2026-11-07）

步骤 4 已执行，**未发出任何模型请求**；停在付费启动前等待本轮明确授权。

- 新轮次目录：`runtime/aiops-goal-035`，场景 `endpoint`，round 1，`target_id=aiops-test-14979f0c7e93`，`gateway_url=http://127.0.0.1:2165/mcp`，业务入口 `http://127.0.0.1:2161/api/availability` 首次请求 `37b4e614e32240d087b7c0dcd7a77ce3` 返回 503；`environment_acceptance=passed`、`environment_model_calls=0`、`diagnosis_acceptance=not_run`。
- 账本最新性：`031 c39a79950914`（1162 条）< `032 bbdb9f766871`（1172）< `033 a47d35f0f3a5`（1183）< `034 e741747b7c24`（1191），`runtime/aiops-goal-034/product-model/cost.json` 确认为最新源账本（2151539 B）。
- 由正式环境入口 `scripts/aiops_test_environment.py backend --run-model --previous-cost` 生成 `runtime/aiops-goal-035/product-model/run-budget.json`（203 B，SHA256 `b397d2b960f1be7d16c53422069e413934b1cdea62908bcf12b028039d1a90f6`）：

| 字段 | 值 | 与源账本核对 |
|---|---|---|
| `version` | 1 | — |
| `previous_sha256` | `e741747b7c246e9d49e98545747d5d96d4af7927c5721266e66e47cbdbf3a018` | 一致 |
| `inherited_requests` | 1191 | 一致（源账本 1191 条） |
| `inherited_reserved_cny` | 46.82155 | 一致 |
| `run_limit_cny` | 5 | 本轮新增上限 5 元 |

- 轮次账本 `runtime/aiops-goal-035/product-model/cost.json`（2151538 B，SHA256 `9e0fbafc62ade8238015e8939d02c8109fa1cb5d46b7df89633957e76349fca5`）：`reserved_cny=46.82155`、`limit_cny=51.82155`（= 继承预留 46.82155 + 本轮 5）、`requests=1191`、`blocked_requests` 9、`request_limits.inherited_requests=1191`；1191 条历史行与源账本逐行一致，本轮新增请求 0，`model-inputs/` 未创建。
- 同轮重启复校验：用相同 `--previous-cost` 再次以 `--run-model` 启动后端，`run-budget.json` 与 `cost.json` 字节与 SHA256 均未变化、行数仍为 1191，说明同轮重启不会重置预算基线。
- 预算守卫干跑（`runtime/aiops-goal-035/budget_dry_run.py`，在临时副本上执行、已删除）：`deepseek-v4.1-flash-1017` / `https://dashscope.aliyuncs.com/compatible-mode/v1` 定价已确认，单次预留 `0.07336` 元（input_upper 20296、output_upper 4096），占本轮 5 元上限的 1.5%，`reserve()` 通过。
- 后端两次启动均以 `stop-backend` 标记干净退出（uvicorn 退出码 0，日志末尾 `Application shutdown complete`），8200 端口已释放；环境仍为 `status=ready`、round 1，仅 gateway 与 Probe 在运行。
- **停止点**：`5B. 035 真实门` 仍记 `not_run`。未获本轮明确授权前不发起任何付费请求；环境自带 3600 秒有效期，超时需重新 `start` 并重建预算。

## 036 真实门执行记录（2026-11-07）

用户在获得 035 预算构建报告后回复「继续、」＝授权本轮单场真实诊断。因 035 环境 3600 秒有效期只剩 187 秒，先将 035 以 `stop` 标记干净停用（`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`，预停快照另存 `runtime/aiops-goal-035/environment-ready.json`），再新建 036 轮次。035 停用后两个预算文件哈希不变、1191 条历史行与 034 逐行一致 → 035 确实零请求。

基线：HEAD `3a4bd4ac605fd948ad2370b8ff1578f682161359`（`main...origin/main [ahead 69]`），未提交改动仍为同样 4 文件 + 2 未跟踪文件；**本门结论同样在未提交工作区下产生，不构成干净 main 的验证**。证据目录 `runtime/aiops-goal-036/`（`evidence-hashes.json` 记录 32 个文件、14 个证据文件、17 个脱敏 `model-inputs/` 的字节数与 SHA256）。

### 环境与预算

- 轮次：`runtime/aiops-goal-036`，场景 `endpoint`，round 1，`target_id=aiops-test-df1a45ce6311`，`gateway_url=http://127.0.0.1:7205/mcp`，业务端口 edge 7201 / localapp 7202 / downstream 7203 / 无监听 7204。
- 首次业务请求 `13d478b930a443e4baefd7a95002ec26` 返回 503（edge 日志 `18:00:45.975366+00:00`、localapp `18:00:45.972775+00:00`）；`preflight.json` 6810 B 通过、3 条 observation、`controller_answer_denied=true`、`model_calls=0`。
- 预算继承：`runtime/aiops-goal-036/product-model/run-budget.json`（203 B，SHA256 `fcd32acc2b0f3ad975afbc4ca98fb73e5161d403380cc58d849202990a7abb72`）＝ `previous_sha256=9e0fbafc62ade8238015e8939d02c8109fa1cb5d46b7df89633957e76349fca5`（035 账本）、`inherited_requests=1191`、`inherited_reserved_cny=46.82155`、`run_limit_cny=5`，累计上限 51.82155。

### 与方案文字的偏差（如实记录）

方案 B 节写的是「使用新输出目录和 035 轮次」，实际真实门跑在 **036**：035 已按方案第 4 步只在免费状态生成预算（零请求），但它的 3600 秒有效期在拿到本轮授权时只剩 187 秒，不足以完成一次真实诊断，因此保留 035 的全部材料（含 `environment-ready.json` 与两个预算文件的重算哈希）、确认其零请求后，另建 036 并继承 035 账本。为证明这一偏差不改变 B 节的实质要求，`chain-equivalence.json` 逐行核对：034 / 035 / 036 的前 1191 行规范化 JSON 摘要完全相同，历史未知 usage 项仍只有行 710（`reserved_cny=0.092916`），034 与 035 的 `reserved_cny` 同为 46.82155，035 新增 0 行、036 新增 17 行 → **036 继承到的正是 034 最新账本的 hash、条数和历史未知项**。授权范围（单轮、一次诊断、≤5 元）与停止条件不受该偏差影响。

### 5B 验收表

| 检查项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` 返回 `{"clicked":1,"post_count":1,"post_status":200}`；此后中间件对再次 POST 返回 403 |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json`（checkpoint 23 + 工具 14 + 模型请求 17 的时序轨迹）、`product/tool_trace.json`、`model-inputs/` 17 份脱敏输入、`report.txt`；**原始 SSE 帧未落盘**（`raw_sse_frames_persisted=false`），由 checkpoint 写入顺序 + 工具轨迹 + 账本重建，前端仅记录唯一一次 POST 200 |
| 以合法工具取得并引用证据 | passed | `gate-b-acceptance.json`：5 项必需证据全部 `ok=true`（已引用 + payload 哈希复算一致） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-21786db68e52462f825880936a6d24b4`（`downstream_port=7204`、`source_sha256=2c280e30e4a6158ed98c12f1a120599355ab1b2da2e53581670fdf8a05164fd7`） |
| 同请求应用失败日志 | passed | `ev-f0072dd3cf124897b0bb4c8969638f41`（`request_id=13d478b930a443e4baefd7a95002ec26`、`connection_established=false`、`error_type=TimeoutError`、status 503） |
| 错误端口无监听/不可达 | passed | `ev-7d1535e6c3e14a4daed0cc0659269d9a`（7204 无监听）、`ev-9bca828b89d7450187612a33e70ec2f9`（localapp_upstream TCP failed） |
| 登记下游健康 | passed | `ev-2b66959aea914f1d956168e169dad954`（downstream TCP ok / HTTP 200） |
| edge/localapp 同 `request_id` 失败链 | passed | `ev-19caa01484284a24a46c07f246d9d618`（edge `response_status=503`）与 localapp 日志同 `request_id` |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`、`target_id=aiops-test-df1a45ce6311` |
| 六项报告内容 | passed | `report.txt` 7088 字：诊断结论 / 影响范围 / 关键事实及引用（12 个 ev-id）/ 直接根因 / 人工处理建议（待人工核对，尚未执行）/ 剩余未知 + 未知限制 / 校验提示 |
| 不臆断无来源历史 | passed | 报告明确将变更者、变更时间、停止发起者、退出历史列为未知；`unresolved_questions` 1 项，`observation_conflicts=[]`、`contradictions=[]` |
| 刷新后报告可读 | passed | `browser-refresh-check.js`：报告卡片 15678 字，`aiops_post_after_refresh=0`，截图 `after-refresh.png` |
| 同轮次后端停止/重启后一致 | passed | `acceptance-live.json` 与 `acceptance-after-restart.json` 的 `report_sha256` 均为 `23b73151fa452c83515ddc521ffd52c12ad46120a2ab50bdad1a6e6c2cabbe9a`、`evidence_total=14`、`root_cause_code` 相同 |
| 读取阶段零模型调用 | passed | 两次读取均为 `requests 1208 → 1208`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致（字节/逻辑） | passed | 7 个产物字节一致；`runs.sqlite-wal` 与 `checkpoints.sqlite` 仅因 SQLite WAL checkpoint 变字节，逻辑摘要一致（23 checkpoints / 132 writes 前后相同）；`heartbeat-drift.json` 75 秒漂移仅 `probe_snapshots`/`probe_targets`，诊断内容 `diagnosis_content_stable=true` |
| 证据完整性 | passed | `gate-b-checks.json`：14/14 条 `raw_hash` 按 `src/probe/protocol.py:raw_hash(payload)` 复算一致，身份字段与行记录相符 |
| 预算 ≤ 本轮 5 元 | passed | 新增 17 次请求，`round_spent_cny=0.833756`，全部 `pricing_verified=true`、无未知 usage、`blocked_requests` 仍为 9（无守卫拒绝） |
| 继承 034 最新账本的 hash／条数／历史未知项 | passed | `chain-equivalence.json`：034/035/036 前 1191 行规范化 JSON 逐字节相同（`base_rows_digest_sha256` 三方一致），历史未知 usage 行仍只有 `[710]`（`reserved_cny=0.092916` 未变），034 与 035 `reserved_cny` 同为 46.82155、035 新增 0 行、036 新增 17 行；`run-budget.json` 的 `inherited_requests=1191`、`inherited_reserved_cny=46.82155`、`run_limit_cny=5` 与源账本一致 |
| 环境恢复与清理 | passed | 最终 `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`remaining_listeners=[]`、`environment_model_calls=0` |

### 关键授权与停止点

- `runtime/aiops-goal-036/product-model/cost.json`（2183777 B，SHA256 `df4c7966e5afedaae757f2b8a4b33821bc6dcee3a82b3ada9960d1ee75cbd2bf`）：`requests=1208`、`reserved_cny=47.655306`、`limit_cny=51.82155`、`blocked_requests=9`；本轮新增 17 条（行号 1192–1208），模型统一为 `deepseek-v4.1-flash-1017`。
- 剩余限制（如实记录，不掩盖）：4 条候选检查提议未通过校验（记为「检查不可调度」，见 `run-detail.json` 的 `validation_issues`）；`/steps` 返回 `total: 0`（step snapshot 未启用）；普通用户 `can_read_raw=false`，只能读摘要与元数据；`localapp` 事件通道未配置，7204 负责进程的启停历史无法核查。
- 5B 判定为 `passed`，5A 同日为 `passed`；Goal 关闭依据见下文「Goal 状态记录方式」。

### 交付物（036 轮次，含重建件）

仓库内没有任何脚本会在本轮生成 `result-summary.json` / `decision-audit.json` / `latest-state.json`（`grep` 确认仅 `scripts/replay_aiops_decision.py:41-46` 把 `result-summary.json` 当作历史目录布局探测项）；034 的同名文件由当时的临时脚本产出。为保证本轮交付物齐全，用 `runtime/aiops-goal-036/build_deliverables.py` 仅从**已持久化状态**（读取 API 落盘结果 `run-detail.json`、`product/checkpoints.sqlite`、`product/tool_trace.json`、`product/knowledge_trace.json`、`product-model/cost.json`）重建等价三件，过程只读、零模型请求、不写轮次数据库：

| 交付物 | 字节 | SHA256 | 内容要点 |
|---|---|---|---|
| `result-summary.json` | 1473 | `7193ea2aaae06c82664149feb527903275585ea42641839a13e188ff5587ed41` | 场景/线程/状态、`diagnosis_kind=confirmed_cause`、原因码、`model_calls=17`（行号 1192–1208）、`round_reserved_cny=0.833756`、`cumulative_reserved_cny=47.655306`、未知 usage 行 `[710]`、未定价 61 条、`cumulative_actual_cost=unknown`、环境三入口恢复与清理、4 个产物 hash |
| `decision-audit.json` | 23084 | `e792e177993be93163c3f057d4c073b561ad3458ed2f9dfea7a698f3f7ebf0a5` | 14 次工具调用（含参数、`validated_live_evidence=true`）、11 条去重 `past_steps`、10 次 `investigation_memory` 轨迹、`diagnosis` 通道写入（checkpoint `1f1da0d0-bb5d-657d…`）、候选/事件/校验问题计数、知识库来源、预算块 |
| `latest-state.json` | 102328 | `6d9aeb09952ad6d7382e484076f92a3b860501425405bc537e692f9e594aaf86` | 读取 API 的完整 `diagnosis` + `investigation` 对象与最终环境状态 |
| `ckpt-decoded.json` | 10880 | `0935cecbd60503b302e91167674b060197f26bfa91028022c3d6c94becb34bbc` | 23 个 checkpoint、132 次写入的通道计数与解码预览（用已安装的 `ormsgpack` 解码，venv 无 `msgpack`） |
| `event-trail-reconstructed.json` | 32308 | `a8a4bc3cd39239e14c46551efef25b60332d2a63db17244cb46c4db92893be1b` | 事件轨迹：23 个 checkpoint（含 `ts`、变更通道、`_step_progress`、plan/past_steps/evidence_events 长度）+ 14 次工具调用 + 17 次模型请求，按时间排序（`18:07:18.848564`→`18:08:35.730279`）；**`raw_sse_frames_persisted=false`**，原始 SSE 帧未落盘，仅记录前端唯一一次 POST 返回 200 |
| `chain-equivalence.json` | 2772 | `37228e8f275f2c735e05bb2fac2dc56a5185561d1f9492aa3faf0e5ea8824b4b` | 034→035→036 账本继承等价性：前 1191 行规范化 JSON 摘要、历史未知 usage 行 `[710]` 的 `reserved_cny=0.092916`、各轮 `reserved_cny`、新增行数（035 为 0、036 为 17）、两份 `run-budget.json` 的 manifest 内容（由 `verify_chain.py` 只读生成） |

`evidence-hashes.json` 已刷新为 32 个文件 + 14 个证据文件 + 17 个 `model-inputs/`，重建件的哈希与 `result-summary.json` 内 `artifact_sha256` 相互印证，`chain-equivalence.json` 亦纳入清单。

### Goal 状态（036 轮次结束时）

- `free_replay`: `passed` — 034 原始材料 75 个文件 hash 全部一致，回放忠实重现 `unlocated`（`model_calls=0`、`new_observations=0`），165 个测试通过。
- `free_environment`: `passed` — 真业务请求、同 `request_id` 双日志可达、旧日志排除、三入口 200 恢复、进程/端口/清理全部通过。
- `paid_run`: `passed` — 单轮授权，17 次新请求，新增预留 0.833756 元（上限 5 元），无未知 usage/价格，无守卫拒绝。
- `root_cause`: `passed` — `confirmed_cause` / `configured_downstream_endpoint_mismatch`，5 项必需证据全部取得并引用。
- `report_persistence`: `passed` — 刷新与同轮重启后报告/诊断对象/证据元数据/hash 一致，读取阶段新增模型请求 0。
- `cleanup`: `passed` — 三业务入口 200、所属进程已停、端口已释放、`cleanup_errors=[]`。

环境停止后再取一次逻辑摘要（`logical-digest-final.json`），与运行期重启后摘要逐项比对：报告、run 行、证据行、checkpoint、writes、users 全部一致；`probe_targets` 状态变为 `offline`（`last_seen=2026-11-06 18:17:22.575174`），属环境停用后的预期心跳变化，不影响诊断内容。

## 干净 main 复跑记录（2026-11-07）

用户要求「提交并且跑，重置 5 元预算」：把免费门代码与本文件提交到 `main`，在**干净 main** 上重跑免费门，并用新轮次 037 在**重置后的 5 元上限**下完整复跑真实门。036 的结论产生于未提交工作区，因此本轮不是重复 036，而是补上「干净 main 验证」这一缺项。

### 提交与基线

| 提交 | 说明 |
|---|---|
| `a912947` | `feat(aiops): distinguish dependency evidence coverage in healthy feedback` |
| `eddc319` | `feat(aiops): replay product-layout historical runs read-only` |
| `53b1a1a` | `docs(aiops): record free gate and 036 real gate acceptance evidence` |

- 新 HEAD `53b1a1acfea88ee9d3ff19c541172c4af7d7919f`，`## main...origin/main [ahead 72]`；跟踪文件全部干净，仅剩一个与本任务无关的未跟踪文件 `pelican-bicycle.html`（2026-11-03 生成，仓库内零引用），因此**未**纳入提交。
- 基线材料：`runtime/aiops-goal-clean-20261107-c/`（`HEAD.txt`、`git-status.txt`、`log.txt`）。
- 干净 main 免费门：`runtime/aiops-goal-freegate-20261107-c/`
  - 回放 `replay.json` 90688 B（SHA256 `6225780b2ce0…`）、`report.txt` 7433 B（`b8be15cba51e…`）：`original_kind=unlocated`、`replayed_kind=unlocated`、`model_calls=0`、`original_artifacts_unchanged=true`。
  - 回归 `pytest-clean.xml` 26109 B（`fc5888b55b58…`）：**165 passed**，唯一警告仍为既有 PyMilvus 弃用。
  - 034 原始材料 75/75 hash 一致（`originals_check {files: 75, mismatched: 0}`）。

### 037 轮次环境与预算（5 元上限重置）

- 轮次：`runtime/aiops-goal-037`，场景 `endpoint`，round 1，`target_id=aiops-test-e0e42f4d99dc`，`gateway_url=http://127.0.0.1:3585/mcp`，业务端口 edge 3581 / localapp 3582 / downstream 3583 / 无监听 3584。
- 首次业务请求 `ff76017e90ba474993fa806ce30b8ade` 返回 503；`preflight.json` 6810 B 通过，`controller_answer_denied=true`、`model_calls=0`。
- `product-model/run-budget.json`（204 B，SHA256 `b14fb5331142b7761b4c3cd12120b83b09afb1cb2308667037b5a37e2ac2b592`）＝ `previous_sha256=df4c7966e5afedaae757f2b8a4b33821bc6dcee3a82b3ada9960d1ee75cbd2bf`（036 账本）、`inherited_requests=1208`、`inherited_reserved_cny=47.655306`、`run_limit_cny=5`，累计上限 `52.655306` → **本轮可用额度确实是重新计量的 5 元**，历史 47.655306 元只作继承基线、不占用新额度。

### 5B 验收表（037 轮次）

| 检查项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` → `{"clicked":1,"post_count":1,"post_status":200}`；截图 `start.png` 76515 B |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json` 30793 B（checkpoint 21 + 工具 14 + 模型请求 17）、`product/tool_trace.json`、`model-inputs/` 17 份脱敏输入；**原始 SSE 帧仍未落盘**（`raw_sse_frames_persisted=false`） |
| 以合法工具取得并引用证据 | passed | `gate-b-acceptance.json` 5135 B：5 项必需证据全部 `ok=true cited=true hash=true`；14/14 条 `raw_hash` 复算一致（`gate-b-checks.json`） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-489a856932ea436590337ca8291e0e91`（`downstream_port=3584`、`upstream_timeout_seconds=0.5`、`source_sha256=459d7933…`） |
| 同请求应用失败日志 | passed | `ev-59d2ca7b56fe4cee8dc3f3291e9750ad`（`request_id=ff76017e…`、`connection_established=false`、`error_type=TimeoutError`、status 503）、`ev-ecd0f9772e574d80a4bbc377e8256ece` |
| 错误端口无监听/不可达 | passed | `ev-b87ff06cb6ea4695914fc147029d8c04`（3584 无监听）、`ev-924599553e2e4157b57e89b957365da4`（localapp_upstream TCP failed / URLError） |
| 登记下游健康 | passed | `ev-36f6899d32994006a04eb4468c4a2034`（downstream TCP ok / HTTP 200）、`ev-95a0be32f70544beb3a29355a1957d23`（3583 监听 PID 33480） |
| edge/localapp 同 `request_id` 失败链 | passed | `ev-115cb5934529438186b8c728873c60e4`（edge `phase=completed`、`connection_established=true`、`response_status=503`）与 localapp 日志同 `request_id` |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`、`thread_id=web-rz98ua5z-8cfd134c4c3a4cd4955df1dad1ba3967` |
| 六项报告内容 | passed | `report.txt` 9180 B（`f3001b55…`），6120 字：诊断结论 / 影响范围 / 关键事实及引用（12 个 ev-id）/ 直接根因 / 人工处理建议（待人工核对，尚未执行）/ 剩余未知 + 未知限制 / 校验提示 |
| 不臆断无来源历史 | passed | 变更者、变更时间、退出历史均列为未知；`unresolved_questions` 1 项（0.5 秒上游超时是否过短，`q-123af3208bb6`）；`observation_conflicts=[]`、`contradictions=[]` |
| 刷新后报告可读 | passed | `browser-refresh-check.js` → 报告 13247 字符、`aiops_post_after_refresh=0`；截图 `after-refresh.png` 86250 B |
| 同轮次后端停止/重启后一致 | passed | `acceptance-live.json` 与 `acceptance-after-restart.json`：`report_sha256` 均为 `34a4de2818b35ca73609fc0691e4ff417a4e94e3355ec55a7aa97122184d8918`、`evidence_total=14`、原因码相同 |
| 读取阶段零模型调用 | passed | 两次读取均为 `requests 1225 → 1225`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致（字节/逻辑） | passed | 7 个产物重启前后字节一致；`runs.sqlite-wal`、`checkpoints.sqlite` 仅因 SQLite WAL checkpoint 变字节（`checkpoint_counts_note` 如实说明逐字节不可比，以重启后行计数 21 checkpoints / 121 writes 为准），`heartbeat-drift.json` 显示诊断内容 `diagnosis_content_stable=true` |
| 证据完整性 | passed | `gate-b-checks.json`：14/14 `payload_hash` 与声明一致、身份字段相符 |
| 预算 ≤ 本轮 5 元 | passed | 17 次新请求（1209–1225）、`round_spent_cny=0.920086`、全部 `pricing_verified=true`、无未知 usage、`blocked_requests` 仍为 9 |
| 继承上一轮最新账本 | passed | `chain-equivalence.json` 1658 B：036 与 037 前 1208 行规范化 JSON 逐字节相同、历史未知 usage 仍只有 `[710]`（`reserved_cny=0.092916`）、各轮新增行数 `{034:1191, 035:0, 036:17, 037:17}` |
| 环境恢复与清理 | passed | `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0` |

### 037 交付物

| 交付物 | 字节 | SHA256 |
|---|---|---|
| `result-summary.json` | 1544 | `3ee8fba045cf…` |
| `decision-audit.json` | 23534 | `4a608dee1826…` |
| `latest-state.json` | 76272 | `441f4172c415…` |
| `ckpt-decoded.json` | 9974 | — |
| `event-trail-reconstructed.json` | 30793 | — |
| `chain-equivalence.json` | 1658 | `fdd5501038a3…` |
| `evidence-hashes.json` | 32 个文件 + 14 证据 + 17 `model-inputs/` | 逐条复算 0 缺失 0 不符 |

### 037 剩余限制（如实记录）

- 原始 SSE 帧仍未落盘，轨迹由 checkpoint 写入顺序 + 工具轨迹 + 模型输入 + 账本重建。
- 4 条候选检查提议未通过校验（重复检查或缺少必需字段，记为「检查不可调度」）；`/steps` 返回 `total: 0`；普通用户 `can_read_raw=false`；`localapp` 事件通道未配置。
- 与 036 的差异仅在于：本轮全部结论产生于**已提交的干净 main**（`53b1a1a`，跟踪文件无改动），不再带有「未提交工作区」的限制。

## 038 轮次复跑记录（2026-11-07）

用户回复 `1`，选择「再跑一轮真实诊断（新授权、新目录、继承 037 账本、5 元上限重新计量）」。本轮不是重试失败轮次，而是在同一规则下再做一次独立复现，用于确认 037 的通过不是偶发。

### 环境与预算

- 轮次目录 `runtime/aiops-goal-038`，场景 `endpoint`，round 1，`target_id=aiops-test-64da610213e2`，`gateway_url=http://127.0.0.1:9894/mcp`，业务端口 edge 9890 / localapp 9891 / downstream 9892 / 无监听 9893。
- 首次业务请求 `5cd71721242b45b180ae61caa5892e8b` 返回 503；`preflight.json` 6810 B（`f221fb21…`）通过，`controller_answer_denied=true`、`model_calls=0`。
- `product-model/run-budget.json`（204 B，SHA256 `cc547e2c4e0ec5cb9427b295061d1847a284e5a0dbdd3863d08b6182e2c32ccf`）＝ `previous_sha256=56003c52781d…`（037 账本）、`inherited_requests=1225`、`inherited_reserved_cny=48.575392`、`run_limit_cny=5`，累计上限 `53.575392` → 本轮可用额度仍是重新计量的 5 元。
- 后端启动命令与 037 相同（`--run-model --profile .env.agent-test --previous-cost runtime/aiops-goal-037/product-model/cost.json`），端口 8200。

### 5B 验收表（038 轮次）

| 检查项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` → `{"clicked":1,"post_count":1,"post_status":200}`；`start.png` 82382 B（`19891515…`） |
| 以合法工具取得并引用证据 | passed | `gate-b-acceptance.json` 4475 B（`e9ecb1af…`）：5 项必需证据全部 `ok=true cited=true hash=true`；14/14 `raw_hash` 复算一致 |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-2d3bf62ff6494e55a834105dd8bcbcf8`（`downstream_port=9893`、`source_sha256=5bcd847b…`） |
| 同请求应用失败日志 | passed | `ev-6cb22a72f1614daf8710b1ee3f0c5b99`（`request_id=5cd71721…`、`connection_established=false`、status 503） |
| 错误端口无监听/不可达 | passed | `ev-1856355944bc44cf99e2c5e7171fdd1b`（9893 `matched_count=0`）、`ev-9acfc09855084968838f4c6eb2436b8f`（localapp_upstream TCP failed / ConnectionRefusedError） |
| 登记下游健康 | passed | `ev-0288c7d78abf41bd9927c3a1ba237885`（downstream TCP ok / HTTP 200） |
| edge/localapp 同 `request_id` 失败链 | passed | `ev-0c611d3e53cb443e95dfe3c937040076`（edge）与 `ev-6cb22a72f1614daf8710b1ee3f0c5b99`（localapp）同 `request_id`，edge 返回 503 |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`、`thread_id=web-ge9b40bd-1141bb9351384a21a89a32f85b808b36` |
| 六项报告内容 | passed | `report.txt` 11680 B（`28d0b0c6…`），7568 字（`report_sha256=cd9acfb3fccd…`）：诊断结论 / 影响范围 / 关键事实及引用（12 个 ev-id）/ 直接根因 / 人工处理建议（待人工核对，尚未执行）/ 剩余未知 + 未知限制 / 校验提示 |
| 不臆断无来源历史 | passed | 变更者、变更动机、退出历史均列为未知；`unresolved_questions` 1 项（9893 曾运行实例被停止，`q-5fb5959aa547`）；`observation_conflicts=[]`、`contradictions=[]` |
| 刷新后报告可读 | passed | 报告 16033 字符、`evidence_nodes=43`、`aiops_post_after_refresh=0`；`after-refresh.png` 86908 B（`f83dc8b8…`） |
| 同轮次后端停止/重启后一致 | passed | `acceptance-live.json` 与 `acceptance-after-restart.json`：`report_sha256` 均为 `cd9acfb3fccd3726d9b8f776e4d0af9730beeaa71845d8a4bb90728cbedb52a0`、`evidence_total=14`、原因码相同 |
| 读取阶段零模型调用 | passed | 两次读取均为 `requests 1240 → 1240`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致（字节/逻辑） | passed | 7 个产物重启前后字节一致；`runs.sqlite-wal`、`checkpoints.sqlite` 仅因 WAL checkpoint 变字节（以重启后 23 checkpoints / 132 writes 行计数为准）；`heartbeat-drift.json` `diagnosis_content_stable=true` |
| 证据完整性 | passed | `gate-b-checks.json` 17021 B（`f35e2a2d…`）：`evidence_all_hash_verified=true`、`bad evidence: []` |
| 预算 ≤ 本轮 5 元 | passed | 15 次新请求（1226–1240）、`round_spent_cny=0.794704`、累计 `49.370096`、全部已定价、无未知 usage、`blocked_requests` 仍为 9 |
| 继承上一轮最新账本 | passed | `chain-equivalence.json` 1888 B（`d2d4a276…`）：037 与 038 前 1225 行规范化 JSON 逐字节相同、行 1–1191 五份账本全部一致、未知 usage 仍只有 `[710]`、新增行数 `{034:1191, 035:0, 036:17, 037:17, 038:15}` |
| SSE 事件、工具执行、模型输入与结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json` 31745 B（`15dea98a…`：checkpoint 23 + 工具 14 + 模型请求 15）、`product/tool_trace.json` 30341 B、`model-inputs/` 15 份脱敏输入；**原始 SSE 帧仍未落盘**（`raw_sse_frames_persisted=false`） |
| 环境恢复与清理 | passed | `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`、`ended_at=2026-11-06T20:13:58.666338Z`；9890–9894 与 8200 均无监听 |

### 038 交付物

| 交付物 | 字节 | SHA256 |
|---|---|---|
| `result-summary.json` | 1522 | `c5de7d220a84…` |
| `decision-audit.json` | 22999 | `b79227b01252…` |
| `latest-state.json` | 104841 | `61b9317c41e3…` |
| `ckpt-decoded.json` | 10617 | `ae8204b4b69b…` |
| `event-trail-reconstructed.json` | 31745 | `15dea98a18d7…` |
| `chain-equivalence.json` | 1888 | `d2d4a276dcfd…` |
| `gate-b-checks.json` / `gate-b-acceptance.json` | 17021 / 4475 | `f35e2a2de177…` / `e9ecb1af2bbd…` |
| `evidence-hashes.json` | 32 个文件 + 14 证据 + 15 `model-inputs/` | 逐条复算 0 缺失 0 不符 |

### 038 剩余限制（如实记录）

- 原始 SSE 帧仍未落盘，轨迹由 checkpoint 写入顺序 + 工具轨迹 + 模型输入 + 账本重建。
- 4 条候选检查提议未通过校验（重复检查或缺少必需字段）；`/steps` 本轮复核返回 `{"status": 200, "total": 0}`（步骤快照未启用）；普通用户 `can_read_raw=false`；`localapp` 事件通道未配置。
- 本轮模型证据条目为 10 条（036/037 为 12/14 条），报告引用 14 条证据中的 12 条；未引用的两条是端口全量列表与主机清单，不影响五类必需证据的引用完整性。

### 038 对 Goal 判定的影响

038 在同样规则下独立复现了 `completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`，落盘、重启、刷新、预算、清理各项结论与 037 完全一致，因此「Goal 完成判定」表中六个状态位的 `passed` 结论得到第二次干净 main 复跑的支持；本轮新增预留 0.794704 元，累计预留 49.370096 元，历史 48.575392 元仍只作继承基线。

## 039 轮次复现记录（2026-11-07）——本轮未通过

用户回复 `1`，选择第三次干净 main 真实门复现（新授权、新目录、继承 038 账本、5 元上限重新计量）。**本轮结论为 `localized_fault`，未达到 5B 的「`completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`」，如实记为 `failed`。**

### 环境与预算

- 轮次目录 `runtime/aiops-goal-039`，场景 `endpoint`，round 1，`target_id=aiops-test-6288fcf3a11f`，`gateway_url=http://127.0.0.1:8945/mcp`，业务端口 edge 8941 / localapp 8942 / downstream 8943 / 无监听 8944；`business/localapp.connection.json` 为 `{"downstream_port": 8944, "upstream_timeout_seconds": 0.5}`。
- 首个业务请求 `4b1204977d3a4227a122807bb0f10bcc` 返回 503（edge `2026-11-07T00:32:16.016141+00:00`、localapp `...16.013285+00:00`）；`preflight.json` 6810 B（`fb251c8d…`）通过，`controller_answer_denied=true`、`model_calls=0`。
- `product-model/run-budget.json`（204 B，SHA256 `334594ad04e0155b57cfb4ede6695dcb52c9126b2579124ba4d2f253983f974a`）＝ `previous_sha256=bf90c874325f…`（038 账本）、`inherited_requests=1240`、`inherited_reserved_cny=49.370096`、`run_limit_cny=5`，累计上限 `54.370096` → 本轮额度重新计量为 5 元。
- 后端命令同前（`--run-model --profile .env.agent-test --previous-cost runtime/aiops-goal-038/product-model/cost.json`），端口 8200；`browser-start.js` 点击结果为 `clicked=1 / post_count=1 / post_status=200`。

### 5B 验收表（039 轮次）

| 检查项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` → `{"clicked":1,"post_count":1,"post_status":200}`；`start.png` 82386 B（`4c99077b…`）；首 POST 后中间件即拒绝再次诊断 |
| 以合法工具取得并引用证据 | passed | 13 次 probe 工具调用全部 `validated_live_evidence=true`；结论引用 6 个证据 id（含全部 5 个必需 id） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-84fff6337dde452483f8ad0a773a7632`：`downstream_port=8944`、`upstream_timeout_seconds=0.5`、`source_sha256=7b882591…2383` |
| 同请求应用失败日志 | passed | `ev-1781cfbaca4f448ca54b0636075c198a`：`request_id=4b1204977d3a4227a122807bb0f10bcc`、`connection_established=false`、`TimeoutError`、status 503 |
| 错误端口无监听/不可达 | passed | `ev-fd5bb6a1c06e40d29aa3d9771aeb5808`（8944 `matched_count=0`）、`ev-fed55b84389f4659add61ba2b8f79d23`（localapp_upstream TCP failed） |
| 登记下游健康 | passed | `ev-22c1afc6c2554bed9173fd1dffbe932d`（downstream TCP ok / HTTP 200） |
| edge-localapp 同 `request_id` 失败链 | passed | `ev-b86c1b17574840a2afce77b6f88214a5`（edge 已连上 localapp、`phase=completed`、`response_status=503`）+ `ev-1781cfba…`（localapp connect 阶段失败） |
| 最终 `completed` + `confirmed_cause` + 原因码 | **failed** | 最终 `kind=localized_fault`、`root_cause_code=''`；`thread_id=web-l9pijv5a-80eb20f4912444438b076be01404e146`、`status=completed`、报告 4334 字 |
| 六项报告内容 | passed | `report-quick.txt` 6795 B（`c98848e5…`）含已定位故障层 / 关键事实及引用 / 人工处理建议（待人工核对）/ 剩余未知；但标题为「故障层已定位，深层原因未明」 |
| 不臆断无来源历史 | passed | 8944 无监听的历史原因、变更者与变更时间均标为未知，未作断言 |
| 刷新后报告可读 | passed | 报告 11154 字符、`evidence_nodes=39`、`aiops_post_after_refresh=0`；`after-refresh.png` 81805 B（`cb8bcc80…`） |
| 同轮次后端停止/重启后一致 | passed | `acceptance-live.json`：`report_sha256=e13e19b4c93863fc807c8dc69cf084e4fa482047d437d49c2f8950ba6bcc9f12`、`evidence_total=13`；重启后复读同值 |
| 读取阶段零模型调用 | passed | `requests 1254 → 1254`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-after-restart.json` 2978 B（`d863e540…`）：run/evidence/checkpoints 行级摘要与重启后一致（checkpoints 17、writes 99），`diagnosis_kind_matches_live=true` |
| 证据完整性 | passed | 13 条证据 payload `raw_hash` 复算一致（`evidence-hashes.json` 27 文件 + 13 证据 + 14 `model-inputs/`，独立复算 0 缺失 0 不符） |
| 预算 ≤ 本轮 5 元 | passed | 14 次新请求（1241–1254）、`round_reserved_cny=0.613538`、累计 `49.983634`、全部 `deepseek-v4.1-flash-1017` 且已定价、无新增未知 usage、`blocked_requests` 仍为 9 |
| 继承 038 最新账本 | passed | `chain-equivalence.json` 2299 B（`121b0000…`）：038/039 前 1240 行规范化 JSON 逐字节相同、1–1191 六份账本一致、未知 usage 仍只有 `[710]`、新增行数 `{034:1191, 035:0, 036:17, 037:17, 038:15, 039:14}`、`chain_equivalent=true` |
| 环境恢复与清理 | passed | `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`、`ended_at=2026-11-07T00:48:45.508157Z`；8940–8945 与 8200 均无监听 |

### 未通过的直接原因（代码级取证）

本轮失败不是模型没找到原因，也不是缺证据：checkpoint 中 `investigation_memory.model_suggestion` 明确写着 `conclusion_level='confirmed_cause'`、`outcome='root_cause'`、`root_cause_code='configured_downstream_endpoint_mismatch'`，`supporting_evidence` 14 条覆盖配置哈希、localapp 失败日志、edge 转发、downstream 探活与 8944 无监听，`validation_issues` 只剩两条非关键未知。

- 模型同时把「8944 无监听的深层历史原因未知」写进了 `contradictions` 字段（原文：「…不同超时/探测方式下网络异常名不同，不自动构成矛盾，但 8944 无监听的历史原因仍未知。」）。
- `src/agent/aiops/strategies/investigation.py:3793-3806` 的 `sufficient` 是合取式，其中含 `not decision.contradictions`；该字段被当作硬性否决条件。
- `runtime/aiops-goal-039/simulate_gate.py` 用原始 checkpoint 决策逐条复算：`root_cause_or_healthy / citations_valid / has_alternatives / alternatives_ok / has_scope / level_confirmed_cause / required_evidence_known / required_evidence_cited / observations_untruncated` 全部为 `true`，唯一为 `false` 的是 `no_contradictions`；把 `contradictions` 清空后重新判定，失败子句列表为空。
- 因此系统走 `:3940-3962` 的 `_localized_findings` 降级路径，输出 `localized_fault` 并把 `root_cause_code` 清空。

判定：本轮失败归因于「待核实说明字段与结论充分性判定耦合」这一产品侧逻辑，而非证据链或模型提议缺陷；该缺陷本次首次暴露，前 036/037/038 三轮都因模型未写 `contradictions` 而通过。

### 039 交付物

| 交付物 | 字节 | SHA256 |
|---|---|---|
| `result-summary.json` | 1472 | `6fdb57798d29…` |
| `decision-audit.json` | 22180 | `6a24b6e63d82…` |
| `latest-state.json` | 76137 | `8642fbc23723…` |
| `ckpt-decoded.json` | 8959 | `d9c7301663fc…` |
| `event-trail-reconstructed.json` | 25793 | `fcdd8ace5826…` |
| `chain-equivalence.json` | 2299 | `121b00008880…` |
| `gate-b-verdict.json` | 8472 | `d533d97641ce…` |
| `simulate-gate.log`（降级复算） | 2716 | `9a20d7315632…` |
| `report-quick.txt` | 6795 | `c98848e5570b…` |
| `evidence-hashes.json` | 6931 | 27 文件 + 13 证据 + 14 `model-inputs/`，逐条复算 0 不符 |

### 039 剩余限制（如实记录）

- 本轮没有 `gate-b-acceptance.json` / `gate-b-checks.json` / `wal-attribution.json` / `heartbeat-drift.json`：这些是「通过轮次」的验收件，本轮既未通过，不伪造。
- 原始 SSE 帧仍未落盘；轨迹由 checkpoint 写入、工具轨迹、模型输入与账本重建（`raw_sse_frames_persisted=false`）。
- 4 条候选检查提议未通过校验（三条为「该检查步骤此前已执行」，一条为假设文字含义未验证）。

### 039 对 Goal 判定的影响

039 未通过，因此「可复现性」结论必须修正为 **036/037/038 三轮通过、039 一轮未通过**，而不是此前写的「连续多轮稳定复现」。六个状态位本身的证据链（免费门、付费单轮、根因码、持久化、清理）仍然成立且可复核，但 Gate B 结论的可复现率是 3/4，且失败模式已定位到具体代码子句。修复方向（供用户决定，本次未改代码）：把 `contradictions`（待核实说明）与「已知现场事实冲突」分开，`sufficient` 只对真正的事实冲突否决结论，或在降级前把「结论已满足证据要求但存在待核实说明」作为可诊断项暴露出来，而不是直接改写为 `localized_fault`。

## 判定逻辑修复（2026-11-07，用户授权「修判定逻辑再复跑」）

按 039 的取证结论改了一处判定逻辑，让「模型自己写的待核实说明」不再一票否决已满足证据要求的结论，而系统自己算出的现场事实冲突继续否决。

### 改动

| 文件 | 改动 |
|---|---|
| `src/agent/aiops/strategies/investigation.py` | `decide_from_evidence` 里把两类系统派生的冲突（`等待模型后现场证据未通过重新校验：…`、`引用已被同范围不同结果更新：…`）先收集进局部变量 `field_conflicts`，再 append 到 `decision.contradictions`；`sufficient` 的对应子句由 `not decision.contradictions` 改为 `not field_conflicts` |
| `tests/test_investigation_fusion.py` | 新增 `_endpoint_state_with_request_logs(...)` / `_endpoint_cause_decision(...)` 两个 helper 与两条测试：`test_pending_model_note_does_not_block_a_fully_cited_confirmed_cause`、`test_system_detected_field_conflict_still_blocks_a_confirmed_cause` |

保留不变：`diagnosis['contradictions']` 仍原样输出模型原文（`_public_text`），未定位报告仍打印「待核实说明（不作为可靠反证）：…」，`investigation_memory` 仍保存原文。报告层本来就把 `contradictions`（模型待核实说明）与 `conflicts`（`observation_conflicts`，现场事实冲突）分成两个键，本次修改与既有对外契约一致。

### 为什么不能直接删掉这个子句

`decision.contradictions` 里同时装着系统派生的两类真实冲突（证据在模型等待期间失效、引用被同范围更新结果覆盖）。这两条必须继续否决结论，因此改的是「用哪一份列表否决」，不是取消否决。

### 验证

| 项 | 结果 |
|---|---|
| 039 真实提议回放（`runtime/aiops-goal-039/replay_fixed.py` → `replay-fixed.json` 697 B `9a43713ac317…`） | 修复前 `localized_fault` / `code=''`；修复后 **`confirmed_cause` / `configured_downstream_endpoint_mismatch`**，`evidence_cited=14`，模型原文 `contradictions` 原样保留（`model_note_preserved=true`）；保留真实 `past_steps` 的变体同样得到 `confirmed_cause`，`model_calls=0` |
| 新增两条单测 | 均通过：模型待核实说明不阻止 `confirmed_cause`；系统 `superseded_citations` 冲突仍降级为 `localized_fault` 且 `investigation_memory['contradictions'] == diagnosis['contradictions']` |
| 四个核心测试文件 | `tests/test_investigation_strategy.py tests/test_investigation_boundaries.py tests/test_investigation_fusion.py tests/test_decision_replay.py` → **289 passed**（原 287 + 新增 2），唯一警告为既有 PyMilvus 弃用 |
| 全量 `pytest tests` | **2060 passed / 37 failed / 99 deselected**；37 个失败与干净 HEAD（`git stash` 后）完全同一集合（`test_matching503_output_flow.py` 24、`test_four_issue_closeout.py` 6、`test_agent_knowledge_consumption.py` 5、`test_live_probe_mechanisms.py` 1、`test_probe_summary_output_flow.py` 1），即**既存失败，与本次改动无关** |

### 仍未做的事

本次只改判定逻辑并验证，没有跑新的付费轮次。要确认「修复后能稳定得到 `confirmed_cause`」，仍需用户单独授权一轮真实复跑（新目录、继承 039 账本、5 元上限重新计量）。

## 040 轮次复跑记录（2026-11-07）——修复后验证轮

用户授权（m02692「继续」）后的单轮付费复跑，目的是验证「判定逻辑修复后同一场景能否重新得到 `confirmed_cause`」。

### 环境与预算

- 新目录 `runtime/aiops-goal-040`（起跑前不存在），起跑基线 `git rev-parse HEAD` = `9f1e5e12fdac8251c9459a664fa3fe655d1e7ff1`、`## main...origin/main [ahead 76]`、仅 `?? pelican-bicycle.html`；8200 无监听、0 个 python 进程。
- `scripts/aiops_test_environment.py start --output runtime\aiops-goal-040 --scenario endpoint --duration-seconds 3600` → `status=ready`、`target_id=aiops-test-dc101f05f6ff`、`gateway_url=http://127.0.0.1:11379/mcp`、round 1、`environment_acceptance=passed`、`business_url=http://127.0.0.1:11376/api/availability`、首个业务请求 `56399ec938f04f23a029d2b79351a478` 返回 **503**（edge `2026-11-07T05:20:32.441724+00:00`、localapp `...32.440863+00:00`）、`environment_model_calls=0`、`preflight.json` 6816 B `passed`、`controller_answer_denied=true`。
- 业务端口 edge 11376 / localapp 11377 / downstream 11375 / 无监听 11378（`business/localapp.connection.json` = `{"downstream_port": 11378, "upstream_timeout_seconds": 0.5}`）；gateway 11379；backend 8200。实测入口 `503`，11378 无监听 → 场景正确。
- 付费后端 `... backend --output runtime\aiops-goal-040 --port 8200 --run-model --profile .env.agent-test --previous-cost runtime\aiops-goal-039\product-model\cost.json` → 8200 监听、`/login` 200 `text/html; charset=utf-8` 780 B。
- **5 元额度重新计量已核验**：`product-model/run-budget.json` 204 B `dc9f6b4ba900d6156c18e69550379b062f9398b2d2420f5854c693392162e677` = `{"version":1,"previous_sha256":"235b30bff2f04071813cf410bb8d745e22690252b547963b8dabb4ed629b96af","inherited_requests":1254,"inherited_reserved_cny":49.983634,"run_limit_cny":5}`；轮次 `cost.json` 2271008 B `6f91fa5cda5aa30f3fe759df7c4d896f6167ade5f35d4a9456f6840f1de5b247`、1254 行、`reserved_cny=49.983634`、`limit_cny=54.983634`、`blocked_requests=9`、`model-inputs/` 不存在。

### 单次点击与结论

- `playwright-cli -s=aiops040` 登录后进 `/aiops`，`browser-start.js` 只点一次「开始诊断」→ `{"clicked":1,"post_count":1,"post_status":200}`，计划 6 步，`start.png` 80299 B。
- 运行行 `thread_id=web-jx3cjas0-b9cc23d8a553484e8a026fd621e600b4`、`completed`、`2026-11-07 05:22:40` → `05:24:01`、报告 7189 字符（`report.txt` 10490 B）。
- **`kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`、`target=aiops-test-dc101f05f6ff`、version 1、`evidence` 13 条、`contradictions=[]`、`observation_conflicts=[]`**，`mechanisms` `hypothesis_protection/contradiction_trigger=true`、`protection_steps=2`、`leading_id=h-563bc2f551d5c9f1`、`current_prediction_contradicted=false`。
- 报告关键事实：localapp 加载的配置 `downstream_port=11378`（配置快照 `source_sha256=e5bf09f7…a72a`，与启动日志加载哈希一致）vs 登记 downstream 实际监听 11375（TCP ok / HTTP 200）；请求 `56399ec9…` 在 localapp 侧 `phase=connect`、`connection_established=false`、`TimeoutError`、`detail=upstream connection failed`、返回 503；edge 侧同 `request_id` `phase=completed`、`connection_established=true`、`response_status=503`（原样转发）；11378 探测 `tcp=failed`（ConnectionRefusedError）。五类必需证据 id：`ev-a8ea6c2748694afeae7ad71561f8a02b`（配置端口+哈希）、`ev-00795a406c4b4d74b2c174b2d658cac2`（同请求应用失败日志）、`ev-43b4e07c324c48feb7e3bafca1800445` + `ev-8e7cdaa594094a018cb84c8cdf8d94f0`（错误端口无监听/不可达）、`ev-d7540e1a9fcc4073a578d38f4db0c689`（登记下游健康）、`ev-b5f66a238d174aeb8a103a4d3690647d` + `ev-ee80deecdecd48ea87d300a14e756754`（edge/localapp 同 `request_id` 链）。
- 报告六项内容齐全（逐字命中）：`已确认直接原因`、`影响范围`、`关键事实及引用`、`直接根因`、`人工处理建议（待人工核对，尚未执行；不作为根因证明）`、`剩余未知` + `未知限制`（4 条）+ `校验提示`；引用 14 条证据中的 11 条，未臆断无来源历史（变更者/动机/退出历史均列为未知）。

### 5B 验收表（040 轮次）

| 项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` 结果 `{"clicked":1,"post_count":1,"post_status":200}`；`start.png` 80299 B `50d59544…` |
| 以合法工具取得并引用证据 | passed | 14 次工具调用全部 `validated_live_evidence=true`（`product/tool_trace.json`）；`gate-b-acceptance.json` 五类 `ok/cited/hash` 全 true |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-a8ea6c2748694afeae7ad71561f8a02b`（`downstream_port=11378`、`source_sha256=e5bf09f7…a72a`） |
| 同请求应用失败日志 | passed | `ev-00795a406c4b4d74b2c174b2d658cac2`（`request_id=56399ec9…`、`connection_established=false`、503） |
| 错误端口无监听/不可达 | passed | `ev-43b4e07c324c48feb7e3bafca1800445`（11378 无监听）+ `ev-8e7cdaa594094a018cb84c8cdf8d94f0`（TCP failed / ConnectionRefusedError） |
| 登记下游健康 | passed | `ev-d7540e1a9fcc4073a578d38f4db0c689`（11375 TCP ok / HTTP 200） |
| edge/localapp 同 `request_id` 失败链 | passed | `ev-b5f66a238d174aeb8a103a4d3690647d` + `ev-ee80deecdecd48ea87d300a14e756754` |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `run-detail.json` / `ckpt-decoded.json`（checkpoint `1f1da6b6-9a9b-6038-8010-0e0b51104c97`） |
| 六项报告内容 | passed | `report.txt` 10490 B `report-headings.json` 六项全 true |
| 不臆断无来源历史 | passed | 报告把变更者/动机/退出历史列为未知，`contradictions=[]` |
| 刷新后报告可读 | passed | 刷新后 15012 字符、`evidence_nodes=42`、`aiops_post_after_refresh=0`；`after-refresh.png` 84314 B |
| 同轮次后端停止重启后一致 | passed | `acceptance-live.json` 与 `acceptance-after-restart.json` 均 `report_sha256=87984ac7ba237f64df0ab015e93ba9ff1e2fa2675a876fdad6b801474632288b`、`evidence_total=14` |
| 读取阶段零模型调用 | passed | 两次读取 `requests 1269 → 1269`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-after-restart.json` / `logical-digest-final.json`（重启后与停止后 `all identical: True`，仅 `probe_targets` 心跳转 offline） |
| 证据完整性 | passed | `gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []` |
| 预算 ≤ 5 元 | passed | 新增 15 次请求（1255–1269）新增预留 `0.776214` 元，`within_run_cap=true`，`blocked_requests` 仍 9，无未定价/未知新行 |
| 继承 039 最新账本 | passed | `chain-equivalence.json` `chain_equivalent=true`、`rows_1_to_history_byte_identical_all_seven=true`、`rows_added_per_round {034:1191,035:0,036:17,037:17,038:15,039:14,040:15}` |
| 环境恢复与清理 | passed | `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`、`ended_at=2026-11-07T05:28:03.476821Z` |

### 040 交付物

| 文件 | 字节 | SHA256（前 12 位） |
|---|---|---|
| `result-summary.json` | 1522 | `2aedce8ccd50` |
| `decision-audit.json` | 21941 | `016ae46edc40` |
| `latest-state.json` | 79798 | `714c2fa2ed41` |
| `event-trail-reconstructed.json` | 28231 | `e9f6cb7ddda0` |
| `chain-equivalence.json` | 2273 | `37d3175840fb` |
| `gate-b-acceptance.json` | 4710 | `d42a32cd26d0` |
| `gate-b-checks.json` | 16836 | `11d59a839821` |
| `report.txt` | 10490 | `070c5fa1d5e9` |
| `after-refresh.png` | 84314 | `328c5b60702b` |
| `evidence-hashes.json` | 8183 | `e09292df6360`（34 个文件 + 14 个证据 + 15 份 `model-inputs/`，独立复算 `bad 0 / missing 0`） |

`result-summary.json` 记录的 `artifact_sha256` 四条（`run-detail.json`、`product-model/cost.json`、`decision-audit.json`、`latest-state.json`）已逐条与磁盘复核一致。

### 040 剩余限制（如实记录）

- 原始 SSE 帧仍未落盘（`event-trail-reconstructed.json` 的 `raw_sse_frames_persisted=false`），时序轨迹由 checkpoint + 工具轨迹 + 账本重建。
- 3 条候选检查提议因「已有该对象和参数的检查结果」被拒（`validation_issues`），1 条未决问题 `q-d5395232406e`（downstream 在请求后收到停止请求并退出）保留为未知。
- `probe_process_snapshot` 对一处对象返回 `service_outside_business_scope`（检查受限），报告已如实标注「相关问题仍未核验」。
- `/steps` 未启用、普通用户 `can_read_raw=false`、localapp 事件通道未配置（与 036–039 一致）。
- 本轮 `diagnosis.evidence` 为 13 条（036 为 12、037/038 为 14），引用 11 条；条数随模型选的检查组合变化，不作为通过条件。

### 040 对 Goal 判定的影响

040 在同一 `endpoint` 场景、同一检查口径下重新得到 `confirmed_cause` + `configured_downstream_endpoint_mismatch`，证明「判定逻辑修复」确实恢复了该场景的正确结论——039 的失败是判定逻辑缺陷，不是模型能力问题。至此 Gate B 可复现率为 **4/5**（036/037/038/040 通过、039 未通过且原因已修复并验证）。

## 041 轮次复现记录（2026-11-08）——修复后第二次复现，本轮未通过

用户回复 `1`（m03976），选择「再跑一轮 041 做修复后第二次复现」。**本轮结论为 `localized_fault`，未达到 5B 的「`completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`」，如实记为 `failed`。**

### 环境与预算（041 轮次）

- 轮次目录 `runtime/aiops-goal-041`（起跑前不存在），起跑基线 `git rev-parse HEAD` = `981e110c0a4901f5fae2edb07bf853e1ce9e7fc7`、`## main...origin/main [ahead 77]`；8200 无监听、0 个 python 进程。
- `scripts/aiops_test_environment.py start --output runtime\aiops-goal-041 --scenario endpoint --duration-seconds 3600` → `status=ready`、`target_id=aiops-test-8229e95953a2`、`gateway_url=http://127.0.0.1:5237/mcp`、round 1、`environment_acceptance=passed`、`business_url=http://127.0.0.1:5233/api/availability`、首个业务请求 `3150e3f568374cc781f4810cbdfa4c88` 返回 **503**（edge `2026-11-07T23:27:24.706811+00:00`、localapp `...24.704941+00:00`）、`environment_model_calls=0`、`preflight.json` 6808 B（`c7b9eb5b…`）通过、`controller_answer_denied=true`。
- 业务端口 edge 5233 / localapp 5234 / downstream 5235 / 无监听 5236（`business/localapp.connection.json` = `{"downstream_port": 5236, "upstream_timeout_seconds": 0.5}`）；gateway 5237；backend 8200。实测入口 `503`、5236 无监听 → 场景正确。
- 付费后端 `... backend --output runtime\aiops-goal-041 --port 8200 --run-model --profile .env.agent-test --previous-cost runtime\aiops-goal-040\product-model\cost.json` → 8200 监听、`/login` 200 `text/html; charset=utf-8` 780 B。
- **5 元额度重新计量已核验**：`product-model/run-budget.json` 204 B `3b091ead4931…` = `{"version":1,"previous_sha256":"46f626419f66f407dfccf388ca658f0c9c4c23e7db63605bc0e4ebf12a89c328","inherited_requests":1269,"inherited_reserved_cny":50.759848,"run_limit_cny":5}`，累计上限 `55.759848`；轮次 `cost.json`（点击前）1269 行、`reserved_cny=50.759848`、`blocked_requests=9`、`model-inputs/` 不存在。

### 单次点击与结论（041 轮次）

- `playwright-cli -s=aiops041` 登录后进 `/aiops`，`browser-start.js` 只点一次「开始诊断」→ `{"clicked":1,"post_count":1,"post_status":200}`，计划 6 步，`start.png` 77946 B（`b46cd5c9…`）。
- 运行行 `thread_id=web-nz67485c-d143d1e50f5d41d1965197ba6ca65881`、`completed`、`2026-11-07 23:28:43` → `23:29:43`、报告 5135 字符（`report.txt` 7591 B）。
- **`kind=localized_fault`、`root_cause_code=''`、`evidence` 仅 5 条、`contradictions=[]`、`observation_conflicts=[]`、`validation_issues` 6 条**（首条即「根因缺少受支持的原因码或完整同请求证据链；保留为未确认假设。」）；`alternatives` 3 条（`unresolved` + `critical=true`「localapp 应用层自身返回 503…edge 只是转发该状态」、`excluded` `ports/5235: listening == false`、`excluded` `dependency_probe/downstream: tcp == "failed"`）；`stop_reason` 为「首选检查受阻（模型未提出下一项检查）…不代表所有可能检查已穷尽」。
- 报告标题为「故障层已定位，深层原因未明」；`report-headings.json`：`mentions_impact/remediation/retest/unknowns/validation_notes` 全 true，`mentions_root_cause_line=false`；引用 11 条证据 id。

### 5B 验收表（041 轮次）

| 检查项 | 结果 | 证据 |
|---|---|---|
| 前端官方页恰好发起一次诊断 | passed | `{"clicked":1,"post_count":1,"post_status":200}`；`start.png` 77946 B（`b46cd5c9…`） |
| 以合法工具取得并引用证据 | passed | 13 次 probe 工具调用全部 `validated_live_evidence=true`（`product/tool_trace.json`）；`gate-b-acceptance.json` 五类 `ok/cited/hash` 全 true |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-89fbcfe6bc6e4679878a546ba87d62be`（`downstream_port=5236`、`source_sha256 1203cad8…`） |
| 同请求应用失败日志 | passed | `ev-ca630f0d9ea449b2a106829d203fadb3`（`request_id=3150e3f5…`、`connection_established=false`、503） |
| 错误端口无监听/不可达 | passed | `ev-9a7c1fd21e6c414d9ed292016070f5e1`（5236 `matched_count=0`）+ `ev-bff6e852fc734938976a9f4a8141431a`（localapp_upstream TCP failed） |
| 登记下游健康 | passed | `ev-fdd7a7fd0cee4f55b30f1a76871c0e6d`（downstream TCP ok / HTTP 200） |
| edge-localapp 同 `request_id` 失败链 | passed | `ev-ca91bcdd5cc6486eabbcbb59c990ca8a` + `ev-f744137eaafa4c4094145e2240c290f1` + `ev-ca630f0d…` |
| 最终 `completed` + `confirmed_cause` + 原因码 | **failed** | 最终 `kind=localized_fault`、`root_cause_code=''` |
| 六项报告内容 | **failed** | 无「已确认直接原因 / 直接根因」两节（`mentions_root_cause_line=false`）；其余四项存在 |
| 不臆断无来源历史 | passed | 更深原因与变更历史均列为未知，未作断言 |
| 刷新后报告可读 | passed | 刷新后 12608 字符、`evidence_nodes=39`、`aiops_post_after_refresh=0`；`after-refresh.png` 85063 B（`fe7d1cf6…`） |
| 同轮次后端停止/重启后一致 | passed | `acceptance-live.json` 与 `acceptance-after-restart.json` 均 `report_sha256=2fd7b87415ff75f59b33e011bbb06ca9b1128e1e01df9c61f0c7f10bd4256f21`、`evidence_total=13` |
| 读取阶段零模型调用 | passed | 两次读取 `requests 1282 → 1282`、`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-after-restart.json` 2979 B（`bfc571ca…`）与 `logical-digest-final.json` 1438 B（`a05e2a09…`）`all identical: True`，仅 `probe_targets` 心跳转 offline |
| 证据完整性 | passed | `gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []`；`evidence-hashes.json` 34 文件 + 13 证据 + 13 `model-inputs/`，独立复算 0 缺失 0 不符 |
| 预算 ≤ 本轮 5 元 | passed | 13 次新请求（1270–1282）、`round_reserved_cny=0.669814`、累计 `51.429662`、全部 `deepseek-v4.1-flash-1017` 且已定价、无新增未知 usage、`blocked_requests` 仍 9 |
| 继承 040 最新账本 | passed | `chain-equivalence.json` 2465 B（`5862f50b…`）：`chain_equivalent=true`、`inherited_rows=1269`、`rows_added_per_round {034:1191,035:0,036:17,037:17,038:15,039:14,040:15,041:13}`、`rows_1_to_history_byte_identical_all_eight=true`、未知 usage 仍只有 `[710]` |
| 环境恢复与清理 | passed | `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`、`ended_at=2026-11-07T23:46:53.158887Z`；5233–5237 与 8200 均无监听 |

### 未通过的直接原因（代码级取证）

**不是模型没找到原因，也不是缺证据。** checkpoint 16/17 的 `investigation_memory.model_suggestion` 明确写着 `conclusion_level='confirmed_cause'`、`outcome='root_cause'`、`root_cause_code='configured_downstream_endpoint_mismatch'`，`supporting_evidence` 11 条，覆盖全部 5 个必需证据 id（`ev-89fbcfe6…` 配置、`ev-ca630f0d…` localapp 失败日志、`ev-f744137e…` edge 转发、`ev-fdd7a7fd…` downstream 探活、`ev-bff6e852…` localapp_upstream），`root_cause` 原文写明 `downstream_port=5236`（`source_sha256 1203cad8…`）vs 登记 5235、5236 无监听、localapp connect 阶段失败并 503。

1. `runtime/aiops-goal-041/step7_policy_necessity.py`（只读、`model_calls=0`）：把 `dependency_followup_policy` patch 成 `None` 后，用 checkpoint 16 与 17 的提议分别复算，**两次都得到 `confirmed_cause` + `configured_downstream_endpoint_mismatch`、`plan=[]`**，且当时 5 条必需证据已全部在场并被引用（`required_all_present=true`、`required_cited` 5/5）。→ 第 7 步的结论本已完整。
2. 但生产运行时策略引擎在同期排入了额外的一次监听检查：`policy_selected_check={"kind":"failed_loopback_dependency_listener_check","arguments":{"local_port":5236,"listening_only":true},...}`，由 `dependency_followup_policy` → `_unverified_loopback_dependency_check` 在 `src/agent/aiops/strategies/investigation.py:3684-3695` 覆盖 `next_check/next_tools/next_arguments`，使收束条件 `sufficient and not decision.next_check.strip()` 不成立 → 多走一轮。`runtime/aiops-goal-041/step7_exact_replay.py` 用与生产相同的参数（`previous_records=records`、`require_concrete_checks=True`、`evidence_index` 钉到 `2026-11-07T23:29:43+00:00`）复算 checkpoint 16，**精确重现了生产行为**（不产出诊断 + `plan=['核验 loopback 依赖 localapp_upstream 的 5236 端口监听状态及进程归属']`）。
3. 多出来的这一轮之后，**最后一次模型调用自己交回了空壳提议**（`runtime/aiops-goal-041/last-turn.json`）：`root_cause=''`、`root_cause_code=''`、`supporting_evidence` **0 条**、`alternatives` 里把「localapp 应用层自身返回 503」从 `unresolved/critical=false` 改成了 `supported/critical=true`、`next_check=''`。于是 `_valid_citations` 与 alternatives 分支同时失败，`sufficient=false`，走停止路径 → `localized_fault`。
4. 结论：与 039 不同，**本次不是 `contradictions` 子句的问题**（`diagnosis.contradictions=[]`，039 的修复在该字段上仍然有效）。041 失败模式是「**策略检查在结论已完整时抢先排入**」+「**末轮模型退回空壳提议**」两段耦合。`runtime/aiops-goal-041/replay_041_policy.py` 显示：策略开启时 checkpoint 17（5236 快照已采）复算能得 `confirmed_cause`，checkpoint 18（空壳提议）复算得 `localized_fault` —— 与本轮真实结果一致。

### 041 交付物

| 文件 | 字节 | SHA256（前 12 位） |
|---|---|---|
| `result-summary.json` | 1461 | `f94414780571` |
| `decision-audit.json` | 22756 | `72b62715f285` |
| `latest-state.json` | 76707 | `91e48b9e6507` |
| `event-trail-reconstructed.json` | 27340 | `63f006336f4a` |
| `chain-equivalence.json` | 2465 | `5862f50b6358` |
| `gate-b-acceptance.json` | 4585 | `62115a53eaf0` |
| `gate-b-checks.json` | 16233 | `5d7bcfe71948` |
| `step7-policy-necessity.json` | 2867 | `0f2a38471301` |
| `step7-exact-replay.json` | 1916 | `dd46ba784cfe` |
| `last-turn.json` | 5830 | `6da5640e4962` |
| `report.txt` | 7591 | `607ebc54a4ea` |
| `after-refresh.png` | 85063 | `fe7d1cf6ce40` |
| `evidence-hashes.json` | 7887 | `4e640d46a58c`（34 文件 + 13 证据 + 13 `model-inputs/`，独立复算 `bad 0 / missing 0`） |

### 041 剩余限制（如实记录）

- 原始 SSE 帧仍未落盘（`event-trail-reconstructed.json` 的 `raw_sse_frames_persisted=false`）。
- 4 条候选检查提议被拒（重复检查 / 缺工具目录），1 条未决问题 `q-4e8b9c355cbd`（localapp 应用层自身 503）保留为 unresolved。
- `/steps` 未启用、普通用户 `can_read_raw=false`、localapp 事件通道未配置（与 036–040 一致）。
- 本轮 `diagnosis.evidence` 仅 5 条（036/040 为 13、037/038 为 14），引用 11 条。

### 041 对 Goal 判定的影响

- 修复后真实复跑结果为 **1 通过（040）/ 2 尝试（040、041）**，即**修复后尚未达到稳定复现**；含 036–041 六轮合计 **4/6**。
- Goal `goal-d4100615-…` 已于 2026-11-07 标记 `complete`（六个状态位均 `passed`，依据是 036/037/038/040 四轮已通过）。041 不改变历史轮次的通过事实，但**削弱了「稳定复现」这一更强主张**：若要以「修复后稳定复现」作为结论，需先修掉本次暴露的「策略抢先排检查 + 末轮空壳提议」两处问题，再复跑验证。

## 判定逻辑修复之二（2026-11-08，用户授权「修这两处再复跑」）

041 暴露的两处问题与 039 不同源（`contradictions` 为空，039 的修复仍生效），分别修复：

| # | 问题 | 位置 | 改动 |
|---|---|---|---|
| 1 | 模型已给出「证据完整的终态结论」时，`dependency_followup_policy` 仍会抢排一次检查并覆盖 `next_check`，导致 `sufficient and not next_check` 的收束条件永不成立，正确结论被拖入下一轮 | `src/agent/aiops/strategies/investigation.py` `decide_from_evidence` | 新增 `model_terminal_cause` 判定（`outcome=='root_cause'` + `root_cause` 非空 + `required_cause_evidence` 非空且被主引用覆盖 + 无 `next_check/next_tools/next_arguments`）；成立时 `policy_check = None`，不再排策略检查 |
| 2 | 末轮「声明终态但不给原因」的空壳提议（`conclusion_level='confirmed_cause'`/`outcome='root_cause'` 但 `root_cause`、`root_cause_code`、`supporting_evidence` 全空）被当作普通降级接受，并把一条 `unresolved/noncritical` 替代解释留成终局 | 同上 + 模块级 `empty_terminal_claim(decision)` / `_EMPTY_TERMINAL_CLAIM` | 显式识别空壳终态主张：追加 `validation_issues`、清空原因与原因码、置 `investigating/unlocated`、写入 `blocked_reason`；主张本身不构成结论，也不许据此把替代解释当已排除 |

保留不变：`diagnosis['contradictions']` 仍原样输出模型待核实说明；系统派生的现场事实冲突（`superseded_citations` / 证据失效）仍照旧否决结论；`investigation_memory` 仍保留本轮 `model_suggestion` 原文；报告层仍分 `contradictions`（模型说明）与 `conflicts`（现场冲突）两个键。

### 回放验证（039/041 真实提议，`model_calls=0`）

- `runtime/aiops-goal-041/replay_041_fixed.py` → `replay-041-fixed.json`：用修补后的引擎重放 041 的 checkpoint 15/16/17/18。
  - checkpoint 16（模型已给出 `confirmed_cause` + `configured_downstream_endpoint_mismatch`）：**旧代码**记录的策略检查 `failed_loopback_dependency_listener_check` 不再排入 → `replayed_plan=[]`、`replayed_policy=null`、`replayed_diagnosis_kind='confirmed_cause'`。
  - checkpoint 17（同一提议、5236 快照已采集）：同样 `confirmed_cause`、无策略检查。
  - checkpoint 18（空壳终态提议）：仍为 `localized_fault`，但 `blocked_reason` 换成本轮的空白主张说明，**不再把空壳当作「已确认」**。
- `runtime/aiops-goal-041/step7-policy-necessity.json`：在策略被禁用的条件下复算 checkpoint 16/17，两次都 `required_cause_evidence` 5/5 齐备且被引用 → 该策略检查在证据链上并非必需，纯属抢跑。

### 单测（新增 3 条，`tests/test_investigation_fusion.py`）

| 用例 | 断言 |
|---|---|
| `test_complete_cause_is_not_reopened_by_a_policy_followup_check` | 证据完整的终态结论 → `plan==[]`、`confirmed_cause`、`policy_selected_check is None`（先断言 `dependency_followup_policy` 确实会排队，确保测的是抢占场景） |
| `test_incomplete_cause_still_lets_the_policy_queue_its_check` | 少引用一条必需证据时 → 不产出诊断、`plan` 非空、策略检查仍被排入（防止放宽过度） |
| `test_terminal_claim_without_a_cause_is_rejected_instead_of_downgraded` | 空壳终态主张 → 无 `diagnosis`、`unlocated/investigating`、原因与原因码清空、含 `_EMPTY_TERMINAL_CLAIM`、替代解释保持 `unresolved`（原 decision 未被就地改写） |

### 回归结果

- `pytest tests/test_investigation_strategy.py tests/test_investigation_boundaries.py tests/test_investigation_fusion.py tests/test_decision_replay.py -q` → **292 passed, 1 warning**（改造前 289，+3 为实现新用例）。
- `pytest tests/test_decision_replay.py tests/test_investigation_strategy.py -q` → **165 passed, 1 warning**（免费门既有门槛不变）。
- 全量 `pytest tests -q` → **2063 passed, 37 failed**；用 `git stash` 回到干净 HEAD `7111780` 复跑得 **2060 passed, 37 failed**，`Compare-Object` 显示两组的失败集合**完全相同**（37 个均为既存失败：`test_matching503_output_flow.py` 24、`test_four_issue_closeout.py` 6、`test_agent_knowledge_consumption.py` 5、`test_live_probe_mechanisms.py` 1、`test_probe_summary_output_flow.py` 1），本次改动未新增失败。

### 仍未做的事

- 没有跑新的付费轮次：要声称「修复后稳定复现」，仍需用户另行授权一轮（042）真实复跑验证。

## 042 轮次复跑记录（2026-11-08）——修复后第二次复现，本轮通过

用户授权（m04548「继续」）后按门禁规则执行，用途是验证「判定逻辑修复之二」（策略抢排检查 + 空壳终态提议）之后，同一 `endpoint` 场景能否重新稳定得到 `confirmed_cause`。

### 环境与预算

| 项 | 值 |
|---|---|
| 基线 | `HEAD=2f8c24d`、`## main...origin/main [ahead 79]`、`8200` 空闲、无 python 进程、目录 `runtime/aiops-goal-042` 起跑前不存在 |
| 环境 | `aiops_test_environment.py start --scenario endpoint --duration-seconds 3600`，`target_id=aiops-test-b4715e70f959`，`gateway=http://127.0.0.1:4203/mcp`，`status=ready`，`environment_acceptance=passed`，首个业务请求 `482ea8413499429abf2cdfb5e14a43be` → **503**，`environment_model_calls=0` |
| 端口 | edge 4200 / localapp 4201 / downstream 4199 / 无监听上游 **4202**；`business/localapp.connection.json` = `{"downstream_port": 4202, "upstream_timeout_seconds": 0.5}` |
| 继承账本 | `runtime/aiops-goal-041/product-model/cost.json`（2324101 B、`d34e6621df22…`、1282 行、`reserved_cny=51.429662`） |
| 轮次 manifest | `product-model/run-budget.json` 204 B `a37f7cce85d3…` = `inherited_requests=1282`、`inherited_reserved_cny=51.429662`、`run_limit_cny=5`、`previous_sha256=d34e6621…` |
| 轮次账本 | 点击前 1282 行、`reserved_cny=51.429662`、`limit_cny=56.429662`；结束时 1296 行、`reserved_cny=52.077212` |
| 本轮新增预留 | `0.64755` 元（≤ 5 元上限；14 次请求 1283–1296，全部 `deepseek-v4.1-flash-1017` 已定价、有 usage、`blocked_requests` 仍为 9） |

### 单次点击与结论

- 前端官方页 `playwright-cli -s=aiops042`：`browser-start.js` 结果 `{"clicked":1,"post_count":1,"post_status":200}` —— **恰好一次 POST `/api/v1/aiops`**，`start.png` 79986 B `619e845fbefb`，页面显示 6 步计划。
- 运行行：`thread_id=web-esgx4cl3-e4987b47e05e4eed9e45f88c718308eb`，`status=completed`，`2026-11-08 00:47:59` → `00:49:05`，报告 5641 字符；`aiops_evidence` 12 行、`probe_snapshots` 3、checkpoints 17 / writes 99。
- 结论：**`kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`**，`target=aiops-test-b4715e70f959`，`version=1`，`diagnosis.evidence` 13 条，`alternatives` 5（unresolved edge 转发说 / supported `ports/4202: listening == false` / excluded `dependency_probe/downstream: tcp == "failed"` / excluded `ports/4200: listening == false` / unresolved 4202 历史生命周期），`contradictions=[]`、`observation_conflicts=[]`、`validation_issues` 4 条（均为「该检查步骤此前已执行」「已有该对象和参数」）、`unresolved` 2 条、`stop_reason` 空、`leading_id=h-92197c91e0d8dcbb`、investigation 7 candidates / 5 check_progress / 1 event。
- 12 次工具调用全部 `validated_live_evidence=true`：`probe_inventory`、`probe_port_snapshot {listening_only:true,limit:256}`、`probe_process_snapshot edge/localapp/downstream`、`probe_port_snapshot {local_port:4200}`，以及后续日志/配置/依赖探测。

### 5B 验收表（042 轮次）

| 通过条件 | 结果 | 证据 |
|---|---|---|
| 新目录 + 继承上一轮最新账本（hash/条数/历史未知项） | passed | `chain-equivalence.json`（`chain_equivalent=true`、`inherited_rows=1282`、`rows_1_to_history_byte_identical_all_nine=true`、`unknown_usage_rows` 全 `[710]`） |
| 本轮新预留 ≤ 5 元 | passed | `result-summary.json`：`round_reserved_cny=0.64755`、`within_run_cap=true`、无未定价/未知新行 |
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js` → `clicked=1`、`post_count=1`、`post_status=200` |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json`（checkpoint 17 + 工具 12 + 模型请求 14）、`product/tool_trace.json`、`model-inputs/` 14 份脱敏输入、`report.txt`；原始 SSE 帧未落盘（`raw_sse_frames_persisted=false`） |
| 以合法工具取得并引用证据 | passed | 12 次 Probe/MCP 调用 `validated_live_evidence=true`；报告引用 10 个 ev id |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-463715442ac140ba91236c103ff7d506`（`downstream_port=4202`、`source_sha256=230c4292…`） |
| 同请求应用失败日志 | passed | `ev-69d5c380b9ef4f2da2e3890a339f9194`（`request_id=482ea841…`、`connection_established=false`、503） |
| 错误端口无监听/不可达 | passed | `ev-a89ff823430e48c88fdbc790772bac5d` + `ev-e4f307cc4c3c475ab48b205fe397e581` |
| 登记下游健康 | passed | `ev-7af5dcd59ad947c68b62d1ae12b836af`（TCP ok / HTTP 200） |
| edge 与 localapp 同 `request_id` 失败链 | passed | `ev-08b69788f05d41a1a5649a43b794dfe5` + `ev-69d5c380…` |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `result-summary.json`、`run-detail.json` |
| 报告六项内容齐全 | passed | `report-headings.json` + `report.txt`（结论/根因证据/影响范围/处理建议/复测方法/剩余未知） |
| 不臆断无来源历史 | passed | 报告把变更者、变更动机、4202 历史生命周期列为未知 |
| 刷新后报告可读 | passed | 刷新后报告 12343 字符、`原因已确认`、`evidence_nodes=37`、`aiops_post_after_refresh=0` |
| 同轮次后端停止/重启后一致 | passed | `acceptance-after-restart.json` 与 live 同 `report_sha256=2c3cab27701a…`、`evidence_total=12`、`requests 1296 → 1296` |
| 读取阶段零模型调用 | passed | live 与重启后两次读取均 `1296 → 1296`，`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-final.json`（`all identical: True`）、`wal-attribution.json`、`heartbeat-drift.json`（仅 `probe_targets` 心跳变化） |
| 证据完整性 | passed | `gate-b-acceptance.json` 全 `ok/cited/hash=true`；`gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []` |
| 预算 ≤ 5 元 | passed | `round_reserved_cny=0.64755`、`limit_cny=56.429662`、`within_run_cap=true` |
| 环境恢复与清理 | passed | `environment.json`：`stopped`、`three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`；4195–4210 与 8200 无监听 |

### 交付物（042 轮次，含重建件）

| 文件 | 字节 | SHA256（前 12 位） | 内容 |
|---|---|---|---|
| `result-summary.json` | 1510 | `5567f7ebb8db` | 轮次摘要（含预算、环境、artifact hashes） |
| `decision-audit.json` | 20739 | `b61282cdb765` | 只读重建的决策审计 |
| `latest-state.json` | 85403 | `f41451fa250c` | 最终 diagnosis + investigation 状态 |
| `event-trail-reconstructed.json` | 25440 | `736022e676af` | checkpoint/工具/模型请求时序轨迹 |
| `chain-equivalence.json` | 2870 | `11f57800ec73` | 九段账本继承等价性 |
| `gate-b-acceptance.json` | 4475 | `ec47c64e6b9e` | 五类必需证据映射 |
| `gate-b-checks.json` | 15445 | `6d99e216f385` | 产物哈希对比与预算块 |
| `evidence-hashes.json` | 7858 | `02f81b53c4c8` | 34 文件 + 12 证据 + 14 model-inputs |
| `report.txt` | 8882 | `479116766106` | 报告原文 |
| `ckpt-decoded.json` | 8595 | `e6f1ffd8d07d` | checkpoint 解码 |
| `product-model/cost.json` | 2350641 | `c750331a23bb` | 轮次账本（1296 行） |
| `product-model/run-budget.json` | 204 | `a37f7cce85d3` | 本轮 5 元额度基线 |

### 剩余限制

- 原始 SSE 帧未落盘（中间件只允许一次 POST，第二路流不可能）；以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代。
- 4 条候选检查提议因「该检查步骤此前已执行」「已有该对象和参数」被系统拒绝执行。
- `/steps` 接口未启用（`total: 0`）；普通用户 `can_read_raw=false`。
- `localapp` 事件通道未配置，无法取到服务事件日志。

### 对 Goal 判定的影响

042 是「判定逻辑修复之二」之后的**第一次**真实复跑，也是同一 `endpoint` 场景在 039、041 两次失败之后重新得到 `confirmed_cause`。至此含全部七轮（036–042）为 **6/7** 通过；修复后两轮（040、042）为 **2/2** 通过，但期间 041 未通过（其失败模式已修复并用真实 checkpoint 回放验证），因此「稳定复现」仍建议继续累积样本，不做无条件的稳定性断言。

## 043 轮次复跑记录（2026-11-08）——修复后第三次复现，本轮通过

用户授权（m04735「1」= 再跑一轮 043 继续累积修复后的成功样本）后按门禁规则执行。

### 环境与预算

| 项 | 值 |
|---|---|
| 基线 | `HEAD=649c08e`、`## main...origin/main [ahead 80]`、`8200` 空闲、0 个 python 进程、目录 `runtime/aiops-goal-043` 起跑前不存在 |
| 环境 | `aiops_test_environment.py start --scenario endpoint --duration-seconds 3600`，`target_id=aiops-test-9d4916f102ac`，`gateway=http://127.0.0.1:4063/mcp`，`status=ready`，`environment_acceptance=passed`，首个业务请求 `95595bf287fd469eac6c585d5f3fe183` → **503**，`environment_model_calls=0`，`started_at=2026-11-08T00:59:10.025097Z` |
| 端口 | edge 4059 / localapp 4060 / downstream 4061 / 无监听上游 **4062**；`business/localapp.connection.json` = `{"downstream_port": 4062, "upstream_timeout_seconds": 0.5}` |
| 继承账本 | `runtime/aiops-goal-042/product-model/cost.json`（2350641 B、`c750331a23bb…`、1296 行、`reserved_cny=52.077212`） |
| 轮次 manifest | `product-model/run-budget.json` 204 B `5505a69536fb…` = `inherited_requests=1296`、`inherited_reserved_cny=52.077212`、`run_limit_cny=5`、`previous_sha256=c750331a…` |
| 轮次账本 | 点击前 1296 行、`reserved_cny=52.077212`、`limit_cny=57.077212`；结束时 1305 行、`reserved_cny=52.436218` |
| 本轮新增预留 | **0.359006** 元（≤5 元上限；9 次请求 1297–1305，全部 `deepseek-v4.1-flash-1017` 已定价、有 usage、`blocked_requests` 仍为 9） |

### 单次点击与结论

- 前端官方页 `playwright-cli -s=aiops043`：`browser-start.js` 结果页面停在 `/aiops` 并截图 `start.png`（84344 B `e81aa8e744b6`），**恰好一次 POST `/api/v1/aiops`**；运行行 `web-fr0omedf-6927d034daba4ec6829696d33481acfb`。
- 运行行：`status=completed`，`2026-11-08 01:01:02` → `01:01:52`，报告 6181 字符；`aiops_evidence` 9 行、`probe_snapshots` 5、checkpoints 11 / writes 66。
- 结论：**`kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`**，`target=aiops-test-9d4916f102ac`，`version=1`，`diagnosis.evidence` 11 条，`alternatives` 4 条全部 `supported` + `verification=predicate_verified` + `critical=False`（各带 `noncritical_reason`），`contradictions=[]`、`observation_conflicts=[]`、`unresolved=[]`、`stop_reason` 空、`validation_issues` 2 条（假设文字未验证 / 一条候选检查不可调度）、`leading_id=h-9a2edaff6dd9d779`、investigation 7 candidates / 2 check_progress / 3 events。
- **这是 043 的一个真实差别**：模型在 9 次请求内就收束（042 为 14 次），且没有留下 unresolved 项；策略引擎未再抢排检查（修复二生效）。
- 9 次工具调用全部取得有效证据：`probe_inventory`、`probe_port_snapshot {listening_only:true,limit:256}`、`probe_dependency_probe {dependency: edge|localapp|downstream}`，以及日志/配置探测。

### 5B 验收表（043 轮次）

| 通过条件 | 结果 | 证据 |
|---|---|---|
| 新目录 + 继承上一轮最新账本（hash/条数/历史未知项） | passed | `chain-equivalence.json`（`chain_equivalent=true`、`inherited_rows=1296`、`rows_1_to_history_byte_identical_all_ten=true`、`unknown_usage_rows` 全 `[710]`） |
| 本轮新预留 ≤5 元 | passed | `result-summary.json`：`round_reserved_cny=0.359006`、`within_run_cap=true`、无未定价/未知新行 |
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js`（登录→`/aiops`→填表单→点击一次）、`start.png` |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json`（checkpoint 11 + 工具 9 + 模型请求 9）、`product/tool_trace.json`、`model-inputs/` 9 份脱敏输入、`report.txt`；原始 SSE 帧未落盘（`raw_sse_frames_persisted=false`） |
| 以合法工具取得并引用证据 | passed | 9 次 Probe/MCP 调用；报告引用 7 个 ev id（共 11 条证据） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-cb62cd5e5b4b488a91f7645017a06311`（`downstream_port=4062`、`upstream_timeout_seconds=0.5`） |
| 同请求应用失败日志 | passed | `ev-e357489a21c24aac9e43fc5108572958`（`request_id=14431d8f…`、`phase=connect`、`connection_established=false`、503） |
| 错误端口无监听/不可达 | passed | `ev-ed8c42ac06ff4c1e9ae156a7c16c691e`（`localapp_upstream` TCP failed / ConnectionRefusedError，4062） |
| 登记下游健康 | passed | `ev-2f28198aeb734a2e901562aea6af9a35`（4061 TCP ok / HTTP 200） |
| edge 与 localapp 同 `request_id` 失败链 | passed | `ev-f9a9e275cb99414ba2c39b6cb217e507`（edge，`connection_established=true`、`response_status=503`）+ `ev-e357489a…` |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `result-summary.json`、`run-detail.json` |
| 报告六项内容齐全 | passed | `report-headings.json`（`mentions_*` 全 true）+ `report.txt` |
| 不臆断无来源历史 | passed | 报告把变更者、变更时间、动机、4062 历史生命周期列为未知 |
| 刷新后报告可读 | passed | 刷新后报告 13394 字符、`原因已确认`、`evidence_nodes=32`、`aiops_post_after_refresh=0` |
| 同轮次后端停止/重启后一致 | passed | `acceptance-after-restart.json` 与 live 同 `report_sha256=8edcb711be36…`、`evidence_total=9`、`requests 1305 → 1305` |
| 读取阶段零模型调用 | passed | live 与重启后两次读取均 `1305 → 1305`，`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-final.json`（`all identical: True`）、`wal-attribution.json`、`heartbeat-drift.json`（仅 `probe_snapshots`/`probe_targets` 心跳变化） |
| 证据完整性 | passed | `gate-b-acceptance.json` 五类全 `ok/cited/hash=true`；`gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []`、稳定产物 8 项字节一致 |
| 预算 ≤5 元 | passed | `round_reserved_cny=0.359006`、`limit_cny=57.077212`、`within_run_cap=true` |
| 环境恢复与清理 | passed | `environment.json`：`stopped`、`three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`；4055–4070 与 8200 无监听，0 个 python 进程 |

### 交付物（043 轮次，含重建件）

| 文件 | 字节 | SHA256（前 12 位） | 内容 |
|---|---|---|---|
| `result-summary.json` | 1455 | `da67d453e193` | 轮次摘要（含预算、环境、artifact hashes） |
| `decision-audit.json` | 16231 | `cbf126be56db` | 只读重建的决策审计 |
| `latest-state.json` | 80847 | `5bd059717983` | 最终 diagnosis + investigation 状态 |
| `event-trail-reconstructed.json` | 17457 | `9f49464612b1` | checkpoint/工具/模型请求时序轨迹 |
| `chain-equivalence.json` | 3082 | `b5780ed09d8d` | 十段账本继承等价性 |
| `gate-b-acceptance.json` | 4067 | `414d97c203e9` | 五类必需证据映射 |
| `gate-b-checks.json` | 12945 | `c35c3b3976f3` | 产物哈希对比与预算块 |
| `evidence-hashes.json` | 7058 | `352bd21b7c45` | 34 文件 + 9 证据 + 9 model-inputs（独立复算 0 不符 / 0 缺失） |
| `report.txt` | 9432 | `fdd012e9f62e` | 报告原文（6181 字符） |
| `ckpt-decoded.json` | 6893 | `0c33147f7794` | checkpoint 解码（诊断写 `1f1db0ff-…`） |
| `product-model/cost.json` | 2367703 | `4b39ea4c2c23` | 轮次账本（1305 行） |
| `product-model/run-budget.json` | 204 | `5505a69536fb` | 本轮 5 元额度基线 |

### 剩余限制

- 原始 SSE 帧未落盘（中间件只允许一次 POST）；以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代。
- 2 条校验提示：当前假设文字含义未验证；一条候选检查因「已有该对象和参数的检查结果」不可调度。
- `/steps` 接口未启用（`total: 0`）；普通用户 `can_read_raw=false`。
- `localapp` 事件通道未配置；报告已把 4062 的历史生命周期列为未知。
- 报告仅引用 11 条证据中的 7 条（未引用：端口全量列表、主机清单类证据）。

### 对 Goal 判定的影响

043 是「判定逻辑修复之二」之后的**第二次**真实复跑，连续两次（042、043）在同一 `endpoint` 场景得到 `confirmed_cause` + `configured_downstream_endpoint_mismatch`，即**修复二之后 2/2 通过**；把修复一之后的四轮（040、041、042、043）合并看为 **3/4**；含全部八轮（036–043，各轮结论为 P/P/P/F/P/F/P/P）为 **6/8** 通过。043 还额外显示修复二的效果：模型 9 次请求即收束、没有 unresolved 项、策略引擎未再抢排检查，`validation_issues` 仅剩 2 条。

## 044 轮次复跑记录（2026-11-08）——连续五轮之第 1 轮，本轮未通过

用户授权（m04885「1，连续跑五轮」）后按门禁规则执行；这是连续五轮（044–048）的第一轮。

### 环境与预算

| 项 | 值 |
|---|---|
| 基线 | `HEAD=f4a4abf`、`## main...origin/main [ahead 81]`、`8200` 空闲、0 个 python 进程、目录 `runtime/aiops-goal-044` 起跑前不存在 |
| 环境 | `start --scenario endpoint --duration-seconds 3600`，`target_id=aiops-test-c581f6781651`，`gateway=http://127.0.0.1:1873/mcp`，`status=ready`，`environment_acceptance=passed`，首个业务请求 `ae9021f76c564dc1a10144489bcafaee` → **503**，`environment_model_calls=0`，`started_at=2026-11-08T01:48:44.003064Z` |
| 端口 | edge 1869 / localapp 1870 / downstream 1871 / 无监听上游 **1872**；`business/localapp.connection.json` = `{"downstream_port": 1872, "upstream_timeout_seconds": 0.5}` |
| 继承账本 | `runtime/aiops-goal-043/product-model/cost.json`（2367703 B、`4b39ea4c2c23…`、1305 行、`reserved_cny=52.436218`） |
| 轮次 manifest | `product-model/run-budget.json` 204 B `85ab37fa85d6…` = `inherited_requests=1305`、`inherited_reserved_cny=52.436218`、`run_limit_cny=5`、`previous_sha256=4b39ea4c…` |
| 轮次账本 | 点击前 1305 行、`reserved_cny=52.436218`、`limit_cny=57.436218`；结束时 1317 行、`reserved_cny=53.027216` |
| 本轮新增预留 | **0.590998** 元（≤5 元上限；12 次请求 1306–1317，全部 `deepseek-v4.1-flash-1017` 已定价、有 usage、`blocked_requests` 仍为 9） |

### 单次点击与结论

- 前端官方页 `playwright-cli -s=aiops044`：`browser-start.js` 结果页面停在 `/aiops` 并截图 `start.png`（81338 B `5a1e7dcd82c1`），**恰好一次 POST `/api/v1/aiops`**；运行行 `web-5lm2quco-21e302389f784ac5abac701738ad107e`。
- 运行行：`status=completed`，`2026-11-08 01:51:09` → `01:52:07`，报告 6146 字符；`aiops_evidence` 10 行、`probe_snapshots` 8–9、checkpoints 13 / writes 77。
- 结论：**`kind=unlocated`、`root_cause_code=''`**（既非 `confirmed_cause` 也非 `localized_fault`），`target=aiops-test-c581f6781651`，`diagnosis.evidence` 10 条，`alternatives` 3 条（两条 `excluded`，一条 `excluded` 且 `critical=false`），`contradictions=[]`、`observation_conflicts=[]`、`unresolved=[]`，`stop_reason`/`blocked_reason` 同为「候选 ID 对应的对象、操作、字段或预期值与此前预期不一致；已停止并保留证据。…候选身份纠正一次后仍未通过；不再重复请求。」，`leading_id=h-ece52db1636d168e`，investigation 4 candidates / 0 check_progress / 0 events。
- 10 次工具调用全部取得有效证据：`probe_inventory`、`probe_process_snapshot` ×3（edge/localapp/downstream）、`probe_port_snapshot {listening_only:true,limit:256}`、`probe_text_log`（edge / localapp / downstream）、`probe_config_snapshot`（localapp）、`probe_port_snapshot {local_port:1871}`。

### 未通过的直接原因（代码级取证）

1. 逐 checkpoint 时间线（`runtime/aiops-goal-044/trace_decision.py`）：13 个 checkpoint，ckpt 04–11 全为 `unlocated/investigating` 且 `next_check` 逐条推进；**ckpt 12 的 `model_suggestion` 已是 `conclusion_level=confirmed_cause`、`outcome=root_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`、`supporting_evidence` 10 条、`validation_issues=0`，但同一 checkpoint 写出的 `diagnosis` 是 `kind=unlocated`**。
2. `runtime/aiops-goal-044/why_identity.py` 复现熔断点：已保存 4 个候选（`h-19a894ac5bee32c1` 无条件、`h-ece52db1636d168e`=`text_logs/localapp#…` 的 `upstream_request.connection_established == false`、`h-cc02bf0debff3aa7`=`ports/1871: listening == false`、`h-7676d16ebd50773f`=`text_logs/edge#…` 同字段）。末轮模型最后一条 alternative 写的是 `explanation='downstream 进程已停止或未监听 1871，导致 localapp 连接被拒'`、`hypothesis_id='h-7676d16ebd50773f'`（edge 日志那条的 id），却配了 `condition={operation:ports, object_name:'1871', field:listening, expected:false}`（ports 那条的条件）→ `_resolve_candidate_identity`（`src/agent/aiops/strategies/investigation.py:1916-1919`）判定「候选 ID 对应的对象、操作、字段或预期值与此前预期不一致」。
3. 该 issue 触发 `src/agent/aiops/strategies/investigation.py:1986-1989`：清空 `hypothesis_id`、`next_check`、`next_tools`、`next_question_id`、`root_cause`，把 `outcome` 置 `investigating`，并写入 `blocked_reason`。即**模型的因果推理正确（根因文本、原因码、10 条支撑证据齐全），失败点是它自己把两个已在簿记中的候选 ID 与条件配错了**，身份校验按设计熔断。
4. 回放（`runtime/aiops-goal-044/replay_044.py`，`model_calls=0`，钉住 `2026-11-08T01:52:07+00:00`）：按原文回放 → `unlocated`、`evidence 10`、`plan 0`、1 条 identity issue；仅把那条 `ports` 条件的 `hypothesis_id` 清空、其余不动 → `identity_issues=[]`、`blocked_reason=''`、**`plan 1`**（引擎会继续调查而非立即收束）。说明熔断解除后并不会自动把结论升为 `confirmed_cause`，本轮不是一个"清掉一行就通过"的简单缺陷。
- 五类必需证据中 **`wrong_port_unreachable_or_not_listening` 与 `registered_downstream_health` 两类未满足**：模型只探了 1871 端口与 downstream 日志，没有对 1872 做端口探测、也没有对 downstream 依赖做探活，`gate-b-acceptance.json` 的 `all_requirements_satisfied=false`。

### 5B 验收表（044 轮次）

| 通过条件 | 结果 | 证据 |
|---|---|---|
| 新目录 + 继承上一轮最新账本（hash/条数/历史未知项） | passed | `chain-equivalence.json`（`chain_equivalent=true`、`inherited_rows=1305`、`rows_1_to_history_byte_identical_all_eleven=true`、`unknown_usage_rows` 全 `[710]`） |
| 本轮新预留 ≤5 元 | passed | `result-summary.json`：`round_reserved_cny=0.590998`、`within_run_cap=true`、无未定价/未知新行 |
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js`（登录→`/aiops`→填表单→点击一次）、`start.png` |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json`（checkpoint 13 + 工具 10 + 模型请求 12）、`product/tool_trace.json`、`model-inputs/` 12 份脱敏输入、`report.txt`；原始 SSE 帧未落盘 |
| 以合法工具取得并引用证据 | passed | 10 次 Probe/MCP 调用全部 `validated_live_evidence=true`；报告引用 5 个 ev id（共 10 条证据） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-ca8bea5f94c8427db13f47f2087a9987`（`downstream_port=1872`） |
| 同请求应用失败日志 | passed | `ev-984881187ae34b9eafc512bb98197e37` |
| 错误端口无监听/不可达 | **failed** | 模型未对 1872 采集端口或依赖探测证据（只探了 1871：`ev-56b93b6b77d940febfc7061d04f81479`） |
| 登记下游健康 | **failed** | 没有 downstream 依赖探活证据，只有 downstream 日志 `ev-f83025a27c2e446aaa849df6688d57ac` |
| edge 与 localapp 同 `request_id` 失败链 | passed | `ev-202623e9d2604b8f90a81e60f5f96f37`（edge）+ `ev-98488118…` + `ev-f83025a2…` |
| 最终 `completed` + `confirmed_cause` + 原因码 | **failed** | `unlocated`、原因码为空（`result-summary.json`、`run-detail.json`） |
| 报告六项内容齐全 | **failed** | 报告为未定位形态，无「直接根因」结论段 |
| 不臆断无来源历史 | passed | 报告把根因明确标为「模型推断（未验证，不作为现场事实）」，并把 1872 的历史生命周期列为未知 |
| 刷新后报告可读 | passed | 刷新后报告 10030 字符、标题 `尚未定位`、`evidence_nodes=30`、`aiops_post_after_refresh=0` |
| 同轮次后端停止/重启后一致 | passed | `acceptance-after-restart.json` 与 live 同 `report_sha256=90f58a7128c7…`、`evidence_total=10`、`requests 1317 → 1317` |
| 读取阶段零模型调用 | passed | live 与重启后两次读取均 `1317 → 1317`，`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-final.json`（`all identical: True`）、`wal-attribution.json`、`heartbeat-drift.json`（仅 `probe_snapshots` 8→9 与 `probe_targets` 心跳变化） |
| 证据完整性 | passed | `gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []`、稳定产物 7 项字节一致（churn 2 项为 WAL 与 checkpoint） |
| 预算 ≤5 元 | passed | `round_reserved_cny=0.590998`、`limit_cny=57.436218`、`within_run_cap=true` |
| 环境恢复与清理 | passed | `environment.json`：`stopped`、`three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`ended_at=2026-11-08T01:58:41.073300Z` |

### 交付物（044 轮次，含重建件）

| 文件 | 字节 | SHA256（前 12 位） | 内容 |
|---|---|---|---|
| `result-summary.json` | 1444 | `a2547824e802` | 轮次摘要（含预算、环境、artifact hashes） |
| `decision-audit.json` | 18257 | `b287358b19f0` | 只读重建的决策审计 |
| `latest-state.json` | 41296 | `ea6fd70573f8` | 最终 diagnosis + investigation 状态 |
| `event-trail-reconstructed.json` | 20761 | `fc4062be8547` | checkpoint/工具/模型请求时序轨迹 |
| `chain-equivalence.json` | 3298 | `004ad0d2f0a2` | 十一段账本继承等价性 |
| `gate-b-acceptance.json` | 3168 | `f9aaa33bc2b0` | 五类必需证据映射（两类未满足） |
| `gate-b-checks.json` | 13879 | `83242d525d73` | 产物哈希对比与预算块 |
| `evidence-hashes.json` | 7441 | `c8b814f3d590` | 34 文件 + 10 证据 + 12 model-inputs（独立复算 0 不符 / 0 缺失） |
| `report.txt` | 8478 | `b10f108c3116` | 报告原文（6146 字符） |
| `ckpt-decoded.json` | 7662 | `21a4bdaf16d6` | checkpoint 解码（诊断写 `1f1db16f-…`） |
| `trace_decision.py` / `why_identity.py` / `replay_044.py` | — | — | 逐 checkpoint 取证与身份熔断复现（只读，`model_calls=0`） |
| `product-model/cost.json` | 2390456 | `416d6591cad9` | 轮次账本（1317 行） |
| `product-model/run-budget.json` | 204 | `85ab37fa85d6` | 本轮 5 元额度基线 |

### 剩余限制

- 原始 SSE 帧未落盘；以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代。
- `/steps` 接口未启用；普通用户 `can_read_raw=false`。
- 报告仅引用 10 条证据中的 5 条。
- 本轮暴露的候选身份熔断属**模型侧簿记错误触发系统保护**，尚未修改代码：若把 id/condition 错配静默容忍，会削弱「预测必须可复现」的保护；是否要改为「回退到该候选的原文条件并提示重填」需单独评估。

### 对 Goal 判定的影响

044 是连续五轮的第一轮，结论为 `unlocated` → 本轮**未通过** `root_cause` 门。纳入统计后：含全部九轮（036–044，各轮 P/P/P/F/P/F/P/P/F）为 **6/9**；修复二之后（042、043、044）为 **2/3**。044 的失败原因与 039、041 不同：前两次是系统侧（`contradictions` 否决、策略抢排 + 空壳提议），本轮是模型侧把两个已有候选的 id 与条件配错触发系统的身份熔断，属于**保护机制按设计生效**而非系统缺陷。

## 045 轮次复跑记录（2026-11-08）——连续五轮之第 2 轮，本轮通过

用户授权（m04885「1，连续跑五轮」）后按门禁规则执行；这是连续五轮（044–048）的第二轮。

### 环境与预算

| 项 | 值 |
|---|---|
| 基线 | `HEAD=b451271`（044 记录已提交）、`8200` 空闲、0 个 python 进程、目录 `runtime/aiops-goal-045` 起跑前不存在 |
| 环境 | `start --scenario endpoint --duration-seconds 3600`，`target_id=aiops-test-c5cbd14f46d3`，`gateway=http://127.0.0.1:14811/mcp`，`status=ready`，`environment_acceptance=passed`，首个业务请求 `0c9c468ea2644345b5be6888cc04162b` → **503**，`environment_model_calls=0`，`started_at=2026-11-08T02:02:37.066035Z` |
| 端口 | edge 14808 / localapp 14809 / downstream 14807 / 无监听上游 **14810**；`business/localapp.connection.json` = `{"downstream_port": 14810, "upstream_timeout_seconds": 0.5}` |
| 继承账本 | `runtime/aiops-goal-044/product-model/cost.json`（2390456 B、`416d6591cad9…`、1317 行、`reserved_cny=53.027216`） |
| 轮次 manifest | `product-model/run-budget.json` 204 B `1c924a16a6e4…` = `inherited_requests=1317`、`inherited_reserved_cny=53.027216`、`run_limit_cny=5`、`previous_sha256=416d6591…` |
| 轮次账本 | 点击前 1317 行、`reserved_cny=53.027216`、`limit_cny=58.027216`；结束时 1326 行、`reserved_cny=53.451384` |
| 本轮新增预留 | **0.424168** 元（≤5 元上限；9 次请求 1318–1326，全部 `deepseek-v4.1-flash-1017` 已定价、有 usage、`blocked_requests` 仍为 9） |

### 单次点击与结论

- 前端官方页 `playwright-cli -s=aiops045`：`browser-start.js` 执行后页面停在 `/aiops`（首次 `run-code` 因浏览器初启未就绪触发一次 `locator.fill` 超时，重试后正常；**该轮仍只产生一次 `POST /api/v1/aiops`**，以 `aiops_runs` 只有 1 行、账本只新增 9 条请求为准）；运行行 `web-xayl1hft-b15d07654091443d9a3b38508429a51e`。
- 运行行：`status=completed`，`2026-11-08 02:04:14` → `02:05:07`，报告 **6925** 字符；`aiops_evidence` 13 行、`probe_snapshots` 3→5、checkpoints 13 / writes 77。
- 结论：**`kind=confirmed_cause`、`root_cause_code=configured_downstream_endpoint_mismatch`**，`target=aiops-test-c5cbd14f46d3`，`diagnosis.evidence` **16** 条，`alternatives` 5 条（4 条 `excluded`、1 条 `unresolved`），`contradictions` 1 条（TimeoutError vs ConnectionRefusedError 在不同超时/端点下的解释，**属于待核实说明，不再否决结论**），`observation_conflicts=[]`、`unresolved` 1 条（localapp 事件通道未配置无法核验退出历史）、`validation_issues` 4 条（均为候选检查不可调度类）、`stop_reason` 空、`leading_id=h-563bc2f551d5c9f1`、investigation 8 candidates / 3 check_progress / 0 events。
- 13 次工具调用全部 `validated_live_evidence=true`：`probe_inventory`、`probe_process_snapshot` ×3、`probe_port_snapshot {listening_only:true,limit:256}`、`probe_dependency_probe {edge|localapp_upstream|downstream}`、`probe_text_log`（edge/localapp）、`probe_config_snapshot`（localapp）、`probe_port_snapshot {local_port:14810}`、`probe_port_snapshot {local_port:14807}`。
- 这份诊断还验证了**修复一**的稳定性：模型写了 1 条 `contradictions`（正是 039 触发降级的那类说明），结论仍为 `confirmed_cause`。

### 5B 验收表（045 轮次）

| 通过条件 | 结果 | 证据 |
|---|---|---|
| 新目录 + 继承上一轮最新账本（hash/条数/历史未知项） | passed | `chain-equivalence.json`（`chain_equivalent=true`、`inherited_rows=1317`、`rows_1_to_history_byte_identical_all_12=true`、`unknown_usage_rows` 全 `[710]`、`expected_reserved_cny_match=true`、`expected_rows_added_match=true`） |
| 本轮新预留 ≤5 元 | passed | `result-summary.json`：`round_reserved_cny=0.424168`、`within_run_cap=true`、无未定价/未知新行 |
| 前端官方页恰好发起一次诊断 | passed | `browser-start.js`、`aiops_runs` 仅 1 行、账本仅新增 9 条请求 |
| SSE 事件、工具执行、模型输入和结果文件留存 | passed（含如实限制） | `event-trail-reconstructed.json`（checkpoint 13 + 工具 13 + 模型请求 9）、`product/tool_trace.json`、`model-inputs/` 9 份脱敏输入、`report.txt`；原始 SSE 帧未落盘 |
| 以合法工具取得并引用证据 | passed | 13 次 Probe/MCP 调用全部有效；报告引用 11 个 ev id（共 13 条证据） |
| 应用加载的下游端口 + 配置哈希 | passed | `ev-e8b28eb3eeb54598816e5e972e3e6c52`（`downstream_port=14810`、`source_sha256=73136c6c…`） |
| 同请求应用失败日志 | passed | `ev-323aaa7d89d040fea00c9c78afa8bc55`（`request_id=0c9c468e…`、`phase=connect`、`connection_established=false`、503） |
| 错误端口无监听/不可达 | passed | `ev-5b06c9d1786242e9a5bd6ffa6219e44b`（14810 无监听）+ `ev-f77786e6186041d08eb469b94366fa9c`（`localapp_upstream` TCP failed） |
| 登记下游健康 | passed | `ev-55a063eaebb349ecaf7183ee66669ecf`（14807 TCP ok / HTTP 200） |
| edge 与 localapp 同 `request_id` 失败链 | passed | `ev-323aaa7d…` + `ev-60ff2c7762984b788bc4a967bbb23051`（edge，`connection_established=true`、`response_status=503`） |
| 最终 `completed` + `confirmed_cause` + 原因码 | passed | `result-summary.json`、`run-detail.json` |
| 报告六项内容齐全 | passed | `report-headings.json`（`mentions_root_cause_line/impact/remediation/retest/unknowns/validation_notes` 全 true）、`report.txt` 6925 字符 |
| 不臆断无来源历史 | passed | 报告把配置变更者、变更动机、14810 历史生命周期、localapp 退出历史列为未知 |
| 刷新后报告可读 | passed | 刷新后报告 14661 字符、`原因已确认`、`evidence_nodes=40`、`aiops_post_after_refresh=0` |
| 同轮次后端停止/重启后一致 | passed | `acceptance-after-restart.json` 与 live 同 `report_sha256=e7b69c42af97…`、`evidence_total=13`、`requests 1326 → 1326` |
| 读取阶段零模型调用 | passed | live 与重启后两次读取均 `1326 → 1326`，`ledger_unchanged=true`、`evidence_files_unchanged=true` |
| 数据库内容一致 | passed | `logical-digest-final.json`（`all identical: True`）、`wal-attribution.json`、`heartbeat-drift.json`（仅 `probe_snapshots` 5→6 与 `probe_targets` 心跳变化） |
| 证据完整性 | passed | `gate-b-acceptance.json` 五类全 `ok/cited/hash=true`；`gate-b-checks.json` `evidence_all_hash_verified=true`、`bad evidence: []`、稳定产物 7 项字节一致 |
| 预算 ≤5 元 | passed | `round_reserved_cny=0.424168`、`limit_cny=58.027216`、`within_run_cap=true` |
| 环境恢复与清理 | passed | `environment.json`：`stopped`、`three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`ended_at=2026-11-08T02:08:32.622532Z` |

### 交付物（045 轮次，含重建件）

| 文件 | 字节 | SHA256（前 12 位） | 内容 |
|---|---|---|---|
| `result-summary.json` | 1455 | `42a01c783d55` | 轮次摘要（含预算、环境、artifact hashes） |
| `decision-audit.json` | 18997 | `2f4e5e4113a0` | 只读重建的决策审计 |
| `latest-state.json` | 84537 | `7bb11158ca87` | 最终 diagnosis + investigation 状态 |
| `event-trail-reconstructed.json` | 20673 | `a285257e12e8` | checkpoint/工具/模型请求时序轨迹 |
| `chain-equivalence.json` | 3766 | `647308724237` | 十二段账本继承等价性（脚本改为按自身目录自动推导段数） |
| `gate-b-acceptance.json` | 4478 | `f93bf438e783` | 五类必需证据映射（全满足） |
| `gate-b-checks.json` | 16232 | `5cf7dd2dc809` | 产物哈希对比与预算块 |
| `evidence-hashes.json` | 7535 | `0e6e8a41b9a6` | 34 文件 + 13 证据 + 9 model-inputs（独立复算 0 不符 / 0 缺失） |
| `report.txt` | 10372 | `7609598853fb` | 报告原文（6925 字符） |
| `ckpt-decoded.json` | 7227 | `50659b4ed887` | checkpoint 解码（诊断写 `1f1db18c-…`） |
| `product-model/cost.json` | 2407518 | `54a2c235089e` | 轮次账本（1326 行） |
| `product-model/run-budget.json` | 204 | `1c924a16a6e4` | 本轮 5 元额度基线 |

### 剩余限制

- 原始 SSE 帧未落盘；以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代。
- `/steps` 接口未启用；普通用户 `can_read_raw=false`。
- 报告仅引用 13 条证据中的 11 条（未引用：`ev-8d39d7b5…`、`ev-a982ce57…`）。
- 仍有 1 条未决问题（localapp 进程是否在请求前停止）无法核验：`localapp` 事件通道未配置，日志 `covers_full_history=false`。
- 4 条校验提示均为「候选检查不可调度（该检查此前已执行 / 已有该对象和参数的检查结果）」，未作为结论依据。

### 对 Goal 判定的影响

045 是连续五轮的第二轮，结论 `confirmed_cause` + 正确原因码 → 本轮**通过**。纳入统计：含全部十轮（036–045，各轮 P/P/P/F/P/F/P/P/F/P）为 **7/10**；修复二之后（042、043、044、045）为 **3/4**。045 还提供了一个修复一的稳定样本：模型本轮写了 1 条 `contradictions`（与 039 同类），结论仍正常升为 `confirmed_cause`。

## Goal 完成判定（2026-11-07）

两道门的通过条件逐条对应如下，全部为产品侧可复现证据，不以 `workflow completed`、`localized_fault` 或环境 `ready` 作为通过依据：

| 状态 | 结果 | 判定依据 |
|---|---|---|
| `free_replay` | `passed` | 034 原始材料 75/75 hash 一致；回放忠实重现 `unlocated`（`model_calls=0`、`new_observations=0`）；反馈四态区分（漏引用 / 未采集 / 不完整 / 矛盾）有单测断言，且不含根因码、引用文本、工具名与工具参数；165 个测试通过（唯一警告为既有 PyMilvus 弃用） |
| `free_environment` | `passed` | `endpoint`（目录 c）与 `normal`（目录 d）各自全新目录独立判定：真业务请求、同 `request_id` 的 edge/localapp 日志经 Probe/MCP 唯一命中且状态一致、轮次切换后旧日志残留 0、停止后三入口 200；`freegate-20261106-b/evidence-hashes.json` 22/22 命中磁盘 |
| `paid_run` | `passed`（注意：039、041、044 未通过，040、042、043、045 通过） | 036 在未提交工作区、037 在干净 main 上各跑一轮单轮授权，038 再独立复跑一轮通过，039 第三次复跑未通过，040 修复判定逻辑后再跑一轮通过，041 修复后第二次复跑未通过，042、043 修复「策略抢排 + 空壳提议」后各再跑一轮通过，044 连续五轮第一轮未通过、045 第二轮通过：036 新增 17 次请求（1192–1208）新增预留 0.833756 元；037 新增 17 次（1209–1225）0.920086 元；038 新增 15 次（1226–1240）0.794704 元；039 新增 14 次（1241–1254）0.613538 元；040 新增 15 次（1255–1269）0.776214 元；041 新增 13 次（1270–1282）0.669814 元；042 新增 14 次（1283–1296）0.64755 元；043 新增 9 次（1297–1305）0.359006 元；044 新增 12 次（1306–1317）0.590998 元；045 新增 9 次（1318–1326）0.424168 元。十轮均在各自重置后的 5 元上限内；全部 `deepseek-v4.1-flash-1017` 且已定价，无新增未知 usage、无未定价新行、`blocked_requests` 未增加；账本继承等价性由各轮 `chain-equivalence.json` 独立复核（045 为十二段链，脚本已改为按自身目录自动推导段数） |
| `root_cause` | `passed`（036/037/038/040/042/043/045 七轮通过；039、041、044 未通过） | 036/037/038/040/042/043/045 均为 `completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`，五类必需证据全部由合法工具取得并被报告引用；无来源历史均列为未知。**039 同一场景得到 `localized_fault`**：模型提议是正确的 `confirmed_cause`，但因其在 `contradictions` 里写了「8944 历史原因未知」而触发 `sufficient` 的 `not decision.contradictions` 否决；该缺陷已修复，040 在同一场景重新得到 `confirmed_cause`。**041 修复后第二次复跑又得到 `localized_fault`**：模型在 checkpoint 16/17 已给出证据完整的 `confirmed_cause`（5 条必需证据齐备且被引用），但策略引擎在同期抢先排入一次 loopback 监听检查，多走一轮后末轮模型自己交回空壳提议（`supporting_evidence` 0 条、把一条 `unresolved/noncritical` 替代解释改成 `supported/critical`），终局降级；两处已修复，**042 与 043 连续两轮重新得到 `confirmed_cause`**（043 仅用 9 次请求即收束、无 unresolved 项）。**044 连续五轮第一轮得到 `unlocated`**：模型末轮提议同样是证据完整的 `confirmed_cause`（10 条支撑、正确原因码），但它在最后一条 alternative 上把已有候选 `h-7676d16ebd50773f`（edge 日志）的 id 与 `ports/1871` 的 condition 配错，触发 `_resolve_candidate_identity` 的身份熔断（`src/agent/aiops/strategies/investigation.py:1916-1919`、清空段 `:1986-1989`），且该轮未采集错误端口探测与 downstream 依赖健康两类证据；回放显示仅清空错配 id 也只是让引擎继续调查（`plan 1`），不会自动升为结论。**045 第二轮恢复 `confirmed_cause`**：16 条证据、5 条替代解释、13 次工具调用覆盖全部五类必需证据，且模型本轮写入 1 条同类 `contradictions` 仍未被降级（修复一稳定）。详见「039 轮次复现记录」「判定逻辑修复」「040 轮次复跑记录」「041 轮次复现记录」「判定逻辑修复之二」「042 轮次复跑记录」「043 轮次复跑记录」「044 轮次复跑记录」「045 轮次复跑记录」 |
| `report_persistence` | `passed` | 036：刷新后报告 15678 字符且 `aiops_post_after_refresh=0`，重启后 `report_sha256=23b73151fa45…`、`requests 1208 → 1208`；037（干净 main）：刷新后 13247 字符、`aiops_post_after_refresh=0`，重启后 `report_sha256=34a4de2818b3…`、`evidence_total=14`、`requests 1225 → 1225`；038（干净 main 复跑）：刷新后 16033 字符、`aiops_post_after_refresh=0`，重启后 `report_sha256=cd9acfb3fccd…`、`evidence_total=14`、`requests 1240 → 1240`；039（未通过轮）：刷新后 11154 字符、`aiops_post_after_refresh=0`，重启后 `report_sha256=e13e19b4c938…`、`evidence_total=13`、`requests 1254 → 1254`；040（修复后轮）：刷新后 15012 字符、`evidence_nodes=42`、`aiops_post_after_refresh=0`，重启后 `report_sha256=87984ac7ba23…`、`evidence_total=14`、`requests 1269 → 1269`；041（未通过轮）：刷新后 12608 字符、`evidence_nodes=39`、`aiops_post_after_refresh=0`，重启后 `report_sha256=2fd7b87415ff…`、`evidence_total=13`、`requests 1282 → 1282`；042（修复后轮）：刷新后 12343 字符、`evidence_nodes=37`、`aiops_post_after_refresh=0`，重启后 `report_sha256=2c3cab27701a…`、`evidence_total=12`、`requests 1296 → 1296`；043（修复后轮）：刷新后 13394 字符、`evidence_nodes=32`、`aiops_post_after_refresh=0`，重启后 `report_sha256=8edcb711be36…`、`evidence_total=9`、`requests 1305 → 1305`；044（连续五轮第 1 轮，未通过轮）：刷新后 10030 字符、`evidence_nodes=30`、`aiops_post_after_refresh=0`，重启后 `report_sha256=90f58a7128c7…`、`evidence_total=10`、`requests 1317 → 1317`；045（连续五轮第 2 轮，通过）：刷新后 14661 字符、`evidence_nodes=40`、`aiops_post_after_refresh=0`，重启后 `report_sha256=e7b69c42af97…`、`evidence_total=13`、`requests 1326 → 1326`。十轮的稳定产物字节一致，WAL/checkpoint 增长经逻辑摘要与心跳归因确认为 SQLite 检查点与 Probe 心跳，诊断内容不变 |
| `cleanup` | `passed` | 035/036/037/038/039/040/041/042/043/044/045/c/d 十三个 `environment.json` 全部 `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`；14805–14815、1865–1880、4055–4070、4195–4210、7201–7210、3580–3595、5230–5240、8940–8950、9890–9900、8200、9083、9087 均无监听，无残留 python 进程 |

结论：A 门（免费门）与 B 门（单轮真实门）在 036、037、038、040、042 五轮均已通过，六个状态位全部 `passed`；039 的第三次复跑暴露了一个真实缺陷并以 `localized_fault` 结束（**修复前 Gate B 可复现率为 3/4**）。039 的失败模式已定位到 `sufficient` 中 `not decision.contradictions` 与「待核实说明」字段的耦合（模型提议本身是正确且证据完整的 `confirmed_cause`）。**该处已于 2026-11-07 按用户授权修好并验证**（见「判定逻辑修复」一节：039 真实提议回放由 `localized_fault` 变为 `confirmed_cause`，系统派生的现场事实冲突仍否决，四个核心测试文件 289 passed，全量 37 个失败与干净 HEAD 同一集合），**并在 040 轮次以全新 5 元额度真实复跑重新得到 `confirmed_cause` + `configured_downstream_endpoint_mismatch`（见「040 轮次复跑记录」），修复后 Gate B 可复现率为 4/5**。

**2026-11-08 补充：041 修复后第二次复跑未通过（`localized_fault`）。** 该轮失败与 039 不同源——`contradictions` 为空、039 的修复仍生效；失败模式是「策略引擎在结论已完整时抢先排入一次 loopback 监听检查」+「末轮模型自己退回空壳提议（0 条支撑引用、把一条 unresolved 非关键替代改成 supported 且 critical）」两段耦合（见「041 轮次复现记录」）。因此**修复后的真实复跑为 1 通过 / 2 尝试，尚未达到稳定复现**；含全部六轮为 4/6。历史轮次（036/037/038/040）的通过事实不变，但「稳定复现」这一更强主张需先修掉上述两处问题后复跑验证才能成立。

**2026-11-08 补充之二：这两处已按用户授权修好并验证（见「判定逻辑修复之二」）。** 用 041 的真实 checkpoint 回放：checkpoint 16/17 的完整结论不再被策略检查抢占（`plan=[]`、`confirmed_cause`），末轮空壳提议被显式拒绝而非降级接受；新增 3 条单测，四个核心文件 **292 passed**，全量失败集合与干净 HEAD 完全相同（37 个既存失败）。

**2026-11-08 补充之三：042 已用新额度真实复跑并重新通过（见「042 轮次复跑记录」）。** 042 在同一 `endpoint` 场景得到 `completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`，14 次请求（1283–1296）新增预留 0.64755 元，五类必需证据齐备并被报告引用，刷新与同轮次重启后报告/证据/账本完全一致且零新增模型调用，环境干净停止。至此**修复后两轮（040、042）2/2 通过、含全部七轮（036–042）6/7 通过**。「稳定复现」仍需继续累积样本，本文件不据此作无条件稳定性断言。

仍照实保留的限制：原始 SSE 帧未落盘（以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代）、部分候选检查提议因工具目录/重复检查被拒、`/steps` 未启用（`total: 0`）、普通用户 `can_read_raw=false`、`localapp` 事件通道未配置。
