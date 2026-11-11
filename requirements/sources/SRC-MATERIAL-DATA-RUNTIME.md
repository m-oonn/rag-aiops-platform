# SRC-MATERIAL-DATA-RUNTIME

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-MATERIAL-DATA-RUNTIME` |
| 类型 | `runtime_material`（运行素材（只读）） |
| 位置 | `data/ ; runtime/` |
| 可用状态 | `available_readonly` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `—` |
| 正文 SHA-256 | `未计算` |

## 3. 摘要

data/ 内含 aiops-evidence、runbooks、reports、vectors（vectors.npy 71.8MB + vectors_meta.json 20.3MB + .1536.bak）、raw、processed、termcp 及 pytest-* 目录；runtime/ 内是按轮次/实验命名的目录（windows-local-faults-*、wrong-endpoint-*、fault-pair-*、aiops-goal-036..050 等），已 gitignore。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/project-card.md §2.3`

## 5. 登记备注

只读不改；data/ 不得当缓存删除；runtime/ 保留失败记录。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

