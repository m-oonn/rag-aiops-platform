# SRC-CODE-AIOPS-ROUTER

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-AIOPS-ROUTER` |
| 类型 | `code`（源码） |
| 位置 | `src/api/routers/aiops.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:23:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `5943ec826acb910bae7d339a3cc45f25c8d46e4d4f6eb2c7c5df4d1d81458ff2` |
| 字节数 | 9453 |

## 3. 摘要

诊断独立 SSE 入口 + 6 个运行态/审计端点。前置拒绝 terminal 未启用（503）；thread_id/evidence_id/target_id 三处正则白名单；证据原始引用仅 admin/auditor 可见。

## 4. 登记的符号

```
AIOpsRequest
diagnose_stream
_owned_run
get_run_status
continue_run
get_run_steps
get_run_evidence
get_run_evidence_item
get_probe_target_status
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/aiops-diagnosis.md`

## 6. 反向引用（15 份资料、196 处提及）

- `cases/aiops-audit.json`：L39, L126, L132, L167, L173, L209, L257, L299, L340, L346, L385
- `cases/aiops-diagnosis.json`：L37, L45, L81, L88, L125, L126, L173, L180, L395, L468, L470, L473 …共 17 处
- `cases/auth-console.json`：L597, L598, L605
- `requirements/_conventions.md`：L5
- `requirements/index.json`：L644, L645, L646, L737, L738, L1470, L1472, L1473, L1474, L1475, L1478, L1482 …共 40 处
- `requirements/modules/aiops-audit.md`：L109, L113, L149, L150, L157, L169, L175, L185, L188, L194, L204, L206 …共 19 处
- `requirements/modules/aiops-diagnosis.md`：L63, L64, L65, L143, L144, L150, L151, L152, L160, L164, L174, L201 …共 29 处
- `requirements/modules/auth-console.md`：L219, L221, L233, L350, L351
- `requirements/overview.md`：L52
- `requirements/project-card.md`：L32, L95
- `specs/feature-index.json`：L378, L962, L1165, L1191, L1219, L1244, L1269, L1296
- `specs/modules/aiops-audit.md`：L23, L29, L37, L58, L59, L60, L61, L62, L63, L71, L72, L73 …共 24 处
- `specs/modules/aiops-diagnosis.md`：L18, L20, L21, L22, L27, L32, L35, L37, L47, L48, L49, L50 …共 28 处
- `specs/modules/auth-console.md`：L55, L223, L231
- `specs/questions.md`：L105, L177, L213, L225, L243

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

