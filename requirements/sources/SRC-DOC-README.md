# SRC-DOC-README

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-README` |
| 类型 | `doc`（项目文档） |
| 位置 | `README.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 可信度 | partial_outdated |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `aa2547df020b0c116c91f8f4e7898c723adf5754685de093dc46f1c9ff098b37` |
| 字节数 | 10776 |

## 3. 摘要

产品自述与技术栈。经与源码交叉核实，至少三处过期：端口写 8000（实为 8200）、'上传即自动触发 Celery'（bm25 库走进程内）、测试矩阵写 '98 集成/PostgreSQL'（实为 SQLite）。作为来源保留但结论不采信，冲突登记于 specs/questions.md。

## 4. 当前材料路径（本来源支撑的资料正文）

- `specs/questions.md Q-01..Q-03`

## 5. 反向引用（8 份资料、25 处提及）

- `cases/platform.json`：L207
- `requirements/_conventions.md`：L121
- `requirements/index.json`：L343
- `requirements/modules/platform.md`：L181, L183, L300
- `requirements/overview.md`：L228, L229, L230, L231, L232, L233, L234
- `requirements/project-card.md`：L22, L101, L139, L203, L263
- `specs/modules/platform.md`：L106, L107
- `specs/questions.md`：L10, L17, L23, L36, L147

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

