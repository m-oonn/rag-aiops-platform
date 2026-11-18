# SRC-DOC-UI-REVIEW-FIXES-20261111

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T21:01:35+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-UI-REVIEW-FIXES-20261111` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/ui-review-fixes-20261111.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T21:00:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `737f17d4d1e975a640e0e3472b9e052646a0ce1c` |
| 正文 SHA-256 | `57a2a6b56130f655ffbe9789037009dfab5166d644c5e8e6a8bf7e82673937ae` |
| 字节数 | 4647 |
| 行数 | 67 |

## 3. 摘要

记录 AIOps 在 Probe 不可用时的提示与知情确认交互、依赖探测失败时的处理，以及真实浏览器截图和相关回归结果；作为实现/验证材料，不视为独立产品决定。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`
- `cases/aiops-diagnosis.json`
- `specs/questions.md Q-42`

## 5. 反向引用（5 份资料、6 处提及）

- `cases/aiops-diagnosis.json`：L838
- `requirements/index.json`：L1919
- `requirements/modules/aiops-diagnosis.md`：L584, L590
- `specs/modules/aiops-diagnosis.md`：L235
- `specs/questions.md`：L269

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```
