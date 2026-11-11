# SRC-CODE-AIOPS-STATE

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-AIOPS-STATE` |
| 类型 | `code`（源码） |
| 位置 | `src/agent/aiops/state.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:24:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `df3ad7c7c5de4b65a7779b5b7deb2285156b7317cff3cd83105f2bd9e2333af7` |
| 字节数 | 3944 |

## 3. 摘要

PlanExecuteState 定义与 reducer 约束（past_steps/raw_evidence/evidence_events 用 operator.add；禁止 __future__ annotations 否则退化为覆盖）。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`

## 5. 反向引用（2 份资料、9 处提及）

- `requirements/index.json`：L1549, L1550, L1614, L1917
- `requirements/modules/aiops-diagnosis.md`：L242, L243, L249, L306, L632

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

