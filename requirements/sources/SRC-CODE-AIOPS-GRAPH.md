# SRC-CODE-AIOPS-GRAPH

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-AIOPS-GRAPH` |
| 类型 | `code`（源码） |
| 位置 | `src/agent/aiops/graph.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:23:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `3de029a1abe547df12c21a71d028d4a035be5c23cfa52af0fa80c4403240fab2` |
| 字节数 | 30880 |

## 3. 摘要

Plan-Execute-Replan 图装配与运行服务：5 节点、HITL 时插入 human_review、terminal 时插入 terminal_review；按 replanner 边界分段 astream 续跑；默认 MemorySaver 内存 checkpointer，managed_run 才落 SQLite 持久 checkpointer。

## 4. 登记的符号

```
AIOpsService
NODE_PLANNER
NODE_EXECUTOR
NODE_REPLANNER
NODE_HUMAN_REVIEW
NODE_TERMINAL_REVIEW
_diagnostic_extras
_snapshot_payload
_thread_runs
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`

## 6. 反向引用（10 份资料、134 处提及）

- `cases/aiops-audit.json`：L37, L38, L45, L83, L84, L91, L210
- `cases/aiops-diagnosis.json`：L38, L39, L128, L138, L393, L394, L401, L438, L439, L446, L529, L575
- `requirements/index.json`：L1476, L1480, L1485, L1509, L1517, L1539, L1540, L1541, L1542, L1543, L1544, L1545 …共 40 处
- `requirements/modules/aiops-audit.md`：L105, L106, L107, L113, L126, L127, L130, L131, L151, L157, L167, L175
- `requirements/modules/aiops-diagnosis.md`：L9, L66, L67, L107, L154, L161, L174, L202, L212, L216, L230, L231 …共 40 处
- `requirements/overview.md`：L101, L203
- `specs/feature-index.json`：L1089, L1139, L1220, L1321
- `specs/modules/aiops-audit.md`：L38, L72, L76, L88, L109
- `specs/modules/aiops-diagnosis.md`：L41, L66, L68, L79, L93, L135, L142, L191, L212
- `specs/questions.md`：L99, L200, L207

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

