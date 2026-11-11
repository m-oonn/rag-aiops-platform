# changes/current.md — 资料维护变动记录（原位维护，不建日期副本）

> 本文件是资料工作区的**唯一增量维护入口**。每次修订只在此处追加一节并更新文末检查点，不生成 `requirements-20261111/`、`*.bak`、`*.old` 之类副本，也不保留旧版全文。
> 变更传播路径固定为：**文件/符号 → 模块 → 调用/协议/数据 → 入口/状态 → 规则/用例**。

---

## 2026-11-11 · 首次建立（基线 `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`）

### 本轮做了什么

按用户提供的《通用-项目理解与测试资料维护提示词》模板，从零建立本项目的可追溯资料工作区（`requirements/`、`specs/`、`cases/`、`changes/` 四个目录此前都不存在）。

**读源方式**：只读。直接阅读 `src/`、`frontend/src/`、`mcp_servers/`、`docker/`、`.github/workflows/`、`docs/`、`tests/`、`scripts/` 的源码与文档；**未运行任何测试、未启动任何服务、未发起任何模型调用或网络请求**（`model_calls: 0`、`network_calls: 0`）。

**产出规模**（全部实测，可被 `requirements/_validate.py` 复核）：

| 维度 | 数量 |
|---|---|
| 模块 | 9 |
| 需求 `REQ-*` | 88 |
| 功能单元 `FEAT-*` | 74 |
| 规则 `RULE-*` | 229 |
| 断言 `ASRT-*` | 226 |
| 用例 `CASE-*` | 121 |
| 来源登记 `SRC-*` | 27 条正常来源 + 2 条 `missing_or_blocked`（`SRC-ENV-LIVE-STATE` 出独立登记文件，`SRC-TPL-SHA` 仅为备注故不出文件）→ `requirements/sources/` 下 28 个 `SRC-*.md` + `index.json` |
| 冲突与缺口 `Q-*` | 39（open 14 / spec_gap 4 / resolved_in_docs 21） |
| 模块内「执行条件型未决」 | 88 条（不进 questions.md，按模块正文登记） |

**模块划分**：`platform`、`auth-console`、`kb-ingest`、`rag-qa`、`aiops-diagnosis`、`aiops-audit`、`evaluation`、`assistant-agent`、`storage-queue`。

### 依据分级结论（本轮最重要的口径）

- **全部 88 条需求的 `basis` 都是 `observed`**，没有一条 `confirmed`。原因：本项目的"明确产品决定"只存在于 `AGENTS.md` / `README.md` / `docs/aiops-goal-handover-20261108.md` 等文档里，而文档与代码存在**系统性偏差**（端口 8200 vs 8000、异步边界、测试口径、事件类型数量、run 状态数量……）。因此本轮一律按"从提交 `bf789d9` 的源码直接核实到的事实"记为 `observed`，文档另在 `Q-*` 与 `overview.md` 冲突表里登记。
- 少数规则被记为 `confirmed` 的，都是"文档明确声明 + 代码可验证一致"的项目纪律，例如：`SECRET_KEY` 强度校验、`NO_PROXY` 本机回环例外、后端端口 8200 避开 Windows 保留段、CI 用占位假密钥、判定规则回放门禁（`RULE-DIAG-018`）。
- **`aiops-audit` 模块无任何 `confirmed` 规则**，`specs/modules/aiops-audit.md` 文件头已声明该模块用例**不得用于判正式 PASS/FAIL**。

### 本轮的形状性判断（供后续维护者快速定位）

1. **代码是事实源，文档是意图源。** 见 `requirements/overview.md` 的冲突表（9 条）与 `specs/questions.md`。
2. **"已实现 / 已启用 / 已验证"三态必须分开读。** 例如：HITL 已实现但默认关闭且**无 HTTP 审批入口**；`/steps` 端点存在但 `ENABLE_STEP_SNAPSHOTS=False` 使 `total` 恒为 0；动态分类策略已实现但默认不生效；`ENABLE_SUPERVISOR` 只有两行注释、端点未实现。
3. **AIOps 链路的真实验收状态是"10/15 通过"，不是"稳定复现"。** 数字只按 `docs/aiops-goal-handover-20261108.md` 的四个分母写（含全部 15 轮 10/15、修复一后 7/11、修复二后 6/9、修复三后 0/1），并如实转述该文档的五项"别宣称"。
4. **一批"界面有、后端不认"的配置**：`assistant.rag_config`（Top-K / 重排序开关）全链路透传但 `RAGService.query` 从不读取；`chunking_config.method`/`separator` 前端可选但后端不消费；`RAG_MIN_SCORE`/`TOP_K`/`CHUNK_SIZE`/`LONG_TERM_MEMORY_COLLECTION` 四个 settings 字段在 `src/` 内零业务引用。
5. **一批"声称接通、实际未接"的能力**：`aiops_approvals` 表无写入方（`approved`/`rejected` 状态永不可达，见 Q-31）；`aiops_runs.degraded` 恒 NULL（Q-36）；长期记忆 `add_long_term_memory` 函数体只有 `pass`；`query.py` / `tasks.py` 两条路由未挂载（Q-19）；前端监控页下载/预览不带 `Authorization`（Q-09）。

