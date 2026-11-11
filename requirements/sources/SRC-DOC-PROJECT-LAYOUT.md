# SRC-DOC-PROJECT-LAYOUT

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-PROJECT-LAYOUT` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/project-layout.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `confirmed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `—` |
| 正文 SHA-256 | `未计算` |

## 3. 摘要

目录与数据保护约定：根目录只放工程入口/依赖/规则；data/ 为有效实验依据不得当缓存删；runtime/ 用独立子目录并保留失败；.env 与 rag_system.db 原位保留、不提交、不打印凭据。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/project-card.md §4 D8`

## 5. 反向引用（1 份资料、5 处提及）

- `requirements/project-card.md`：L102, L139, L145, L202, L256

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

