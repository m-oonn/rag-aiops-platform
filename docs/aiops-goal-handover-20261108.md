# AIOps 真实诊断验收：交接说明（2026-11-08）

这份文档是给接手的人看的。它不重复过程记录——逐轮细节、每一行证据哈希、每一次失败的代码级取证都在
[aiops-goal-acceptance-plan-20261106.md](aiops-goal-acceptance-plan-20261106.md)（约 200 KB）里。
这里只讲四件事：**现在到底是什么状态**、**证据在哪**、**怎么复现**、**别宣称什么**。

---

## 1. 一句话状态

在一个隔离的 Windows 测试环境里，从网页点一次「开始诊断」开始，真实模型经 Probe → Gateway → MCP 取证，
对 `configured_downstream_endpoint_mismatch`（应用加载的下游端口 ≠ 登记的下游端口）这个场景，

- **15 轮真实付费诊断：10 轮通过（`confirmed_cause` + 正确原因码），5 轮未通过**；
- 5 次失败中 **3 次是我们的判定逻辑有缺陷**（已全部修复，每一处都有真实 checkpoint 回放证据），
  **2 次是模型自己的判断失误**（故意不修，理由见 §5）；
- 无论通过与否，**持久化、账本、清理三件事 15 轮全部做到**：刷新可读、同轮次重启可读且零新增模型调用、
  环境干净停止无残留进程与端口；
- 新增预留花费合计 **9.611526 元**（195 次模型请求），每轮各自在重置后的 5 元上限内；
- 已把「改判定规则不许把已通过的轮次改坏」做成**零成本回放门禁**，装进 CI。

**「修复后可稳定复现」这个更强的说法仍然不成立**，见 §6。

---

## 2. 证据在哪

| 位置 | 内容 |
|---|---|
| `docs/aiops-goal-acceptance-plan-20261106.md` | 主文档：两道门定义、免费门记录、036–050 逐轮记录（含 20 行 5B 验收表）、三次判定逻辑修复的取证、零成本回放门禁、Goal 完成判定表 |
| `runtime/aiops-goal-036/` … `runtime/aiops-goal-050/` | 每轮一个目录，各约 5–9 MB（15 轮合计 113 MB）。**`runtime/` 在 `.gitignore` 内，只存在于这台机器** |
| 每轮目录内的 `result-summary.json` | 该轮结论、请求号区间、新增预留、环境清理结果的汇总（重建件，不含新模型调用） |
| 每轮目录内的 `gate-b-acceptance.json` / `gate-b-checks.json` | 五类必需证据的逐项核验；产物稳定性与预算核验 |
| 每轮目录内的 `product/` | `runs.sqlite`（运行与报告）、`checkpoints.sqlite`（LangGraph 全量状态）、`tool_trace.json`、`evidence/*.json` |
| 每轮目录内的 `product-model/` | `cost.json`（逐请求账本）、`run-budget.json`（本轮预算清单）、`model-inputs/*.json`（每次发给模型的完整请求体，已脱敏） |
| 每轮目录内的 `acceptance-live.json` / `acceptance-after-restart.json` | 刷新前 / 重启后两个时点的报告哈希与证据数，用于证明持久化且零新增调用 |
| 每轮目录内的 `chain-equivalence.json` | 该轮账本与其全部前序账本的逐行字节等价性证明 |

`runtime/` 不进版本库是刻意的（体积 + 含本机路径）。要把它变成可交接材料，见 §8 的选项。

---

## 3. 逐轮结果

端口列依次是 edge / localapp / registered downstream；「配置错端口」是 `business/localapp.connection.json`
里 `downstream_port` 被写成的那个值（该端口在场景里没有监听）。

