# SRC-CODE-FRONTEND-ROUTER

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-FRONTEND-ROUTER` |
| 类型 | `code`（源码） |
| 位置 | `frontend/src/router/index.js` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:26:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `f9775e6d6d7a19803a1d6930557e14a0496b44671623df718913a49f9e0b7946` |
| 字节数 | 1690 |

## 3. 摘要

12 条路由（1 重定向 + 11 页面），除 /login 全部 requiresAuth；路由级懒加载；守卫只判 localStorage.token 存在，不校验有效性。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/console.md`

## 5. 反向引用（11 份资料、40 处提及）

- `cases/auth-console.json`：L505, L507, L513
- `requirements/index.json`：L615, L616, L697, L724, L739, L1389, L2269, L2575, L2597, L2599, L2721, L3078
- `requirements/modules/assistant-agent.md`：L61, L124
- `requirements/modules/auth-console.md`：L192, L196, L206, L268, L284, L327, L354
- `requirements/modules/evaluation.md`：L61, L388
- `requirements/modules/rag-qa.md`：L268, L272
- `requirements/modules/storage-queue.md`：L203
- `requirements/overview.md`：L143
- `requirements/project-card.md`：L111
- `specs/feature-index.json`：L354
- `specs/modules/auth-console.md`：L23, L37, L38, L54, L172, L179, L252, L311

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

