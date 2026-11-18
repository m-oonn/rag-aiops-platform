# SRC-DOC-TOOL-AVAILABILITY-20261111

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-TOOL-AVAILABILITY-20261111` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/tool-availability-control-20261111.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T20:38:21+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `b0278e4db8e2727c9f5bf1c008fc224172a0e0dcf7446659e07abc69d9332a23` |
| 字节数 | 8238 |
| 行数 | 81 |

## 3. 摘要

规划参考资料与知识检索工具可用/停用两场对照：均 confirmed_cause，但知识 MCP 调用均为 0；complete 事件含 evidence_source_availability，报告未显式列出缺席知识源。每格两场，不支持工具有效/无效结论。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`

## 5. 反向引用（3 份资料、3 处提及）

- `cases/aiops-diagnosis.json`：L793
- `specs/modules/aiops-diagnosis.md`：L221
- `specs/questions.md`：L255

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```