| 轮次 | 结论 | 原因码 | 请求号 | 模型调用 | 新增预留(元) | 端口 | 说明 |
|---|---|---|---|---|---|---|---|
| 036 | `confirmed_cause` | ✅ | 1192–1208 | 17 | 0.833756 | 7201/7202/7203，错 7204 | 脏工作区首轮通过 |
| 037 | `confirmed_cause` | ✅ | 1209–1225 | 17 | 0.920086 | 3581/3582/3583，错 3584 | 干净 main 复跑通过 |
| 038 | `confirmed_cause` | ✅ | 1226–1240 | 15 | 0.794704 | 9890/9891/9892，错 9893 | 独立复跑通过 |
| 039 | `localized_fault` | — | 1241–1254 | 14 | 0.613538 | 8941/8942/8943，错 8944 | **系统缺陷一**，已修 |
| 040 | `confirmed_cause` | ✅ | 1255–1269 | 15 | 0.776214 | 11376/11377/11375，错 11378 | 修复一验证通过 |
| 041 | `localized_fault` | — | 1270–1282 | 13 | 0.669814 | 5233/5234/5235，错 5236 | **系统缺陷二**，已修 |
| 042 | `confirmed_cause` | ✅ | 1283–1296 | 14 | 0.647550 | 4200/4201/4199，错 4202 | 修复二验证通过 |
| 043 | `confirmed_cause` | ✅ | 1297–1305 | 9 | 0.359006 | 4059/4060/4061，错 4062 | 仅 9 次请求即收束 |
| 044 | `unlocated` | — | 1306–1317 | 12 | 0.590998 | 1869/1870/1871，错 1872 | 模型侧：候选 id 配错（2026-11-09 尝试修复后主动回滚，见 §5） |
| 045 | `confirmed_cause` | ✅ | 1318–1326 | 9 | 0.424168 | 14808/14809/14807，错 14810 | |
| 046 | `confirmed_cause` | ✅ | 1327–1340 | 14 | 0.720520 | 10339/10340/10341，错 10342 | |
| 047 | `confirmed_cause` | ✅ | 1341–1349 | 9 | 0.402616 | 4568/4569/4570，错 4571 | |
| 048 | `confirmed_cause` | ✅ | 1350–1362 | 13 | 0.614854 | 14825/14826/14827，错 14828 | |
| 049 | `localized_fault` | — | 1363–1377 | 15 | 0.851434 | 14298/14299/14300，错 14301 | **系统缺陷三**，已修 |
| 050 | `localized_fault` | — | 1378–1386 | 9 | 0.392268 | 7712/7713/7714，错 7715 | 模型侧：未核实解释标成关键 |

合计：**195 次请求、9.611526 元**；账本从 1191 行（034 期末）增长到 1386 行，`reserved_cny` 46.82155 → 56.433076。

---

## 4. 三处系统侧缺陷（已修，都有回放证据）

三处的共同模式都是：**模型给出了证据完整、原因码正确的 `confirmed_cause`，被我们的判定或策略代码否掉了。**

### 缺陷一：模型写的「待核实说明」被当成可靠反证（039）

- 症状：模型在 `contradictions` 里写了一条「8944 无监听的历史原因仍未知」，`sufficient` 合取式里的
  `not decision.contradictions` 直接把整条结论否掉，降级为 `localized_fault`。
- 问题本质：`contradictions` 字段的定义本来就是「待核实说明，不是可靠反证」，提示词也这么写；
  但校验器把它当成了一票否决。同时系统自己也往这个列表里追加真实冲突，两者混在一个字段里。
- 修法（`9f1e5e1`）：新增局部变量 `field_conflicts`，只装系统派生的两类真实冲突
  （「等待模型后现场证据未通过重新校验」「引用已被同范围不同结果更新」），`sufficient` 改为
  `and bool(decision.alternatives) and not field_conflicts`；`diagnosis['contradictions']` 仍原样输出模型原文。
- 证据：039 真实 checkpoint 回放，`localized_fault` → `confirmed_cause`。

### 缺陷二：结论已完整时策略抢排检查 + 末轮空壳提议被接受（041）

- 症状甲：模型在 checkpoint 16 已给出五类证据齐备的结论，`dependency_followup_policy` 仍抢先排入一次
  loopback 监听检查并覆盖 `next_check`，多走一轮。
