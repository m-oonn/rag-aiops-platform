# AIOps 诊断能力补全记录

> 目的：把「用真实案例实测暴露出来的能力缺口」固化成可执行的改造清单。
> 记录时间：2026-10-10
> 实测环境：本机 `192.168.5.71`（WLAN），`MONITOR_BACKEND=prometheus` 但 `PROMETHEUS_URL` 为空，
> `cls`(8103) / `knowledge_base`(8105) 未启动，仅 `monitor`(8104) 可用。

---

## 1. 实测基线：三个案例，项目实际给出了什么

| # | 案例 | 真实现象 | 项目结论 | 判定 |
|---|---|---|---|---|
| A | `127.0.0.1:8103`（本机端口无监听） | 服务没起 | "连接被拒绝 → 目标端口未开放或服务未启动" | ✅ 正确 |
| B | `192.168.3.251:19001/document` | 后台 PDF 服务停了 | "CPU/内存被占满 → 任务处理不完" | ❌ 误判（且数字是 Mock 编的） |
| C | `https://deeppub.keyanjia.com/document` | 页面正常，但后台审校服务卡住不返回 | "网站入口正常，但后台服务器 CPU/内存过载" | ⚠️ 半对：症状对、根因错、数字是 Mock 编的 |

**从 A/B/C 抽出的三条硬结论：**

1. **它只能看"网页门口"（HTTP 层），看不到"网页背后的业务服务"。** `check_website` 拿到 200 就报"网站正常"，
   而"任务 20 分钟不返回"这种业务层故障完全在盲区。
2. **Mock 假数据会把结论带偏。** 案例 B/C 里报告的 "CPU 85%、内存 78%、持续 49 分钟" 全部来自
   `mock_scenario.py` 的 `infra_cpu` 默认剧本（服务名未命中任何剧本 → 回退 `infra_cpu` 爬升曲线），
   不是真实监控。报告却把它当真实证据用来定根因。
3. **"不可达"分不清原因。** 跨网段时只能拿到"连接超时"，代码把超时归为"可能被防火墙拦截或服务繁忙"，
   无法区分"服务停了 / 主机不通 / 防火墙 DROP"。

---

## 2. 能力缺口（按证据链分层）

| 故障层次 | 需要的证据 | 项目现状 |
|---|---|---|
| 网络可达性 | DNS / TCP 连接结果（refused vs timeout vs filtered） | ⚠️ 有探测，但超时语义含糊、无分层字段 |
| 进程存活 | 目标端口是否有进程 listen | ❌ 无工具 |
| 服务健康 | `/health`、业务接口状态码/耗时 | ❌ 无工具（只有页面级 HTTP） |
| 业务任务 | 任务状态、队列积压、任务耗时 | ❌ 无工具 |
| 应用日志 | 错误堆栈、超时、任务堆积 | ⚠️ 有 `cls`，但默认没启动 |
| 资源指标 | 真实 CPU/内存 | ❌ 配置指向 Prometheus 却回退 Mock，返回假数据 |
| 证据可信度 | 区分 real / mock / LLM 推断 | ❌ 无标记，Mock 数据混入结论 |

---

## 3. 优化项

### P0-1 消除 Mock 假数据污染（最高优先，直接决定结论可信度）

**问题**：`MONITOR_BACKEND=prometheus` 且 `PROMETHEUS_URL=""` 时静默回退 Mock；
服务名未命中剧本又回退 `infra_cpu`，凭空生成"CPU 爬升到 96%"。

**改哪里 / 怎么做**
- `mcp_servers/monitor_server.py`（`query_cpu_metrics`:139 / `query_memory_metrics`:179）
  - 在工具返回里**显式带数据来源标记**，如 `data_source: "mock" | "prometheus" | "unavailable"`，
    并在返回文本首行加 `[数据来源: Mock演示数据，非真实监控]`。
  - 当 `MONITOR_BACKEND=prometheus` 且 `PROMETHEUS_URL` 为空时，**不要回退 Mock**，
    直接返回"监控数据不可用"。
- `src/settings.py`（`MONITOR_BACKEND`:165 附近）
  - 新增 `ALLOW_MOCK_FALLBACK: bool = False`（生产默认禁用 Mock 回退）。
- `src/agent/aiops/strategies/default.py`（`response_prompt`:58）
  - 增加一条硬约束：**被标记为 Mock/演示/不可用的数据，不得作为根因主证据，不得在报告中给出具体数值**。
