# SRC-DOC-FAULT-PAIR-20261110

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-FAULT-PAIR-20261110` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/fault-pair-preexperiment-result-20261110.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T20:38:21+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `fe228024cd2e7433b2d90509596ec38306c7b9b0a11cd1e9639280b4a2c10f52` |
| 字节数 | 23532 |
| 行数 | 146 |

## 3. 摘要

八场两类故障四组对照的人工语义审核：诊断定位、引用支持、建议适用性各维度均 8/8 达到人工判定标准；作者自审，非自动正确性验证，不支持统计外推，机械 capability_passed 未改写。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`

## 5. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```
