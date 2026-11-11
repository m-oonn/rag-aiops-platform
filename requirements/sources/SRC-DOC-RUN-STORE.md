# SRC-DOC-RUN-STORE

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-RUN-STORE` |
| 类型 | `doc`（项目文档） |
| 位置 | `docs/aiops-run-store.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `confirmed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `4e7c9dab6e4d065de4e2eda02d9cedafe19259468d9997396a8bf5df9d68707f` |
| 字节数 | 2895 |

## 3. 摘要

三张表（aiops_runs/aiops_approvals/aiops_step_snapshots）语义与状态机、写操作 best-effort、/steps 端点鉴权与 thread_id 白名单；明确未做断线续传与从第 k 步重放。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-audit.md`

## 5. 反向引用（10 份资料、40 处提及）

- `cases/aiops-audit.json`：L91, L221, L432, L463, L469, L477
- `cases/aiops-diagnosis.json`：L446
- `requirements/index.json`：L1481, L1787, L1904, L1998, L2051, L2195, L2228, L2246
- `requirements/modules/aiops-audit.md`：L133, L139, L175, L275, L282, L334, L356
- `requirements/modules/aiops-diagnosis.md`：L162, L470, L474, L613
- `requirements/project-card.md`：L54, L207
- `specs/feature-index.json`：L1368
- `specs/modules/aiops-audit.md`：L78, L190, L193, L204, L207, L228, L238
- `specs/modules/aiops-diagnosis.md`：L142, L248
- `specs/questions.md`：L206, L207

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

