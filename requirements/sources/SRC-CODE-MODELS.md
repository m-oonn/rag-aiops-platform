# SRC-CODE-MODELS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-MODELS` |
| 类型 | `code`（源码） |
| 位置 | `src/database/models.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:26:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `d1f3f7d2b4c8fe1b2e7a7e2def49f3be020ccb89eb6f7c5b5519848d35e80e86` |
| 字节数 | 17174 |

## 3. 摘要

20 个 ORM 模型（对应 24 张实际表含关联/索引），覆盖身份、知识库链路、会话、评测、助手/Agent、诊断运行与审批、步级快照、探针目标与快照、证据账本。

## 4. 登记的符号

```
User
KnowledgeBase
KnowledgeDocument
DocumentChunk
GeneratedQAPair
ChatSession
ChatInteraction
EvaluationTask
EvaluationResult
EvaluationDatasetItem
Assistant
AssistantVersion
Agent
AgentExecutionLog
AiopsRun
AiopsApproval
AiopsStepSnapshot
ProbeTarget
ProbeSnapshot
AiopsEvidence
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/overview.md §对象模型`

## 6. 反向引用（22 份资料、123 处提及）

- `cases/aiops-audit.json`：L423, L431, L461, L476, L483
- `cases/assistant-agent.json`：L274
- `cases/kb-ingest.json`：L682
- `cases/rag-qa.json`：L529
- `requirements/index.json`：L261, L279, L459, L490, L647, L732, L779, L931, L933, L1090, L1114, L1329 …共 39 处
- `requirements/modules/aiops-audit.md`：L133, L139, L208, L214, L253, L259, L271, L276, L282, L292, L301, L335 …共 15 处
- `requirements/modules/aiops-diagnosis.md`：L109, L612, L644
- `requirements/modules/assistant-agent.md`：L72, L76, L86, L126, L135, L139, L195, L212
- `requirements/modules/auth-console.md`：L94, L105, L109, L221, L233, L342
- `requirements/modules/evaluation.md`：L193, L205, L321, L339, L387
- `requirements/modules/kb-ingest.md`：L81, L186, L302, L352
- `requirements/modules/platform.md`：L110, L112, L301, L315
- `requirements/modules/rag-qa.md`：L227, L235, L350
- `requirements/overview.md`：L51, L53, L91, L92
- `requirements/project-card.md`：L45, L187
- `specs/modules/aiops-audit.md`：L179, L193, L199, L200, L227, L228, L239, L240
- `specs/modules/assistant-agent.md`：L134, L188
- `specs/modules/auth-console.md`：L231
- `specs/modules/evaluation.md`：L52, L53, L54, L232, L246
- `specs/modules/kb-ingest.md`：L52, L251
- `specs/modules/rag-qa.md`：L200
- `specs/questions.md`：L117, L225, L231

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