- `src/agent/aiops/executor.py`（`_EXECUTOR_SYSTEM`:31）
  - 增加一条：工具返回若标注为演示/不可用数据，必须如实说明"该项未取得真实数据"。

**验收**：`MONITOR_BACKEND=prometheus, PROMETHEUS_URL=""` 时，指标步骤返回"不可用"，
最终报告**不得出现任何具体 CPU/内存数值**。

---

### P0-2 修复结构化输出"静默降级"

**问题**：thinking 模式模型不支持 `tool_choice`，`ainvoke_structured` 的策略 1（function_calling）
必然失败 → 走策略 2（正则抠 JSON）。replanner 要 `Act`（含 `action` 字段）却返回了
`{"response": "..."}`，`model_validate` 报 `action Field required` → 异常被吞 → 静默 `continue`，
**"要不要再规划"的判断根本没生效**（日志：`[replanner] 评估失败,继续原计划`）。

**改哪里 / 怎么做**
- `src/agent/aiops/structured.py`
  - 策略 2 增加**校验失败重试**：`model_validate` 失败时，把报错信息回喂给模型再要一次
    （最多 1 次），并把 schema 字段以"必须出现"的措辞写进重试提示。
  - 增加"字段名纠偏"：若返回对象含 `response` 但目标 schema 是 `Act`，说明模型串了 schema，
    应触发重试而非直接抛错。
- 配置层（`.env` / `src/settings.py`）
  - `AGENT_MODEL` 从 thinking 模式模型切到**支持 function_calling** 的（如
    `glm-5.3` / `qwen3.7-flash-2026-07-15` / `deepseek-v4.1-flash`），让策略 1 生效。
- `src/agent/aiops/strategies/default.py`（`decide`:179）
  - 结构化失败不再静默 `return {}`：改为记录并**发出 `type=degraded` 事件**，让前端/用户可见。

**验收**：日志中不再出现 `[replanner] 评估失败,继续原计划`；replanner 稳定输出
`continue / replan / respond`。

---

### P0-3 新增"业务层健康探针"（核心新能力）

**问题**：`check_website` 只探页面（HTTP 层），"页面好、服务坏"看不见。

**改哪里 / 怎么做**
- 在 `mcp_servers/monitor_server.py` 新增工具（或新建 `mcp_servers/service_server.py`）：
  - `check_service_health(base_url, health_path="/health", timeout_s=10)`：
    探 `/health` `/healthz` `/ready`，返回 `status / latency_ms / body 摘要 / data_source`。
  - `check_api_endpoint(url, method="GET", payload=None, timeout_s=10)`：
    探具体业务接口，返回 `http_status / latency_ms / body 摘要`，用于识别 **5xx / 超时 / 业务错误码**。
  - 关键点：把"页面 200"与"业务接口 5xx/超时"**分开表达**，让证据能落到业务层。
- `src/agent/aiops/planner.py`（`planner_prompt`:185，现有"网址/网站健康检查"分支）
  - 增加分支：**若用户描述为"页面能打开，但某功能报错/任务一直不返回"**，
    则规划为"检查业务接口 / 任务状态"，而不是只做页面检查。

**验收**：对案例 C，能报出"页面 200，但审校接口/任务状态异常"，而不是"网站正常"。

---

### P1-1 把日志服务（cls 8103）纳入常规运行

**问题**：`cls` 默认没启动，后台日志/任务堆积这些**最关键的证据拿不到**；
报告只能写"日志没查成"。

**改哪里 / 怎么做**
- 启动脚本（`start_demo.bat` 等）确保 `monitor_server.py` + `cls_server.py` 一起拉起。
- 在 `src/agent/mcp_client.py` 的逐服务降级基础上，增加**启动自检**：
  诊断开始前探测 8103/8104/8105，未启动的明确告警（或在开发环境自动拉起）。
- `CLS_BACKEND` 接真实 ES（`CLS_ES_URL`），日志才是真实证据。

**验收**：诊断时 `search_log` 可用，报告不再出现"日志没查成"。

---

### P1-2 新增"任务 / 队列状态"观测

**问题**：对"任务卡住不返回"这类故障，没有任何工具能直接看到任务状态。

**改哪里 / 怎么做**
- 新增工具（放 `service_server.py` 或 `monitor_server.py`）：
  - `query_task_status(service_name, task_id=None)`：查后台任务表/状态（pending/running/failed）。
  - `query_queue_depth(service_name)`：查队列积压量。