### 本轮明确没做的事（避免误读为"已完成"）

- **没有运行任何产品用例**，所以所有用例的 `readiness` 只表示"资料完整度"，不代表可通过；`ready` 108 条 / `draft` 13 条。
- **没有核实任何外部依赖的在线状态**（Milvus / RabbitMQ / Redis / Elasticsearch / Celery worker / 各 MCP 服务 / MinIO），一律 `unresolved`，已登记为 `SRC-ENV-LIVE-STATE`（blocked）。
- **没有核实真实费用与账单**：`docs/aiops-goal-handover-20261108.md` 的 9.611526 元是"新增预留/峰值上界"而非账单，`cumulative_actual_cost` 在该文档里就是 `unknown`，资料不另作推算。
- **没有补 2 条高成本审计用例**（`ASRT-AUDIT-009` 探针新鲜度 180s、`ASRT-AUDIT-011` 转 stale 181s）：需要真实等待时钟推进，不放开配额，理由写在 `specs/modules/aiops-audit.md` §4 第 9 条与 `specs/catalog.json` 的 `remaining_scope`。
- **没有补 `FEAT-AUTH-009/010` 的用例**：属真实覆盖缺口，已在 catalog 的 `features_without_case`（13 个）里如实登记。

### 修改过的工作区外文件

一个也没有。所有写入都在 `requirements/`、`specs/`、`cases/`、`changes/` 与本文件所在目录内；`src/`、`frontend/`、`mcp_servers/`、`tests/`、`scripts/`、`docs/`、`docker/`、`data/`、`runtime/` 下的业务文件**零改动**。
辅助脚本只放在 `runtime/docs-tools/`：`build_indexes.py` 生成三个索引文件，另有 `check_questions.py` / `count_unresolved.py` / `show_timestamps.py` 三个纯统计核对脚本。唯一放在资料区内的可执行文件是 `requirements/_validate.py`（纯文档校验器，`--strict` 报错退出码 1）。`runtime/` 已在 `.gitignore` 内。

### 自检结果

```
python requirements\_validate.py --strict
→ JSON 文件: 13  用例总数: 121
  需求: 88  功能: 74  规则: 229  断言: 226
→ ERROR 0 —— 全部校验通过   (exit=0)
```

校验器覆盖的 9 类检查：目录与文件存在性、JSON 可解析、用例 24 个必需字段齐全、跨文件 ID 引用闭合（case → ASRT/rule/flow/requirement/feature、feature → requirement）、ID 全局唯一、空用例拒绝、`basis`/`role`/`readiness`/`execution_kind`/`evaluation_mode` 取值合法、源码锚点路径真实存在、凭据明文扫描、`catalog.json` 用例数与实际一致。

### 三态分布（`requirements/index.json` 实测，供交叉核对）

| 维度 | 是 | 否 | 未标注 |
|---|---|---|---|
| `implemented` 已实现 | 86 | 1 | 1（`REQ-KB-010`） |
| `enabled` 已启用 | 76 | 8 | 4 |
| `verified` 已验证 | **25** | 49 | 14 |

**`verified=是` 的 25 条全部只靠既有离线单测断言（原文写「已验证（部分）」），不代表本轮实测**；本轮 `model_calls: 0`、`network_calls: 0`、未启动任何服务。剩余 14 条 `verified=未标注` 是模块正文没写明确结论的叙述式条目（如 `REQ-KB-004`、`REQ-RAG-005`、`REQ-STORE-003`），保留"未标注"属如实登记、不是解析缺陷。

三态解析器 `runtime/docs-tools/build_indexes.py::parse_three_state` 必须同时支持三种写法（赋值式、顿号列表式、叙述式），且只在解析不出显式取值时才用"默认启用→是""unresolved/本轮未核实→否"兜底，不得覆盖已判定的值。


---

## 检查点（Checkpoint）