- 症状乙：末轮模型交回空壳提议（`supporting_evidence` 0 条、把一条 `unresolved/noncritical` 改成
  `supported/critical`），被当成有效提议接受并降级。
- 修法（`2f8c24d`）：新增模块级 `_EMPTY_TERMINAL_CLAIM` 与 `empty_terminal_claim(decision)`，先显式拒绝空壳；
  再算 `model_terminal_cause`，成立时 **跳过** `dependency_followup_policy`。
- **踩过的顺序教训**：空壳拒绝必须先于「缺必需证据则降级」那段，否则留痕会被覆盖、策略检查照旧排队。
- 证据：041 checkpoint 16/17 回放 `plan=[]` + `confirmed_cause`。

### 缺陷三：同一个绑定规则查两遍，一次放行一次否决（049）

- 症状：五类必需证据与正确原因码齐备，仍降级。两处原因：
  1. `_validate_alternatives` 对「模型原文没有逐字复述条件、但状态由证据推导」**显式放行**
     （`derived_status=True` → `verification='predicate_verified'`），而 `sufficient` 的替代解释子句
     又**重复要求** `_condition_bound`（原文必须逐字等于条件公式），同一份数据两处规则不一致。
  2. 模型把收束说明写进 `next_check`（「证据链已齐备…；不再新增工具检查。」），非空字符串被
     `_incomplete_check_contract_fields` 判成「检查提议缺少必需字段」。
- 修法（`6da5cf8`）：`sufficient` 信任已完成校验的 `verification=='predicate_verified'`，去掉重复的
  `_condition_bound`；新增「收束说明识别」——`next_check` 非空但 `next_tools` / `next_arguments` /
  `discriminating_question` / `expected_observation` 全空且直接原因证据齐备时，按「模型声明停止」处理并留痕。
- 证据：049 checkpoint 20 回放 `localized_fault` → `confirmed_cause`、`plan=[]`。

三处修复合计：`src/agent/aiops/strategies/investigation.py` 净增约 60 行判定代码 + 7 条单测；
六个判定相关测试文件从 358 → 362 passed，加上回放门禁 4 条后共 **366 passed**。

---

## 5. 两次模型侧失败（故意不修）

这两次**不是系统缺陷**，按现行规则也不该放松校验。区别在于：缺陷是「证据齐备的正确结论被系统否掉」，
而这两次是「模型给出的提议本身不满足规则」。

### 044（`unlocated`）

模型末轮提议是证据完整的 `confirmed_cause`（10 条支撑、正确原因码），但在最后一条 alternative 上
**把两个已有候选的 id 和 condition 配错了**：用了 edge 日志那条候选的 `hypothesis_id`，配的却是
`ports/1871` 那条的 condition。系统的 `_resolve_candidate_identity` 因此熔断并清空结论
（`src/agent/aiops/strategies/investigation.py` 中 `_resolve_candidate_identity` 与紧随其后的清空段）。
回放显示：**只清空那个错配的 id，引擎也只是继续调查（`plan 1`），不会自动升为结论**。

**2026-11-09 已尝试修复并主动回滚**：把熔断限制为「只有主假设身份错配才停」，让单条 alternative 的
配错只作废那一行。回放效果符合预期（044 从 `unlocated` 变成继续调查 `plan 1`，15 轮无回归、
`regressed=[]`），但全量测试多出 5 个失败——`tests/test_investigation_mechanisms.py` 的三组用例
（`test_unknown_candidate_reference_stops_without_creating_or_replacing_candidates[alternative]`、
`test_candidate_reference_cannot_retarget_a_saved_prediction[*]`、
`test_rewritten_exclusion_is_atomically_rejected_and_saved_prediction_preserved`）明确锁定了**整轮原子拒绝**
这一安全契约：任一角色试图把已保存的预测改指向时，整轮拒绝，避免模型靠改写条件伪造排除。
也就是说不是代码写错，而是这条改动削弱了一项**有意的**安全不变量。已 `git checkout` 回滚，
工作区恢复干净（`tests/test_recorded_round_replay.py` + `tests/test_investigation_mechanisms.py` → 92 passed）。