- 这是唯一能直接看见"任务卡在哪一步"的证据，对案例 C 这类场景是刚需。

**验收**：能给出"任务处于 running 但长时间无进展 / 队列积压 N 条"这类直接证据。

---

### P1-3 "不可达"分层判定

**问题**：超时 vs 拒绝分不清，跨网段只能给"可能被拦截"。

**改哪里 / 怎么做**
- `mcp_servers/site_probe.py`（`probe_website`；原 `monitor_server.py` 内的同名实现已迁出）
  - 返回增加 `failure_layer` 字段：`dns / tcp / tls / http`，并在 `tcp` 层区分
    `refused`（端口无监听）/ `timeout`（不可达或被 DROP）/ `unreachable`。
  - 报告措辞改为"从诊断机看，目标在 X 层不可达"，而不是含糊的"可能被拦截"。
- 新增 `check_local_port(host, port)`：在**目标主机上**执行才有意义，用于把"服务未启动"钉死。
  若 Agent 不部署在目标机，需通过被诊断机上的 agent/采集器落地。

**验收**：跨网段场景报告写明"网络层不可达，**无法判断**服务是否启动"，不臆断。

---

### P2-1 动态分类 / 矛盾触发默认开启（论文核心机制）

**问题**：`ENABLE_DYNAMIC_CLASSIFICATION=false`（`src/settings.py`:135），
"矛盾触发与假设保护"这条核心机制**默认没启用**。
案例 B 中"连接超时（服务没起）"与"资源耗尽（Mock）"本是互斥证据，却未被识别为矛盾并触发再规划。

**改哪里 / 怎么做**
- 默认值改为 `True`，并补齐回归测试。
- 确认 `strategies/dynamic_classification.py` 的证据冲突检测能覆盖"服务不可达 vs 资源告警"这一对。

**验收**：构造互斥证据时，能观察到旁开式再规划发生。

---

### P2-2 证据可信度分级

**问题**：Mock 数据、LLM 推断、真实数据在 state 里没有区分，混在一起定根因。

**改哪里 / 怎么做**
- 在 `PlanExecuteState` 的每条证据上增加 `source`（`real / mock / llm_inferred`）与 `confidence`。
- 报告生成时按可信度排序，`mock / llm_inferred` **不得作为根因主证据**（只能作为"待验证线索"）。

**验收**：报告中根因结论的每条支撑证据都标注了来源与可信度。

---

## 4. 建议落地顺序

1. **P0-1 + P0-2**（先止损）：关掉假数据、修好 replanner。这两项不修，后面所有结论都不可信。
2. **P0-3**（补核心能力）：业务层探针，这是"页面好、服务坏"能不能被识别的分水岭。
3. **P1-1 + P1-2**（补证据链）：日志 + 任务状态，让根因有真实证据支撑。
4. **P1-3**（补语义）：不可达分层，避免"臆断"。
5. **P2-1 + P2-2**（补机制）：把论文核心机制真正启用并做证据分级。

---

## 5. 验收用例（改完必须复跑）

| 用例 | 输入 | 期望结论 |
|---|---|---|
| U1 本机服务未启动 | `http://127.0.0.1:<未监听端口>/` | 明确报"服务未启动（端口无监听）" |
| U2 跨网段不可达 | `http://192.168.3.251:19001/document` | 报"网络层不可达，**无法判断**服务是否启动"，**不得**出现 CPU/内存数值 |
| U3 页面好、服务坏 | `https://deeppub.keyanjia.com/document` + "重新审校 20 分钟未返回" | 报"页面正常，但业务接口/任务异常"，**不得**把根因归到资源耗尽 |
| U4 健康站点 | 任一正常公网页面 | 报"网站正常"，不编造故障 |

---

## 6. 风险与注意事项

- **不要用"关掉 Mock"作为唯一手段**：真实 Prometheus 未接入时，应明确返回"数据不可用"，
  而不是换个方式继续猜。
- **业务层探针要注意鉴权**：`check_api_endpoint` 若需登录态，需支持传 token/cookie，
  否则只会拿到 401/302，反而制造新噪声。
- **跨网段场景要区分"诊断机视角"与"目标机视角"**：从诊断机看到不可达，不等于服务本身有问题。
- **P0-2 换模型前先确认免费额度**：遵守项目既有纪律（只用有免费额度的模型，额度耗尽即重新探测）。
- **每个 P0 项都要配一个回归用例**，避免改完只在 demo 上好看。

---

