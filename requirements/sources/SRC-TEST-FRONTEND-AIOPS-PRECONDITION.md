# SRC-TEST-FRONTEND-AIOPS-PRECONDITION

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-TEST-FRONTEND-AIOPS-PRECONDITION` |
| 类型 | `test`（测试资产） |
| 位置 | `frontend/src/views/AIOps.evidencePrecondition.test.js` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T21:00:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `be8b3a8f8cf19e445cfd6efde73770bb98a4a9aa66e6921e3344a1138274e181` |
| 字节数 | 3625 |
| 行数 | 99 |

## 3. 摘要

四条前端组件测试分别覆盖 Probe 不可用时提示和确认门槛、所有现场工具不可用时强化提示、Probe 可用时不提示、依赖探测失败不误报；本轮未运行测试。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`

## 5. 反向引用（4 份资料、6 处提及）

- `cases/aiops-diagnosis.json`：L839, L845
- `requirements/index.json`：L1918
- `requirements/modules/aiops-diagnosis.md`：L584, L590
- `specs/modules/aiops-diagnosis.md`：L235

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```