| 字段 | 值 |
|---|---|
| `last_observed` | `2026-11-11T10:02+08:00`，基线提交 `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`（`main`）。已读：`src/` 全量、`frontend/src/` 全量、`mcp_servers/`、`docker/`、`.github/workflows/`、`docs/` 顶层文档、`tests/` 目录清单、`scripts/` 目录清单。 |
| `pending_work` | ① `SRC-ENV-LIVE-STATE` 的在线状态核实（需授权联网 + 起服务，本轮明令禁止）；② `Q-*` 中 14 条 `open` 待产品决定，其中 Q-31（审批表无写入方）建议优先；③ 88 条模块内「执行条件型未决」需 controlled_fixture 或真实等待/付费授权；④ 13 个 `features_without_case` 待补用例；⑤ `docs/api.md` 覆盖面严重不足（Q-04），若上游补文档需回填 `specs/questions.md`。 |
| `last_published` | 资料建立那一轮未提交（零业务改动，仅工作区）。**2026-11-11 起业务改动开始进 Git**：问题 1/2/4 的修复与文档同步随本轮提交推送到 `origin/main`（提交号见 `git log` 顶部）。 |
| `pending_delivery` | 交付待确认项：① 是否需要把 `requirements/`、`specs/`、`cases/`、`changes/` 纳入版本控制（涉及 `.gitignore` 决策）；② 是否需要同步发布到外部文档系统（如飞书文档/知识库）；③ 是否需要按 `AGENTS.md` 的协作习惯在每日流水里登记本次资料建立。 |

---

## 后续增量维护约定（写给下一个维护者）

1. **只改原文，不加副本**。要修改某条需求，直接编辑 `requirements/modules/<module>.md` 里对应的 `REQ-*` 小节；不改号、不重排、不新建 `*-v2.md`。
2. **改完必须重跑两步**：
   ```bat
   python runtime\docs-tools\build_indexes.py
   python requirements\_validate.py --strict
   ```
   索引文件（`requirements/index.json`、`specs/feature-index.json`、`specs/catalog.json`）是**生成物**，不要手改；`generated_at` 已在脚本里改成真实运行时刻，不再是写死常量。
3. **新增断言必须带用例，或明确登记为缺口**。校验器不会因为"断言没被引用"报错（那是覆盖缺口不是错误），但必须在 `specs/catalog.json` 的模块 `remaining_scope` 或本文件里说清楚为什么没补。
4. **不要用正文里"提到编号"的位置充当定义**。`_validate.py` 的 ID 识别已收紧为"只认定义位置"（`RULE` 用 `^#{2,4}\s+RULE-…`、`ASRT` 用断言表格行 `| ASRT-… |`），因为 `ASRT-DIAG-015` 是**刻意跳号**留给 Q-17 待决口径的，正文里有它的说明文字。
5. **改 `src/` 之后**：本资料里的 `file:line` 锚点会失效。要么同步更新锚点，要么在 `changes/current.md` 记录"锚点基于旧提交"。本资料全部锚点以 `bf789d9` 为准，不写"main 分支当前"。
6. **涉及 AIOps 判定逻辑的改动**：先跑零成本回放门禁 `python -m pytest -q tests/test_recorded_round_replay.py`（见 `RULE-DIAG-018`），若曾通过的轮次回放失败，资料里的"10/15"口径与相关断言必须重估。


---

## 2026-11-11 业务代码改动记录（UI 复核问题 1 / 2 / 4）

本轮首次**修改业务源码**（此前 `changes/current.md` 声明"本轮零业务改动"仅对资料建立那一轮成立）。改动来源：真机点击复核发现的 7 个问题中，用户指定先修 1、2、4。

### 改了什么

| 问题 | 改动位置 | 说明 |
|---|---|---|
| 2 健康端点双前缀 | `src/api/routers/health.py` | `@router.get("/health")` → `@router.get("")`，实际路径由 `/api/v1/health/health` 变为 `/api/v1/health`；另加 `@router.get("/health", include_in_schema=False)` 兼容别名，旧路径不中断。 |
| 1 队列监控静默失败 | `src/api/routers/health.py` | `GET /queues` 改为三态：`ok`（含 `summary.workers`）/ `degraded`（中间件正常但无在线 Worker）/ `unavailable`（中间件不可达，附 `detail`）。先 `ping` 再 `inspect`，无 Worker 时响应从约 4.1 秒降到约 1 秒。 |
| 1 前端错误态 | `frontend/src/views/QueueMonitor.vue` | 按 `status` 分流展示 error / warning / 正常；新增第四张「在线 Worker」卡；错误附 `detail` 小字。 |
| 4 缺角色管理 | `src/settings.py`、`src/api/dependencies.py`、`src/api/routers/auth.py` | 新增 `ADMIN_USERNAMES` 引导配置与 `require_admin` 依赖；新增 `GET /auth/me`、`GET /auth/users`、`PATCH /auth/users/{id}/role`；`UserOut` 增加 `role`；登录时命中 `ADMIN_USERNAMES` 自动提权（幂等）。 |
| 4 前端入口 | `frontend/src/views/Users.vue`（新增）、`router/index.js`、`App.vue` | `/users` 页面，仅 `admin` 显示菜单项；禁止修改自己的角色，避免最后一个管理员被降级。 |
| 4 测试 | `tests/test_user_roles.py`（新增） | 覆盖 `/me` 含 role、非 admin 403、改他人角色生效、改自己 400、非法角色 422、不存在用户 404、`ADMIN_USERNAMES` 提权与幂等。 |
| 配置审计 | `.env.example` | 补 `ADMIN_USERNAMES=`，满足 `tests/test_configuration_audit.py` 的"字段全覆盖"约束。 |
| 文档 | `README.md`、`docs/api.md` | 更正访问端口（前端 5273 / 后端 8200，原写 5173 / 8000）、补健康端点与角色引导说明、补 4 个新端点。 |

