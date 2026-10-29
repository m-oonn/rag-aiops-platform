# GitHub 仓库同步核查报告

- **受检仓库**：`git@github.com:m-oonn/rag-aiops-platform.git`（public）
- **核查时间**：2026-09-27
- **核查目的**：确认「毕设创新线」是否已正确并入项目主线并反映到 GitHub
- **核查方式**：`git ls-remote` 远程分支实测 + 独立工作树快照导入实测 + 已提交/未提交文件逐项比对

---

## 一、核查结论（先行）

> **不是"合并"没做，而是"提交"没做完。**

1. **毕设创新线的核心代码确实已在 GitHub 上** ✅ —— `src/agent/aiops/core/*`、`src/agent/aiops/strategies/*`（含 `dynamic_classification.py`）、`docs/architecture.md`、`docs/history/修复工作总结报告.md` 均已入库。
2. **但进入方式是"线性上传"，不是分支合并** ⚠️ —— GitHub 上**只有 `main` 一个分支，且无任何 merge commit**；两条线在仓库视图里是一条直线，没有可审计的合并动作。
3. **GitHub 上的 `main` 处于「开箱即坏」状态** 🔴 —— 已提交代码引用了**未提交**的模块，实测 4/4 关键模块导入失败。**任何人 clone 后都跑不起来。**
4. **本地仍有 23 个已修改文件 + 29 个未跟踪文件未提交**，其中包含造成上述断链的全部缺失模块。

**一句话**：工作区是完整可跑的，GitHub 是残缺不可跑的。差的是一次"补齐式"提交与推送。

---

## 二、分支与远程状态

### 2.1 远程实际分支（`git ls-remote --heads origin`）

```
45db7820a56a8e615ef838b5bf6b293b1dbd4e80   refs/heads/main
```

**远程只有 `main`。** 没有 `thesis-dynamic-classification`，也没有文档中声称的 `thesis-dynamic-classification-v2`。

### 2.2 本地与远程一致性

| 检查项 | 结果 |
|---|---|
| 本地 `main` vs `origin/main` | ahead **0** / behind **0** —— **无任何未推送的提交** |
| `git log --merges` | **空** —— main 历史上**没有任何合并提交** |
| `thesis-dynamic-classification` 位置 | `bb1eba8`（2026-06-26），**是 main 的祖先** |
| thesis 有而 main 没有的提交 | **0 个** |
| main 有而 thesis 没有的提交 | **49 个** |
| `thesis-dynamic-classification` 是否为 main 祖先 | **是**（已被包含） |
| 该分支是否推送过 | **否**（无 upstream 跟踪） |

**解读**：`thesis-dynamic-classification` 停留在 2026-06-26，此后 main 上又累积了 49 个提交。也就是说——**两线从未真正分叉**，创新线内容是沿 main 的线性历史进入的。该本地分支已是一枚**过时僵尸分支**（落后 49 个提交且从未上云）。

### 2.3 main 的提交形态

2026-09-23 当天集中出现约 49 个提交，全部形如：

```
45db782 docs: 上传修复工作总结报告
65a934f docs: 上传项目完成度存档
16630b2 docs: 上传架构总览与论文章节提纲
916c8b8 feat: 上传全链路脚本与 Apache-2.0 LICENSE
8f5421b feat: 上传项目根文件(README/requirements/.env.example/.gitignore)
...
b7bb849 feat: 上传 AIOps executor 执行器(ReAct+并行观测+历史压缩)
```

这是**"按文件分批灌入仓库"**的操作痕迹，而非合并。**漏灌的文件就成了断链源头。**

---

## 三、关键发现：GitHub 上的 main 无法运行（实测证据）

### 3.1 实测方法

为排除本地工作区干扰，从 `main` 快照创建**独立 git 工作树**，在其中实际执行模块导入：

```bash
git worktree add /tmp/gitcheck/main main --detach
cd /tmp/gitcheck/main
python -c "import src.agent.aiops.executor, mcp_servers.monitor_server, ..."
```