结论修正：044 **不是**第四处该修的系统缺陷，而是系统按设计阻止「模型改写已保存预测」时连带损失的
一次本可继续的调查。真要让 044 通过，需要放宽那条原子性契约——在拿到更强理由前不应改。

### 050（`localized_fault`）

模型末轮提议已经是证据完整、收束字段清空的 `confirmed_cause`（7 条支撑、正确原因码），
但它把「localapp 上游超时设置过短（0.5s）」这条**自己没核实**的竞争解释标成 `critical=True`
且不写 `noncritical_reason`，替代解释析取式因此不成立（`alternatives_ok=false` 是唯一失败子句）。

判断这属模型侧的四个依据：

1. `model-inputs/1386.json` 的 system 提示就是 `cause_correction` 的复核提示，明确写着
   「若你已引用证据说明某个未决解释不能造成本次请求失败，该理由须填写在 `noncritical_reason`，
   并由你判断 `critical`；只把理由放 `limitation` 仍会保留关键未决状态」——系统已把口径讲清，模型没照做。
2. 同样写法在 048 被模型自己标成 `unresolved + critical=False` 并通过。
3. 四个反事实变体：按原文回放 → 拒绝；只把它改成 `critical=False` + 补理由 → **`confirmed_cause`**；
   删掉它 → 同样通过；**强行标成 `excluded` 却不给证据 → 仍被拒**，并新增「因果主张不能由有限现场条件
   证明排除」的 issue。也就是说松绑会同时放出真正该被挡住的东西。
4. 修复三的留痕（「把收束说明写在 next_check 里」）本轮**没有出现**，说明模型这次自己把字段清干净了。

---

## 6. 别宣称什么

- ❌ **「修复后可稳定复现」**。10/15 是事实，且修复三之后的唯一一轮（050）未通过。分阶段口径：
  含全部十五轮 10/15；修复一之后（040–050）7/11；修复二之后（042–050）6/9；修复三之后（050）0/1。
  修复后连续通过的最长记录是 042、043（2 轮）与 045–048（4 轮）。
- ❌ **「模型已经可靠」**。两处模型侧失误（候选 id 配错、未核实解释标成关键）都发生在方案完全正确、
  证据齐备的时刻，属于模型自身的簿记与判断问题，与提示词无关（提示词已反复讲清）。
- ❌ **「真实花费 = 9.6 元」**。9.611526 元是**新增预留**（按峰值价率上界计算），不是账单。
  账本里有 61 行历史记录没有 `pricing_verified`、第 710 行 usage 未知，因此
  `cumulative_actual_cost` 只能标 `"unknown"`。
- ❌ **「干净 main 已验证全部轮次」**。036 在未提交工作区上跑的；037、038 在干净 main 上；
  039 之后工作区又陆续带入修复，每轮的 `HEAD` 记录在对应轮次目录与主文档里。
- ❌ **「原始 SSE 已留证」**。原始流式帧没有落盘（`raw_sse_frames_persisted=false`），
  轨迹是用 checkpoint + 工具调用 + 模型输入 + 账本重建的。
- ❌ **「全量测试全绿」**。全量 `pytest tests -q` 是 2071 passed / 37 failed，这 37 个是**改动前就存在**的
  既存失败（`test_matching503_output_flow.py` 24、`test_four_issue_closeout.py` 6、
  `test_agent_knowledge_consumption.py` 5、`test_live_probe_mechanisms.py` 1、
  `test_probe_summary_output_flow.py` 1），已用 `git stash` 回到干净 HEAD 比对过失败集合完全相同。

其他如实保留的限制：部分候选检查提议因工具目录缺失或重复检查被拒（各轮 `validation_issues` 1–9 条，
多数为 2–4 条）；`/steps` 未启用（`total: 0`）；普通用户 `can_read_raw=false`；`localapp` 事件通道未配置；
报告并未引用全部证据（各轮引用 7–12 条，未引用的列在 `gate-b-acceptance.json` 的 `uncited_evidence` 里）。

