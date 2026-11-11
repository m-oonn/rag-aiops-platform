# SRC-ENV-LIVE-STATE

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-ENV-LIVE-STATE` |
| 类型 | `environment_state`（运行态事实（不可读）） |
| 位置 | `Milvus(19530) / RabbitMQ / Redis / Elasticsearch / Celery worker 在线状态` |
| 可用状态 | `blocked` |
| 采集时间 | `—` |
| 依据等级 | `unresolved` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `未计算` |

## 3. 摘要

**不可读原因**：本任务禁止网络调用与外起服务；无法在不触发外部依赖的前提下核实运行态。

**对资料的影响**：所有依赖在线状态的产品行为条目只能标 observed(代码路径) 而不能标 confirmed(实测)；相关断言 readiness 降为 draft。

## 4. 当前材料路径（本来源支撑的资料正文）

- `—`

## 5. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