### 3.2 实测结果

| 模块 | GitHub `main` 快照 | 本地工作区 |
|---|---|---|
| `src.utils.metrics.AIOPS_PARALLEL_BATCHES` | ❌ **不存在** | ✅ 存在 |
| `src.agent.aiops.executor` | ❌ `ImportError: cannot import name 'AIOPS_PARALLEL_BATCHES'` | ✅ OK |
| `src.agent.aiops.planner` | ❌ 同上 `ImportError` | ✅ OK |
| `mcp_servers.monitor_server` | ❌ `ModuleNotFoundError: No module named 'mcp_servers.prometheus_client'` | ✅ OK |
| `mcp_servers.cls_server` | ❌ `ModuleNotFoundError: No module named 'mcp_servers.cls_client'` | ✅ OK |
| `src.main`（FastAPI app） | ❌ `ImportError: cannot import name 'AIOPS_PARALLEL_BATCHES'` | ✅ OK |

**GitHub 侧 4/4 关键模块导入失败；本地工作区 5/5 通过。** 断链是确定的、可复现的。

### 3.3 四处硬性断点

| # | 已提交文件 | 引用的未提交依赖 | 后果 |
|---|---|---|---|
| 1 | `src/agent/aiops/executor.py` L29 `from src.utils.metrics import AIOPS_PARALLEL_BATCHES, ...` | `src/utils/metrics.py` 缺该指标定义（已提交版本 `grep -c` = **0**） | L4 并行观测整条链路不可用 |
| 2 | `mcp_servers/monitor_server.py` L34 `from mcp_servers.prometheus_client import ...` | `mcp_servers/prometheus_client.py` **未跟踪** | 监控 MCP 服务无法启动 |
| 3 | `mcp_servers/cls_server.py` L35 `from mcp_servers.cls_client import ClsClient, use_es_backend` | `mcp_servers/cls_client.py` **未跟踪** | 日志 MCP 服务无法启动 |
| 4 | `src/main.py` L9 模块级 `from prometheus_fastapi_instrumentator import Instrumentator` | 本地已改为 `try/except` 可选降级，**未提交** | 未装该包时整个 FastAPI 应用起不来 |

> 另：`src/settings.py`（已提交版本）**不含** `PROMETHEUS_USERNAME` / `PROMETHEUS_PASSWORD` / `PROMETHEUS_BEARER_TOKEN` / `PROMETHEUS_VERIFY_SSL` 及 ES 鉴权字段，而新增的 `prometheus_client.py` / `cls_client.py` 会消费它们。

---

## 四、本地未提交清单（按处置建议分类）

### A 类 · 必须提交（否则 GitHub 仓库持续不可用）

**新增文件（未跟踪）**

| 文件 | 作用 |
|---|---|
| `mcp_servers/prometheus_client.py` | 监控 MCP 的 Prometheus 真实后端 |
| `mcp_servers/cls_client.py` | 日志 MCP 的 Elasticsearch 真实后端 |
| `mcp_servers/service_map.py` | 服务名别名归一化（口头名 ↔ 监控前缀 ↔ 索引前缀） |
| `docker/docker-compose.observability.yml` | 观测栈编排 |
| `docker/prometheus/` | Prometheus 配置 |
| `scripts/discover_prometheus_metrics.py` | Prometheus 指标/标签自动发现 |
| `scripts/seed_es_demo_logs.py` | ES 演示日志灌入 |
| `scripts/verify_mcp_e2e.py` | MCP 端到端验证 |
| `scripts/probes/probe_all_models.py` 等 5 个探测脚本 | 模型可用性探测 |
| `tests/test_metadata_extractor.py`、`test_reranker.py`、`test_vector_retriever.py` | 补齐的单测 |

**已修改文件（23 个，327 增 / 107 删）**