---

## 7. 怎么复现一轮

### 7.1 判定规则门禁（零成本，先跑这个）

```powershell
python -m pytest -q tests/test_recorded_round_replay.py
```

它把 036–050 这 15 轮记录在 checkpoint 里的模型提议，用当前 `decide_from_evidence` 重判，
零模型调用、约 2 秒。四条不变量：曾通过的轮次不许回放失败、039/049 必须被当天规则接受、
仍被拒的（041/044/050）必须写明 `blocked_reason`、每轮必须落到终态诊断。

语料是 `tests/data/recorded-rounds.json.gz`（391 KB，随仓库提交），由 `scripts/distil_recorded_rounds.py`
从 `runtime/` 蒸馏；`runtime/` 存在时优先用真目录，不存在时回落到语料，两者结果一致。
CI 里对应步骤名 `Decision-rule gate (recorded paid rounds must not regress)`。

**改动 `src/agent/aiops/strategies/investigation.py` 的判定逻辑前必须先跑这个。**

### 7.2 跑一轮真实诊断（会产生费用，需明确授权）

```powershell
# 1) 建隔离环境（免费）。scenario=endpoint 即「配置端口错」，duration 给足 3600 秒
python scripts/aiops_test_environment.py start --output runtime\aiops-goal-0XX `
    --scenario endpoint --duration-seconds 3600

# 2) 起付费后端。--previous-cost 指向上轮最新账本；run-budget.json 由这一步生成
python scripts/aiops_test_environment.py backend --output runtime\aiops-goal-0XX --port 8200 `
    --run-model --profile .env.agent-test `
    --previous-cost runtime\aiops-goal-0YY\product-model\cost.json

# 3) 渲染这一轮的 Playwright 片段（从轮次目录的 login.json 取账号，不落明文到仓库）
python scripts/aiops_round/render_browser.py --round-dir runtime\aiops-goal-0XX

# 4) 网页点一次（浏览器要先 open 再等 8–12 秒，否则 fill 会 30 秒超时）
#    playwright-cli -s=aiops0XX open http://127.0.0.1:8200/login
#    playwright-cli -s=aiops0XX run-code --filename scripts\aiops_round\browser-start.js

