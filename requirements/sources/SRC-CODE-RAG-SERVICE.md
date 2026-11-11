# SRC-CODE-RAG-SERVICE

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-RAG-SERVICE` |
| 类型 | `code`（源码） |
| 位置 | `src/services/rag_service.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:25:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `bd23b9dac4e692199ae03214e03aaba91c87aa4e78d3a4b3e7bdf800f1202cf1` |
| 字节数 | 15025 |

## 3. 摘要

问答编排核心：规则意图快过滤→LLM 意图分类→按 (intent, 有无KB, 有无Agent) 矩阵分派三条路径；RAG 路径内含 rerank、多跳（受 MAX_HOP 约束）与'引用段落编号'的强约束 prompt；检索质量以结构化日志输出。

## 4. 登记的符号

```
RAGService.query
_quick_intent_check
_assess_retrieval_quality
_general_chat
_rag_path
_agent_path
_single_hop_query
_multi_hop_query
_format_response
_format_context
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/rag-qa.md`

## 6. 反向引用（11 份资料、140 处提及）

- `cases/assistant-agent.json`：L308, L329, L330, L382, L435, L573, L595, L602
- `cases/rag-qa.json`：L178, L179, L180, L181, L212, L229, L230, L231, L232, L365, L366, L369 …共 18 处
- `requirements/index.json`：L1166, L1167, L1168, L1171, L1172, L1173, L1174, L1198, L1210, L1243, L1245, L1265 …共 40 处
- `requirements/modules/assistant-agent.md`：L97, L104, L111, L112, L119, L167, L171, L174, L190, L193, L196, L208 …共 13 处
- `requirements/modules/evaluation.md`：L370, L386
- `requirements/modules/rag-qa.md`：L103, L104, L105, L108, L120, L124, L137, L152, L170, L178, L186, L188 …共 24 处
- `requirements/overview.md`：L27, L203
- `specs/feature-index.json`：L751, L820, L845, L867, L1622, L1694
- `specs/modules/assistant-agent.md`：L50, L53, L143, L161, L170, L296, L305
- `specs/modules/rag-qa.md`：L35, L52, L55, L56, L57, L91, L116, L158, L165, L172, L186, L193 …共 17 处
- `specs/questions.md`：L45, L51, L57

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