- 断链修复核心：`src/utils/metrics.py`、`src/settings.py`、`src/main.py`
- 后端：`src/api/routers/{chat,assistant,evaluation,health}.py`、`src/worker/tasks.py`
- 配置：`.env.example`（+52 行）
- 前端：`frontend/src/App.vue`、`views/{Agent,Assistant,Chat}.vue` 及 2 个 `.test.js`
- 脚本：`scripts/{probe_llm,probe_more_models,run_ragas_eval}.py`
- 测试：`tests/{test_agent_config_schema,test_aiops_auth,test_aiops_graph,test_assistant_functional,test_intent_router}.py`

### B 类 · 建议提交（论文线，需你确认）

| 文件 | 说明 |
|---|---|
| `docs/thesis/引言.md` | 论文第 1 章正文（当前**未跟踪**，即论文正文未上云） |
| `docs/thesis/毕设评审报告.md` | 本次评审产出（可选） |

### C 类 · 绝对不能提交 🔴

**仓库是 public，以下内容一旦推送即公开：**

| 文件 | 风险 |
|---|---|
| `岗位梳理_创峰数智_AI应用开发实习生.md`（369 KB） | **求职隐私** |
| `电话沟通准备_创峰数智_AI应用开发实习生.md` | **求职隐私** |
| `线下面试准备_妙笔生花.md` | **求职隐私** |
| `面试完整解析_妙笔生花.md` | **求职隐私** |
| `面试感谢消息.md` | **求职隐私** |
| `面试要点_精简版.md` | **求职隐私** |
| `rag_system.db-shm` / `-wal` / `.bak-20260926121951` / `.bak2-20260926122225` | 数据库运行时副产物 |
| `reports/probe_*.txt`、`reports/_probe_speech.wav` | 探测产物，无版本价值 |

### D 类 · `.gitignore` 缺口

当前 `.gitignore` 只写了 `*.db`，**无法匹配**以下实际存在的文件：

```gitignore
*.db-shm
*.db-wal
*.db.bak*
reports/
```

**这是当前最紧迫的隐患**：若执行 `git add -A`，WAL/SHM 与探测产物会被一并提交到公开仓库。

---

## 五、根因分析

| 层次 | 根因 |
|---|---|
| 直接原因 | 2026-09-23 采用"按文件分批上传"的方式同步仓库，**新增文件（`mcp_servers/*_client.py`、`service_map.py`、docker observability）与增量修改（`metrics.py`、`settings.py`、`main.py`）被遗漏** |
| 结构性原因 | 缺乏"提交后验证"环节——若上传后执行一次导入自检或 `pytest`，断链会立刻暴露 |
| 流程原因 | 两条线在同一工作区并行，没有通过分支隔离，导致"哪些文件属于哪条线"依赖人工记忆，遗漏难以发现 |
| 分支原因 | `thesis-dynamic-classification` 从未推送，且很快落后于 main，后来被直接以线性提交方式覆盖，合并历史不可追溯 |

---

## 六、修复方案

### 步骤 0 · 先补 `.gitignore`（防误提交，必须最先做）

```bash
cat >> .gitignore <<'EOF'
*.db-shm
*.db-wal
*.db.bak*
reports/
EOF
```

### 步骤 1 · 校验忽略生效

```bash
git check-ignore -v rag_system.db-wal reports/probe_all_models_result.txt
```

### 步骤 2 · 精确暂存（禁止使用 `git add -A`）

