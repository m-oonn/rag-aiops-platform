# SRC-CODE-RETRIEVAL

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-RETRIEVAL` |
| 类型 | `code`（源码） |
| 位置 | `src/retrieval/hybrid_retriever.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:35:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `03c2f69e876d7d4fbfc5ccf8824a72e20aecfbfdff99625740c286daabf794c3` |
| 字节数 | 8162 |

## 3. 摘要

BM25 与向量各取 top_k*2，RRF（常数 60）融合；BM25 用 2-gram 滑窗分词；索引进程内懒加载一次、不随新文档增量刷新；rerank 为真实在线模型调用，失败降级直接截断。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/rag-qa.md`

## 5. 关联来源

- `{'source_id': 'SRC-CODE-BM25', 'location': 'src/retrieval/bm25_retriever.py', 'content_sha256': '39d164894efde943544507b6f44c4e65a9bf978a619d4f3fc20e8bb4f67596d2'}`
- `{'source_id': 'SRC-CODE-RERANKER', 'location': 'src/retrieval/reranker.py', 'content_sha256': 'a9d236af1e0d7ec291f3f39b7147381ddbf0a9a946e5da88ec09c3c21323d9d8'}`

## 6. 反向引用（7 份资料、33 处提及）

- `cases/rag-qa.json`：L468, L469
- `requirements/index.json`：L1194, L1197, L1199, L1201, L1202, L1203, L1206, L1209, L1214, L1423, L1424, L1437
- `requirements/modules/rag-qa.md`：L132, L135, L139, L144, L145, L146, L148, L152, L158, L328, L345
- `requirements/overview.md`：L27
- `requirements/project-card.md`：L64
- `specs/feature-index.json`：L776
- `specs/modules/rag-qa.md`：L53, L123, L130, L137, L249

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