### 对资料锚点的影响（重要）

本资料全部 `file:line` 锚点以提交 `bf789d9` 为准。本轮改动使下列文件的**行号发生偏移**，但符号名未变，锚点仍可按符号定位：

- `src/api/routers/health.py`：`health_check` 装饰器行号变化，新增 `_broker_error`、`health_check_legacy`。
- `src/api/routers/auth.py`：新增 `RoleName`、`RoleUpdate`、`get_me`、`list_users`、`update_user_role`，`UserOut` 增加 `role` 字段。
- `src/api/dependencies.py`：新增 `require_admin`。
- `src/settings.py`：新增 `ADMIN_USERNAMES` 与 `ADMIN_USERNAME_SET`。

`REQ-*` / `RULE-*` / `ASRT-*` 正文里若写死了上述文件的行号，需要按符号名重新核对；本轮**未**逐条回填行号（属于下一轮维护动作）。

### 实测结果（本轮）

- `GET /api/v1/health` 与 `/api/v1/health/health` 均 200。
- `GET /api/v1/health/queues` 三态全部真机验证：无 Worker → `degraded`；启动 Worker → `ok` 且 `summary.workers=1`；`docker stop rag_rabbitmq` → `unavailable`，恢复后回到 `degraded`。
- Chrome 真实点击：`admin` 登录后侧边栏出现「用户管理」→ 进入 `/users` → 把 `demo` 从 `user` 改为 `auditor` → 重新查询接口确认已持久化。
- `pytest -q`：2120 passed / 106 deselected / 0 failed（142.30s）；`frontend` vitest 18 文件 / 111 用例全部通过。

## 2026-11-11 AIOps 八场人工语义审核完成（资料口径更新）

这一轮不改业务代码，只完成 `docs/fault-pair-preexperiment-result-20261110.md` 里挂着的「八场人工三维语义审核 pending」，因此先前"诊断正确率 null"的表述有了可引用的人工判定结果。

| 项目 | 内容 |
|---|---|
| 审核工具 | `scripts/diagnostic_review.py` 的 `prepare` / `check`（只生成与校验本地审核包，不调用模型、不判定正确性） |
| 审核包 | `runtime/review-e2-b1b/s01-config-G00` … `s08-downstream-G00`（8/8 `prepare` 成功，0 模型调用、0 费用） |
| 审核人 / 日期 | 孙仲信 / 2026-11-11 |
| 回填与校验 | `runtime/docs-tools/fill_manual_review.py` 回填八份 `manual-review.json`；八场 `check` 全部 `review_status=recorded`、`pending_dimensions=[]` |
| 汇总档 | `runtime/review-e2-b1b/review-summary.json`、`runtime/review-e2-b1b/AI辅助研判汇总-20261111.md` |
| 结论 | `diagnosis` 8/8 `correct_localization`、`citation_support` 8/8 `supported`、`recommendation` 8/8 `appropriate` |
| 同步文档 | `docs/fault-pair-preexperiment-result-20261110.md` 新增「人工语义审核（2026-11-11 完成）」节，并把两处"待审"改成已完成 |

### 对资料锚点的影响

无。本轮没有改 `src/`、`frontend/`、`mcp_servers/`、`tests/`，`file:line` 锚点不受影响。新增的只有 `runtime/` 下的审核材料（`runtime/` 在 `.gitignore` 内，不进仓库）。

### 写作用词约束（第五章必须遵守）

- 可以说：**八场（2 类故障 × 4 组）经人工语义审核，故障层定位 8/8 正确、引用支持 8/8、处理建议 8/8 恰当**。
- 必须同时写：这是人工断言（`review_is_human_assertion=true`、`automatically_verified_correctness=false`）；8 场、每组 2 场**不支持统计外推**；配置错误四场与下游场 s05 停在 `localized_fault`（保守但正确）。
- 不得说：系统自动判对；正确率外推到其他故障类型；`capability_passed` 已通过（机械层仍是 `false`，未改写）。
- 已知缺陷照实写：s04 的 `ev-5481c983d34c467c893c055afef0e30c` 引用未通过绑定校验，事实成立但渲染句不是 payload 连续子串。
