# 资料撰写约定（内部规范，先读这一份再动笔）

本目录资料按 `C:\Users\Administrator\Downloads\通用-项目理解与测试资料维护提示词.txt` 生成。
基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（分支 `main`）。
**所有 `file:line` 锚点必须带完整相对路径**（例：`src/api/routers/aiops.py:123-129`），不允许只写文件名。

---

## 1. 模块划分（唯一权威，不得新增/改名）

| module_id | 中文名 | 需求前缀 | 负责文件 |
|---|---|---|---|
| `platform` | 平台启动/配置/安全/CI | `PLAT` | requirements/modules/platform.md、specs/modules/platform.md、cases/platform.json |
| `auth-console` | 鉴权与前端控制台 | `AUTH` | 同名三件套 |
| `kb-ingest` | 知识库与文档摄取 | `KB` | 同名三件套 |
| `rag-qa` | 检索与问答 | `RAG` | 同名三件套 |
| `aiops-diagnosis` | AIOps 诊断链路 | `DIAG` | 同名三件套 |
| `aiops-audit` | 运行记录/证据/审计/探针 | `AUDIT` | 同名三件套 |
| `evaluation` | 评测 | `EVAL` | 同名三件套 |
| `assistant-agent` | 助手与 Agent 配置 | `AGENT` | 同名三件套 |
| `storage-queue` | 对象存储与队列监控 | `STORE` | 同名三件套 |

## 2. 稳定 ID 规则

- 需求：`REQ-<PFX>-###`，三位数字，按模块内从 `001` 开始，**只增不改号**。废弃不删除，标 `decision_status: retired` + `supersedes`。
- 功能：`FEAT-<PFX>-###`。
- 规则：`RULE-<PFX>-###`（写在 `specs/modules/<module>.md`）。
- 断言：`ASRT-<PFX>-###`（写在 `specs/modules/<module>.md`，被用例 `assertion_id` 引用）。
- 用例：`CASE-<PFX>-###`（写在 `cases/<module>.json`）。
- 流程：`FLOW-<PFX>`，本资料固定为：
  - `FLOW-PLAT`（启动与请求进入）
  - `FLOW-AUTH`（注册登录与每次请求鉴权）
  - `FLOW-KB-INGEST`（上传→解析→切分→向量化→就绪）
  - `FLOW-RAG-QUERY`（提问→意图路由→检索→rerank→生成→溯源）
  - `FLOW-DIAG`（诊断提交→图执行→SSE→报告）
  - `FLOW-DIAG-RESUME`（终态挂起→审批校验→续跑）
  - `FLOW-AUDIT`（运行记录/证据读取/步快照）
  - `FLOW-EVAL`（建任务→数据集→执行→报告）
  - `FLOW-ASSIST-EXEC`（助手/Agent 配置→执行）
  - `FLOW-STORE`（文件列举/下载/预览/上传）

## 3. basis 语义（严格按模板）

- `confirmed`：**明确的产品决定**，且有文档/注释写明理由与适用条件。代码能看到但没写成决定的**不算** confirmed。
- `observed`：直接读源码核实的实现事实。允许 `readiness: ready`，但只能记录 `OBSERVED`，**不证明设计正确**。
- `unresolved`：缺依据、口径冲突、或只能推断。`readiness` 必须 `draft`，并在正文标 `SPEC_GAP`。
- `proposed`：AI 建议，**不得**自动升为 confirmed，不得写成"已决定"。

一个需求里若代码事实与文档声明冲突：**需求本身按文档/决定写（confirmable），把代码事实写进"实现状态"，把冲突单列到 `specs/questions.md`**。

## 4. 角色与 execution_kind

角色：`functional` / `core-flow` / `performance` / `experience` / `product-details`。
按"断言目的"分配，**不要为每个需求机械复制五份**；一个需求通常 1–2 个角色。

