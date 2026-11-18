# SRC-CODE-FRONTEND-AIOPS-VIEW

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-FRONTEND-AIOPS-VIEW` |
| 类型 | `code`（源码） |
| 位置 | `frontend/src/views/AIOps.vue` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T21:00:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `e9ba6010055d48a336da3b8ae6e52390ffbc176ef712c90722f3ec086394c370` |
| 字节数 | 52367 |

## 3. 摘要

AIOps 页面承载诊断提交、SSE 事件消费、进度与报告展示；新增依赖现场证据状态提示及知情确认门槛，依赖请求失败时保持沉默。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`

## 5. 关联来源

- `{'location': 'frontend/src/views/AIOps.test.js', 'bytes': 26214}`
- `{'location': 'frontend/src/views/AIOps.matching503.test.js', 'bytes': 5120}`
- `{'location': 'frontend/src/views/AIOps.evidencePrecondition.test.js', 'bytes': 3625}`
- `{'location': 'frontend/src/views/__fixtures__/matching503-api-20261024.json', 'bytes': 337182}`

## 6. 反向引用（9 份资料、73 处提及）

- `cases/aiops-diagnosis.json`：L217, L218, L219, L225, L845
- `requirements/index.json`：L1478, L1480, L1516, L1517, L1581, L1757, L1819, L1827, L1859, L1860, L1861, L1892 …共 21 处
- `requirements/modules/aiops-audit.md`：L190, L208, L255, L274, L278, L355
- `requirements/modules/aiops-diagnosis.md`：L157, L161, L174, L208, L210, L216, L271, L440, L497, L505, L545, L553 …共 18 处
- `requirements/project-card.md`：L30
- `specs/feature-index.json`：L963, L1214, L1241
- `specs/modules/aiops-audit.md`：L18, L19, L20, L21, L22, L25, L71, L241
- `specs/modules/aiops-diagnosis.md`：L18, L19, L20, L21, L22, L23, L61, L71, L235, L276
- `specs/questions.md`：L219

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

