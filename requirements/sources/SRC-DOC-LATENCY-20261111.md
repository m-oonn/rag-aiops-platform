# SRC-DOC-LATENCY-20261111

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-LATENCY-20261111` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/latency-fault-20261111.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T20:38:21+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `253f192536a030fcdf3420ecaf1e641e943a6aba2243ce9e1eed664d6c7f9d8e` |
| 字节数 | 11206 |
| 行数 | 119 |

## 3. 摘要

downstream_slow 受控夹具与两场真实运行：慢响应连接已建立、receive_headers 超时、两场 localized_fault；未提供直接原因码，缺少可判定的依赖响应超时谓词，重复日志受既有守卫阻止。结果层与夹具条件可核；不代表统计结论或人工诊断正确性。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`

## 5. 反向引用（3 份资料、4 处提及）

- `cases/aiops-diagnosis.json`：L750
- `specs/modules/aiops-diagnosis.md`：L70, L228
- `specs/questions.md`：L261

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```