# 5) 收尾：先停后端再停环境（顺序重要，否则 logical_digest 取不到重启前基线）
#    新建空文件 runtime\aiops-goal-0XX\stop-backend，等 8200 释放
#    新建空文件 runtime\aiops-goal-0XX\stop
```

`--run-model` 的后端有硬性闸门：本轮只允许**一次** `POST /api/v1/aiops`，之后 403；
轮次不符 503。所以网页只能点一次，观察时不要改写任何输入。

### 7.3 一轮完整的验收动作清单

辅助脚本在 `scripts/aiops_round/`（**随仓库提交**，不再需要拷进轮次目录）。它们用同一个
定位规则找轮次：`--round-dir runtime/aiops-goal-0XX` → 环境变量 `AIOPS_ROUND_DIR` → 否则取
最新一个跑过（有 `product-model/cost.json`）的目录。所以最省事的用法是先在 shell 里设一次：

```powershell
$env:AIOPS_ROUND_DIR = 'runtime/aiops-goal-0XX'
```

按顺序跑（全部只读，除 `ledger_snapshot.py` 写快照、`report_outline.py` 写 `report.txt`）：

`ledger_snapshot.py before` → 点击 → `observe.py`（只读观察）→ `accept_reader.py live` →
`render_browser.py --thread <thread_id>` + `browser-refresh.js`（刷新取证）→
`hash_artifacts.py before-restart` → 重启后端 → `accept_reader.py after-restart` →
`logical_digest.py after-restart` → `hash_artifacts.py after-restart` → 停后端 →
`logical_digest_final.py` / `wal_attribution.py` / `heartbeat_drift.py` → 停环境 →
`build_deliverables.py` / `build_event_trail.py` / `ckpt_decode.py` /
`report_outline.py`（先生成 `report.txt`，否则 `gate_b_acceptance.py` 会 FileNotFoundError）/
`gate_b_acceptance.py` / `gate_b_checks.py` / `verify_chain.py` / `hash_evidence.py`。

最后用 `check_all_envs.py` 确认所有环境都干净停止（`stopped` + 三入口 200 + 端口释放 +
进程停止 + `cleanup_errors` 为空 + 环境自身零模型调用）。

脚本里原本硬编码的四个轮次常量现在都从轮次目录自己读：目录名（`round_dir()`）、
错配端口（`wrong_port()`，读 `gate-b-acceptance.json` 的配置证据——环境停止时 fixture 会把
`business/localapp.connection.json` 改回健康端口，归档配置不可信）、继承行数与继承预留
（`inherited_baseline()` / `inherited_reserved()`，读 `product-model/run-budget.json`）。
`verify_chain.py` 的段数按轮次目录自动推导，直接跑即可。

---

## 8. 下一步可选的几条路

1. **继续累积真实样本**：再跑 051、052……每轮约 0.4–0.9 元。价值是提高统计置信度，
   但**不会**改变「模型侧失误不可控」这一性质；建议一次只跑 3–5 轮并附授权。
2. **把 `runtime/` 冻成交接包**：15 轮共 113 MB，含本机绝对路径。可以打成 zip 放共享盘，
   或把每轮的 `result-summary.json` / `gate-b-acceptance.json` / `report.txt` / `report-headings.json`
   抽出来做一份轻量只读包（约几 MB），让没这台机器的人也能查看。
   注意：**验收脚本本身已经不再依赖这一步**——见 §7.3，辅助脚本已在 `scripts/aiops_round/` 里，
   拿不到 `runtime/` 的人也能用蒸馏语料跑门禁、也能对自己的新轮次跑全套验收。
3. **提升一过成功率**：针对两处模型侧失误做**结构性约束**（例如候选 id 必须来自上一轮已有候选、
   `critical=True` 的未决解释必须有 `noncritical_reason` 或证据引用），而不是继续改提示词。
   注意：任何此类改动都必须先过 §7.1 的门禁，且不得把 041/044/050 的拒绝理由变成「无理由通过」。
4. **补 37 个既存失败**：与本任务无关，但会让 CI 噪音掩盖真回归。

---

## 9. 相关提交

| commit | 内容 |
|---|---|
| `a912947` / `eddc319` / `53b1a1a` | 免费门：依赖证据覆盖度区分、历史产品布局只读回放、验收记录 |
| `948b062` | 干净 main 复跑 + 037 真实门（重置额度） |
| `0f2cb7e` `dc58a98` | 038 通过、039 未通过及其降级根因 |
| `9f1e5e1` | **修复一**：待核实说明不再否决已引用完整的结论 |
| `981e110` | 040 修复后验证通过 |
| `7111780` | 041 未通过与「策略抢排 + 空壳提议」根因 |
| `2f8c24d` | **修复二**：完整结论不再被策略检查重开 + 空壳终态显式拒绝 |
| `649c08e` `f4a4abf` | 042、043 修复后连续两轮通过 |
| `b451271` `c32092a` `3556fa6` `3395ba4` `6343572` | 连续五轮 044 失败、045–048 通过 |
| `6da5cf8` | **修复三**：信任已校验的排除项 + 收束说明不再被当成检查 |
| `2d34c3e` | 049 未通过、050 模型侧未通过 |
| `cee906d` | 回放门禁第一版（依赖本机 `runtime/`） |
| `f7ca98b` `f47562f` `e367c5c` | 蒸馏语料 + CI 步骤，让门禁在没有 `runtime/` 的机器上也能跑 |
| `fcc78d8` | 本交接说明 + 验收辅助脚本入库（`scripts/aiops_round/`，去掉全部轮次硬编码） |