```bash
# A 类：断链修复 + 生产化改造（逐项显式添加）
git add src/utils/metrics.py src/settings.py src/main.py \
        src/api/routers/chat.py src/api/routers/assistant.py \
        src/api/routers/evaluation.py src/api/routers/health.py \
        src/worker/tasks.py .env.example \
        mcp_servers/prometheus_client.py mcp_servers/cls_client.py mcp_servers/service_map.py \
        docker/docker-compose.observability.yml docker/prometheus \
        scripts/discover_prometheus_metrics.py scripts/seed_es_demo_logs.py scripts/verify_mcp_e2e.py \
        scripts/probes/probe_all_models.py scripts/probes/probe_nonchat_models.py scripts/probes/probe_real_backends.py \
        scripts/probes/probe_realtime_models.py scripts/probes/probe_livetranslate_params.py \
        frontend/src/App.vue frontend/src/views/Agent.vue frontend/src/views/Assistant.vue \
        frontend/src/views/Chat.vue frontend/src/views/Agent.test.js frontend/src/views/Assistant.test.js \
        tests/test_metadata_extractor.py tests/test_reranker.py tests/test_vector_retriever.py \
        tests/test_agent_config_schema.py tests/test_aiops_auth.py tests/test_aiops_graph.py \
        tests/test_assistant_functional.py tests/test_intent_router.py

# B 类：论文线（按需）
git add docs/thesis/引言.md

# 暂存后必须复核，确认无 C 类文件混入
git diff --cached --name-only
```

### 步骤 3 · 提交前自检（关键，上次就是漏了这步）

```bash
# 3.1 断链回归：四个模块必须全部 OK
python -c "
for mod in ['src.utils.metrics','src.agent.aiops.executor','src.agent.aiops.planner','mcp_servers.monitor_server','mcp_servers.cls_server']:
    __import__(mod); print('OK', mod)
"
# 3.2 单测回归
pytest tests/test_dynamic_classification.py tests/test_intent_router.py -q
```

### 步骤 4 · 提交并推送

```bash
git commit -m "fix: 补齐 MCP 生产化依赖模块，修复 main 断链

- 新增 prometheus_client / cls_client / service_map，修复 monitor/cls MCP 服务无法启动
- metrics.py 补 AIOPS_PARALLEL_BATCHES，修复 executor/planner 导入失败
- main.py 将 prometheus 依赖改为可选降级
- settings.py 补 Prometheus/ES 鉴权与 TLS 配置
- 补观测栈编排、探测脚本与单测"

git push origin main
```

### 步骤 5 · 收尾分支

```bash
# 方案一：删除僵尸分支（推荐，两线已线性合一，无历史价值）
git branch -d thesis-dynamic-classification

# 方案二：若要保留"双线"可追溯性，需在推送后补一份《双线合并说明》
# 并修正 architecture.md 中不存在的分支名 thesis-dynamic-classification-v2
```

---

## 七、风险提示

1. 🔴 **`git add -A` / `git add .` 是本次最大的操作风险**——会把 6 份求职材料推送到 **public** 仓库，且 Git 历史一旦写入便无法彻底撤回（需 rewrite history + force push，代价高）。**必须逐项显式添加。**
2. 🟡 `reports/_probe_speech.wav` 等二进制探测产物入库会永久增大仓库体积。
3. 🟡 推送前建议先 `git push --dry-run origin main` 预演。
4. 🟢 本次为**纯新增与补齐**，无删除、无重写历史，**不需要 `--force`**，符合 git-safe 原则。

---

## 八、核查证据索引（可复现命令）

```bash
# 1. 远程分支实况
git ls-remote --heads origin

# 2. 本地/远程一致性 + 无合并提交
git rev-list --count origin/main..main          # 期望 0
git log --merges --oneline                      # 期望空

# 3. thesis 分支关系
git merge-base --is-ancestor thesis-dynamic-classification main && echo 已并入
git rev-list --count main..thesis-dynamic-classification   # 期望 0

# 4. 断链核验（已提交 vs 未提交）
git show main:src/utils/metrics.py | grep -c AIOPS_PARALLEL_BATCHES        # 期望 0
git show main:src/agent/aiops/executor.py | grep AIOPS_PARALLEL_BATCHES    # 有引用
git show main:mcp_servers/monitor_server.py | grep prometheus_client       # 有引用

# 5. 快照导入实测
git worktree add /tmp/gitcheck/main main --detach
cd /tmp/gitcheck/main && python -c "import src.main"   # 期望 ImportError
git worktree remove /tmp/gitcheck/main --force

# 6. 未提交清单
git status --porcelain
```

---

*报告结束 · 2026-09-27*