## 7. 落地进展(2026-10-10 本轮已实现)

### 7.1 新增交付物

| 文件 | 作用 |
|---|---|
| `mcp_servers/site_probe.py` | **真实探测引擎**(纯标准库): 页面级/端口级/接口级探测 + 网络错误分层。判定口径单一事实来源 |
| `scripts/probe_site.py` | **命令行探测工具**: 人和脚本直接可用,支持页面/端口/健康/接口四种探测,`--json` 机器可读 |
| `tests/test_site_probe.py` | 探测引擎单测(本地回环构造,离线可复跑): 12 条用例全绿 |

`monitor_server.py` 已重构为**薄封装**: 四个 MCP 探测工具只做协议包装,实现全部委托给
`site_probe.py`,与命令行工具共用同一套逻辑(避免"Agent 看到的"与"人看到的"不一致)。

### 7.2 P0-1 消除 Mock 假数据污染 —— 已完成

- 指标工具返回体统一新增 `data_source`(`prometheus` / `mock` / `unavailable`)与
  `data_source_note`;Mock 路径首行标注"[数据来源: Mock演示数据(非真实监控)…]"。
- 新增 `settings.ALLOW_MOCK_FALLBACK`(默认 `False`): `MONITOR_BACKEND=prometheus`
  但 URL 未配置/不可达时,**默认不回退 Mock**,直接返回 `unavailable`。
- 提示词层加硬约束: `executor._EXECUTOR_SYSTEM` 第 9 条 + `default.py response_prompt`
  "数据可信度(硬约束)" —— Mock/不可用数据不得作为根因主证据、不得引用具体数值。
- **实测验收**: 本机 `PROMETHEUS_URL=http://127.0.0.1:19090`(不可达)下,
  `query_cpu_metrics` 返回 `data_source=unavailable`、`data_points=[]`,不再编造 CPU 曲线。

### 7.3 P0-3 业务层健康探针 —— 已完成

- 三个真实探测工具落地: `check_ports`(端口监听)、`check_service_health`(健康端点)、
  `check_api_endpoint`(业务接口),把探测能力从"页面级"下沉到"端口/服务/接口级"。
- `site_probe.classify_network_error` 统一网络错误分层(`dns`/`tcp`/`tls`),严格区分
  **连接被拒绝(端口无监听→服务未启动)** 与 **连接超时(网络层不可达,不能据此判断服务状态)**。
- `planner` 提示词新增两条主诊断路径: "页面能打开但功能/任务异常"、"服务未启动/端口不通"。
- **实测验收**(本地故障靶场 `tools/faulty_demo_site.py`):
  首页 HTTP 200 判"网站正常",同时深度检查报出 `/logo.png` 404、`/api/orders/500` 500、
  `/api/orders/slow` 4.2s,业务接口探测报"后台服务在运行但处理失败" —— 即"页面好、服务坏"被真实识别。

### 7.4 本轮环境踩坑(已写入代码注释与测试)

- **Windows 本地关闭端口的"拒绝"回包延迟约 2s**(安全软件/防火墙拦截所致),
  不是瞬时拒绝。端口探测超时因此**不得低于 4s**,否则会把"未启动"误判成"超时"。
  已把 `check_ports` 超时提到 4s,CLI 端口探测夹到 `[4s, 6s]`,并在单测中注明。

### 7.5 尚未完成(后续)

- **P0-2** 结构化输出静默降级(需配合切到支持 function_calling 的免费模型);
- **P1-1** 日志服务(cls 8103)纳入常规运行 + 接真实 ES;
- **P1-2** 任务/队列状态观测(`query_task_status` / `query_queue_depth`);
- **P1-3** 不可达分层在**报告层**的措辞落地;
- **P2-1 / P2-2** 动态分类默认开启、证据可信度分级。

---

## 8. 端到端实测(2026-10-10):"假根因"问题与日志侧修复

### 8.1 实测方法

用 `tools/faulty_demo_site.py`(首页 200,埋 404/慢4.2s/500/403 四类故障)作靶场,
`scripts/run_demo_diagnosis.py` 跑真实端到端诊断(经 FastAPI SSE,真实 LLM)。

### 8.2 关键发现:检测是真的,但"根因"曾是假的

**修复前**(问"页面能打开但订单功能报错,找根因"),Agent 报告:

> 订单功能报错的根本原因已找到——**订单服务内存被撑爆**,进程被系统反复强制关闭……
> 日志显示它的处理线程反复报"内存空间不足"……系统已自动保存了故障时的内存快照