`execution_kind`：
- `live_ui`：从已部署的 Web 控制台可点触发的路径。
- `live_api`：直接请求后端 HTTP 端点（含普通校验错误）。
- `live_cli`：命令行/脚本入口（如 `pytest`、`scripts/*.py`）。
- `static_review`：只读源码/配置/文档即可完成的核对。
- `controlled_fixture`：**只有**需要响应模拟、故障注入、特殊预置（如 Mock 后端制造 503、注入 endpoint mismatch、伪造过期审批）才用它。

## 5. readiness / evaluation_mode

- `readiness` 只表示**资料完整度**：`ready` = 来源/步骤/预期/评价方式/执行条件都写清；`draft` = 仍有缺口；`retired` = 废弃。
- `evaluation_mode`：
  - `binary`：条件明确的规则，判定 PASS/FAIL。**正式 PASS/FAIL 还须 basis=confirmed 且适用条件成立**；observed 的 binary 断言只能记 OBSERVED。
  - `graded`：效果目标（如诊断准确率），必须说明 达到/接近/部分达到/明显偏离/无法判断 的判据，且**不得编造阈值**。
  - `measurement`：只报数值（单位/样本/条件），不设通过线。
- 等待超时是**运行预算**，不是性能 SLA，不要写成性能阈值。
- 共享用例**不保存执行结果**、不写 `runtime_ready`、不写"本机禁用"结论。

## 6. 用例 JSON 字段（缺一不可，空值用 null 或 []）

```json
{
  "case_id": "CASE-KB-001",
  "assertion_id": "ASRT-KB-001",
  "feature_id": "FEAT-KB-001",
  "role": "functional",
  "basis": "observed",
  "readiness": "ready",
  "requirement_refs": ["REQ-KB-001"],
  "rule_refs": [],
  "flow_refs": ["FLOW-KB-INGEST"],
  "applicability": "适用条件一句话；不适用时写清在哪不适用",
  "preconditions": ["..."],
  "steps": ["1. …", "2. …"],
  "expected": ["可判定的预期结果，一条一条"],
  "evaluation_mode": "binary",
  "comparison_dimensions": [],
  "evidence": ["需要留下的证据：响应码/字段/日志/文件/表行/doc_id…"],
  "execution_kind": "live_api",
  "required_actions": [],
  "required_capabilities": [],
  "resource_requirements": [],
  "resource_refs": ["src/api/routers/knowledge_base.py:311-411"],
  "dependencies": [],
  "timeout_seconds": 30,
  "readonly_retry_max": 0,
  "cleanup": "无副作用时写 'none'；有副作用写清回滚动作"
}
```

`cases/<module>.json` 顶层：
```json
{
  "module_id": "kb-ingest",
  "baseline_commit": "bf789d9e4fff51b7a2c0b661046f9e5c72b6e483",
  "generated_at": "2026-11-11T09:40:00+08:00",
  "cases": [ ... ]
}
```

## 7. 禁止事项（会被退回）

- 无来源却标 `confirmed`。
- 把维护指令/提示词要求当成本项目需求。
- 空用例（steps 或 expected 为空）。
- 虚构资源：不存在的端点、表、字段、脚本、环境变量、文件路径一律不得出现；不确定就标 `unresolved` 并写"未核实"。
- 用 `README.md` 的过期口径当事实（端口 8000、5173、"上传自动 Celery"、"RAGAS 评测"、"MinIO 版本管理"、"Recall 维度" 均已核实与代码不符）。
- 在资料里写任何密钥/Token/密码/Cookie 明文，或复制 `.env` 内容。
- 声称运行过测试/服务/模型（本次全程只读静态核实，`model_calls: 0`、`network_calls: 0`）。

## 8. 写作风格

- 简体中文，短句，先结论后证据。
- 每条事实后面直接跟锚点，不集中堆在段尾。
- 区分"已实现"（代码能走通）、"已启用"（默认开关打开）、"已验证"（有真实运行证据）三态——这是本项目最容易混淆的地方，必须逐条写清。
- 文档里出现的每个 `REQ-*`/`FEAT-*`/`RULE-*`/`ASRT-*`/`CASE-*` 都必须能被 `requirements/index.json` 或 `specs/feature-index.json` 解析到。
