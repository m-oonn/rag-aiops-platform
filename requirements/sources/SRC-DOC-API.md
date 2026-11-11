# SRC-DOC-API

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-API` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/api.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 可信度 | incomplete |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `d7827e88d73b6fc21b3b3b49676b5422651dc4baad5cc2e27d04c8e34645b83f` |
| 字节数 | 1537 |
| 行数 | 71 |

## 3. 摘要

接口文档，仅覆盖 auth/knowledge-bases/chat/evaluations 四组；缺 aiops/agents/monitor/storage/health/upload 六组，且 evaluations 只写了 2 个端点（实际 10 个）。资料以源码为准，本文件只作冲突证据。

## 4. 当前材料路径（本来源支撑的资料正文）

- `specs/questions.md Q-04`

## 5. 反向引用（3 份资料、8 处提及）

- `requirements/overview.md`：L42
- `requirements/project-card.md`：L87, L204, L264
- `specs/questions.md`：L28, L29, L31, L264

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

