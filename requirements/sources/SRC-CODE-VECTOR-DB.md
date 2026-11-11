# SRC-CODE-VECTOR-DB

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-VECTOR-DB` |
| 类型 | `code`（源码） |
| 位置 | `src/database/vector_db.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:35:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `b6402d9d5e1793249d1a68409cd1d531f963110b8ad441a1d05ca7079a45f4bd` |
| 字节数 | 9098 |

## 3. 摘要

Milvus 连接失败仅 warning 并置 _available=False；collection rag_documents_v2 / dim 1024 / IVF_FLAT+L2；写入双写（先本地 npy 再 Milvus），查询在不可用时回落 LocalVectorStore（单例+文件锁+mtime 跨进程重载）。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/rag-qa.md`

## 5. 关联来源

- `{'source_id': 'SRC-CODE-LOCAL-VECTORS', 'location': 'src/database/local_vector_store.py', 'content_sha256': '94669c16930d76aee174e459cff3729a380cb86c363d08bbd02a0cb1a5737431'}`

## 6. 反向引用（8 份资料、28 处提及）

- `cases/kb-ingest.json`：L681
- `requirements/index.json`：L924, L925, L928, L929, L932, L937, L1091, L1105, L1212, L1213, L1442
- `requirements/modules/kb-ingest.md`：L179, L184, L186, L190, L302, L336, L348
- `requirements/modules/rag-qa.md`：L154, L346
- `requirements/overview.md`：L99
- `requirements/project-card.md`：L60, L179
- `specs/feature-index.json`：L586
- `specs/modules/kb-ingest.md`：L62, L165, L251

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

