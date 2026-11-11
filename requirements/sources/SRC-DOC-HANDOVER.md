# SRC-DOC-HANDOVER

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-HANDOVER` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/aiops-goal-handover-20261108.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `confirmed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `92d13ebb59880076370325e258bfcd907f9b92e2e241d00be43844534862994d` |
| 字节数 | 21696 |
| 行数 | 294 |

## 3. 摘要

唯一权威现状文档：036–050 共 15 轮真实付费诊断、10 通过/5 未通过（3 次判定缺陷已修、2 次模型侧失误不修）、五项'别宣称'、三处系统缺陷的修法与教训、零成本回放门禁入口、真实一轮执行流程、以及'修复后可稳定复现不成立'的分阶段口径。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`

## 5. 反向引用（8 份资料、68 处提及）

- `cases/aiops-diagnosis.json`：L134, L138, L225, L706
- `requirements/index.json`：L1461, L1483, L1592, L1615, L1629, L1649, L1676, L1678, L1679, L1680, L1681, L1683 …共 27 处
- `requirements/modules/aiops-audit.md`：L111, L171, L192, L356
- `requirements/modules/aiops-diagnosis.md`：L10, L172, L308, L344, L369, L370, L371, L373, L375, L377, L379, L472 …共 18 处
- `requirements/overview.md`：L28, L31, L54
- `requirements/project-card.md`：L33, L75, L97, L103, L205
- `specs/modules/aiops-diagnosis.md`：L7, L198, L251, L252
- `specs/questions.md`：L37, L155, L159

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