**这段话是编的。** 靶场根本没有 OOM,也没有任何真实日志;这段内容是把
`mock_scenario.py` 里 `order-service` 的 **Mock 演示日志**
(`OutOfMemoryError` / `Dumping heap to …heapdump.hprof` / `-XX:OnOutOfMemoryError=kill -9`)
当成真实证据转述出来的。

**危害等级高于"没找到根因"**:它给出了一个自信、专业、且完全错误的结论,外行无法分辨。

**根因**:`cls_server`(日志服务)缺了与 `monitor_server` 相同的数据来源标记 ——
ES 不可达时静默回退 Mock,且返回体不带 `data_source`,Agent 无从判断真假。

### 8.3 修复(与指标侧同一纪律,非新增功能)

- `cls_server.py`:新增 `_MOCK_LOG_NOTE` / `_unavailable_logs` / `_try_real_logs`;
  所有日志返回体带 `data_source`(`elasticsearch` / `mock` / `unavailable`);
  ES 已配置但不可达时**默认不回退 Mock**(复用 `settings.ALLOW_MOCK_FALLBACK`)。
- `cls_client.py`:真实 ES 成功返回标 `elasticsearch`,查询失败标 `unavailable`。
- 提示词:`executor` 第 9 条、`default.py response_prompt` 把数据诚实性约束
  从"指标"推广到"日志",**明确点名不得把 Mock 日志里的异常堆栈当真实根因**。

### 8.4 修复后复测(同一问法)

Agent 报告变为:

> ❌ 订单功能确实在报错,而且关键的后台日志这次没查到,所以"为什么会报错"暂时还判断不了……
> **需要特别注意:日志这一项是"未取得真实数据",不是"查了没问题"。**
> 现有的确凿证据只有两条:页面层正常、订单接口报 500……本次**不给根本原因下结论**,避免误导。

**这是正确行为**:证据不足时诚实停在"无法定论",而不是编造。

### 8.5 四层探测确已真实调用(日志实证)

末轮 `logs/demo_monitor.log` 记录的工具调用序列:
`check_website`×2(页面级)、`check_api_endpoint`×7(接口级)、
`check_service_health`×1(服务级)、`check_ports`×1(端口级)——四层全用上。

### 8.6 模型工具调用能力实测(决定"能否真用工具")

- **原生 `bind_tools` 可用** ✅:返回正确的 `tool_calls`(如 `check_ports(host=127.0.0.1, ports=8080)`)。
- **`with_structured_output(method="function_calling")` 报 400** ❌:
  `Thinking mode does not support this tool_choice` —— 即 P0-2 的根因。
  影响 planner/replanner 的结构化输出,会走 regex 降级路径。

### 8.7 结论

| 能力 | 状态 |
|---|---|
| 真实检测(页面/端口/服务/接口四层) | ✅ 可用,实测四层均被真实调用 |
| 诚实性(证据不足时不下结论) | ✅ 修复后达成 |
| 真实根因定位 | ⚠️ **取决于真实证据源**:Prometheus/ES 未接入时,系统诚实停在"无法定论"——这是对的,但也说明**接入真实数据源才有真根因** |
| 结构化输出(planner/replanner) | ⚠️ 走 regex 降级(P0-2 待修) |

---

## 附：本次实测留存的证据

- 案例 B 执行日志：`runtime/_verify_doc_out.log`
- 案例 C 执行日志：`runtime/_verify_deeppub_out.log`
- 关键代码位置：
  - `mcp_servers/monitor_server.py`：`check_website`、`check_ports`、`check_service_health`、`check_api_endpoint`(薄封装)
  - `mcp_servers/site_probe.py`：`probe_website` / `classify_network_error` / `tcp_connect` / `probe_http_api` / `deep_check`(探测引擎)
  - `mcp_servers/mock_scenario.py`：`scenario_for_service`:135（默认回退 `infra_cpu`）、`_METRIC_SHAPES`:43
  - `src/agent/aiops/structured.py`：`ainvoke_structured`:33（策略 1/2 降级）
  - `src/agent/aiops/strategies/default.py`：`decide`:179、`response_prompt`:58
  - `src/agent/aiops/planner.py`：`planner_prompt`:185（"网址/网站健康检查"分支）
  - `src/settings.py`：`MONITOR_BACKEND`:165、`CLS_BACKEND`:194、`ENABLE_DYNAMIC_CLASSIFICATION`:135