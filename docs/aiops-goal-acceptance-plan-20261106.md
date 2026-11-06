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
| 5B. 真实门（036 轮次执行） | passed | 预算清单、SSE/工具轨迹、脱敏模型输入、报告与证据 hash、数据库重启读取、费用账本 | 全链路、根因门槛、六项报告内容、刷新/重启一致及零读取模型调用全部通过，费用与清理符合约束 |

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

## Goal 完成判定（2026-11-07）

两道门的通过条件逐条对应如下，全部为产品侧可复现证据，不以 `workflow completed`、`localized_fault` 或环境 `ready` 作为通过依据：

| 状态 | 结果 | 判定依据 |
|---|---|---|
| `free_replay` | `passed` | 034 原始材料 75/75 hash 一致；回放忠实重现 `unlocated`（`model_calls=0`、`new_observations=0`）；反馈四态区分（漏引用 / 未采集 / 不完整 / 矛盾）有单测断言，且不含根因码、引用文本、工具名与工具参数；165 个测试通过（唯一警告为既有 PyMilvus 弃用） |
| `free_environment` | `passed` | `endpoint`（目录 c）与 `normal`（目录 d）各自全新目录独立判定：真业务请求、同 `request_id` 的 edge/localapp 日志经 Probe/MCP 唯一命中且状态一致、轮次切换后旧日志残留 0、停止后三入口 200；`freegate-20261106-b/evidence-hashes.json` 22/22 命中磁盘 |
| `paid_run` | `passed` | 单轮授权下 17 次新请求（行号 1192–1208，全部 `deepseek-v4.1-flash-1017` 且已定价），新增预留 0.833756 元 ≤ 5 元；无新增未知 usage、无未定价新行、`blocked_requests` 未增加；034→035→036 账本继承等价性由 `chain-equivalence.json` 独立复核 |
| `root_cause` | `passed` | `completed` + `confirmed_cause` + `configured_downstream_endpoint_mismatch`；五类必需证据全部由合法工具取得并被报告引用（12/14 个 ev-id 出现在报告中）；变更者/变更时间/停止发起者/退出历史等无来源历史均列为未知 |
| `report_persistence` | `passed` | 刷新后报告 15678 字符且 `aiops_post_after_refresh=0`；同轮后端停止再重启后 `report_sha256=23b73151fa45…`、`evidence_total=14`、诊断对象与证据元数据一致，`requests 1208 → 1208`；7 个稳定产物字节一致，WAL/checkpoint 增长经逻辑摘要与心跳归因确认为 SQLite 检查点与 Probe 心跳，诊断内容不变 |
| `cleanup` | `passed` | 035/036/c/d 四个 `environment.json` 全部 `status=stopped`、`recovery=three_business_endpoints_200`、`ports_released=true`、`owned_processes_stopped=true`、`cleanup_errors=[]`、`environment_model_calls=0`；7201–7205、8200、9083、9087 无监听 |

结论：A、B 两道门均已通过，六个状态位全部 `passed`，Goal 标记完成。遗留限制照实保留在上文「剩余限制」：原始 SSE 帧未落盘（以 checkpoint + 工具轨迹 + 模型输入 + 账本重建轨迹替代）、4 条候选检查提议因工具目录/重复检查被拒、`/steps` 未启用、普通用户 `can_read_raw=false`、`localapp` 事件通道未配置；且本门全部结论产生于未提交工作区（HEAD `3a4bd4a` + 4 个改动文件），不构成干净 main 的验证。
