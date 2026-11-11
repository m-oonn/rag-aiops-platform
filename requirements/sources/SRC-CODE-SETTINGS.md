# SRC-CODE-SETTINGS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-SETTINGS` |
| 类型 | `code`（源码） |
| 位置 | `src/settings.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:24:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `56c834f001510889fcdb585ef521f0c1fea7cb0c2d356b3582f6b2697f4b9d0e` |
| 字节数 | 21925 |

## 3. 摘要

113 项配置单一来源：LLM/Embedding/RAG/AIOps 能力开关/MCP 地址/双轨后端（mock|真实）。含两条纪律性注释：真实后端不可达不回退 Mock；NO_PROXY 追加本机回环以避代理劫持 MCP。

## 4. 登记的符号

```
Settings
settings
MCP_SERVERS
API_PREFIX
AIOPS_CHECKPOINT_DB_PATH
PROBE_EVIDENCE_DIR
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/platform.md`

## 6. 反向引用（31 份资料、180 处提及）

- `cases/aiops-audit.json`：L45, L85, L211, L393, L422, L430
- `cases/aiops-diagnosis.json`：L61, L82, L303, L313, L440, L474, L483, L583, L629, L664
- `cases/assistant-agent.json`：L349
- `cases/auth-console.json`：L257, L264
- `cases/evaluation.json`：L18
- `cases/kb-ingest.json`：L18, L70, L683
- `cases/platform.json`：L165, L171, L248, L254, L531
- `cases/rag-qa.json`：L273
- `cases/storage-queue.json`：L69
- `requirements/index.json`：L245, L267, L299, L300, L302, L303, L305, L306, L453, L524, L565, L731 …共 40 处
- `requirements/modules/aiops-audit.md`：L109, L113, L168, L175, L273, L282, L297, L301, L332, L357
- `requirements/modules/aiops-diagnosis.md`：L462, L464, L474, L495, L505, L549, L553, L607, L621, L643
- `requirements/modules/assistant-agent.md`：L64
- `requirements/modules/auth-console.md`：L121, L135, L159, L341
- `requirements/modules/evaluation.md`：L389
- `requirements/modules/kb-ingest.md`：L114, L175
- `requirements/modules/platform.md`：L82, L86, L94, L112, L120, L122, L124, L130, L134, L313
- `requirements/modules/rag-qa.md`：L152, L154, L158, L167, L178, L210, L218, L245, L253, L280, L332, L335 …共 13 处
- `requirements/modules/storage-queue.md`：L124, L170, L270
- `requirements/overview.md`：L98, L119, L123
- `requirements/project-card.md`：L22, L56, L59, L77, L96, L99, L112, L115, L121, L183, L184, L206
- `specs/feature-index.json`：L107
- `specs/modules/aiops-audit.md`：L88, L116, L227, L236
- `specs/modules/aiops-diagnosis.md`：L86, L135, L155, L156, L184, L231, L244, L253
- `specs/modules/assistant-agent.md`：L278
- `specs/modules/auth-console.md`：L105
- `specs/modules/evaluation.md`：L31
- `specs/modules/kb-ingest.md`：L37
- `specs/modules/platform.md`：L62, L170, L174, L176, L178, L182, L185, L186, L189, L192, L254
- `specs/modules/rag-qa.md`：L151, L193, L221, L235, L249

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

