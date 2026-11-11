# SRC-CODE-AIOPS-INVESTIGATION

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-AIOPS-INVESTIGATION` |
| 类型 | `code`（源码） |
| 位置 | `src/agent/aiops/strategies/investigation.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:33:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `624c089f0d5e910927872c9e47113bdd14f07de1ccca3a6ffc662bbcb8b9498b` |
| 字节数 | 279252 |
| 行数 | 3959 |

## 3. 摘要

全仓最大且最关键的判定文件（3959 行）。定义 outcome(3)/conclusion_level(4)/root_cause_code(4)/alternative.status(4)/claim_type(2) 枚举，承载结构化调查、候选校验、熔断降级与终态收敛。CI 有零成本回放门禁保护其判定逻辑不被改坏。

## 4. 登记的符号

```
InvestigationStrategy.decide
decide_from_evidence
outcome
conclusion_level
root_cause_code
Alternative.status
claim_type
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`
- `specs/modules/aiops-diagnosis.md`

## 6. 反向引用（4 份资料、26 处提及）

- `cases/aiops-diagnosis.json`：L686
- `requirements/index.json`：L1611, L1612, L1671, L1672, L1673, L1674, L1675, L1677, L1684, L1926
- `requirements/modules/aiops-diagnosis.md`：L128, L129, L130, L304, L310, L360, L361, L362, L363, L365, L370, L379 …共 13 处
- `specs/modules/aiops-diagnosis.md`：L195, L212

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

