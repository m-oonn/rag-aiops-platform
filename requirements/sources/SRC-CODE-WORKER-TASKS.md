# SRC-CODE-WORKER-TASKS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-WORKER-TASKS` |
| 类型 | `code`（源码） |
| 位置 | `src/worker/tasks.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:35:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `7deb3372777de7e60e71b05cb9b0f44020e679dbdf37369992d2cb7ca9ef65ae` |
| 字节数 | 10148 |

## 3. 摘要

process_document_task 只是薄封装，真正逻辑是纯函数 process_document(doc_id, progress)，因此 Celery 与进程内 BackgroundTasks 共用同一实现；bm25 模式短路不调 embedding；失败置 status=3 且不 re-raise。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/kb-ingest.md`

## 5. 反向引用（11 份资料、87 处提及）

- `cases/kb-ingest.json`：L420, L442, L486, L538
- `cases/rag-qa.json`：L351, L367, L368, L418, L472
- `requirements/index.json`：L774, L850, L864, L880, L882, L885, L887, L889, L890, L894, L915, L919 …共 28 处
- `requirements/modules/kb-ingest.md`：L73, L136, L152, L155, L157, L160, L162, L164, L166, L174, L176, L177 …共 23 处
- `requirements/modules/rag-qa.md`：L146, L190, L329
- `requirements/overview.md`：L203
- `requirements/project-card.md`：L48, L177
- `specs/feature-index.json`：L560, L585, L609
- `specs/modules/kb-ingest.md`：L44, L45, L46, L47, L48, L61, L62, L63, L137, L144, L151, L158 …共 15 处
- `specs/modules/rag-qa.md`：L172
- `specs/questions.md`：L45, L192

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

