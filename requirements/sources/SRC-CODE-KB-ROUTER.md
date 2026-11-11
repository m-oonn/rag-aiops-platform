# SRC-CODE-KB-ROUTER

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-KB-ROUTER` |
| 类型 | `code`（源码） |
| 位置 | `src/api/routers/knowledge_base.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:25:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `b6b9649aee6557affbcebee156ebf9264ee098962c9fcb758bc62abb3ac29baa` |
| 字节数 | 28233 |

## 3. 摘要

知识库与文档全生命周期 20 个端点：建/列/查/改/删库，上传（扩展名+MIME+魔数+50MB 校验，落盘 data/raw 并镜像 MinIO 但失败不阻断），派发（bm25→进程内 BackgroundTasks，否则 Celery 带 5 秒硬超时回落），重试/批量重试/批量删/重处理，生成 QA 对并 CRUD/下载，chunks 查看与预览。

## 4. 登记的符号

```
create_knowledge_base
upload_document
_dispatch_document
_try_celery_delay
_verify_file_signature
sanitize_filename
retry_document
batch_retry_documents
generate_qa_for_document
get_document_chunks
reprocess_document
preview_document
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/kb-ingest.md`

## 6. 反向引用（12 份资料、177 处提及）

- `cases/kb-ingest.json`：L46, L47, L48, L49, L97, L98, L136, L137, L184, L185, L225, L226 …共 28 处
- `cases/rag-qa.json`：L317
- `cases/storage-queue.json`：L394
- `requirements/_conventions.md`：L97
- `requirements/index.json`：L767, L769, L770, L771, L772, L775, L778, L780, L781, L803, L804, L805 …共 40 处
- `requirements/modules/kb-ingest.md`：L67, L70, L71, L72, L75, L79, L81, L85, L93, L99, L100, L101 …共 40 处
- `requirements/modules/storage-queue.md`：L120, L161, L162, L163, L170, L231, L232, L240, L286, L287
- `requirements/overview.md`：L100, L203
- `specs/feature-index.json`：L487, L510, L536, L610, L631, L655, L678, L700, L1796
- `specs/modules/kb-ingest.md`：L18, L19, L20, L21, L22, L24, L25, L26, L27, L28, L30, L31 …共 40 处
- `specs/modules/storage-queue.md`：L58, L150, L195, L312
- `specs/questions.md`：L23

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

