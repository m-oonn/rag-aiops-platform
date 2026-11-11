# SRC-CODE-MAIN

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-MAIN` |
| 类型 | `code`（源码） |
| 位置 | `src/main.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:24:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `a048d37db5c1118d2b5c5d4140667c13df2f88b2763f4d75b88ce2bae15d5ee9` |
| 字节数 | 12328 |

## 3. 摘要

FastAPI 装配入口：密钥强校验→建表/列级补列→限流/安全头/trace_id 中间件→11 组路由挂载→可选 Prometheus→uvicorn 8200（避开 Windows 保留段 7911-8010）。

## 4. 登记的符号

```
create_app
_validate_secrets
_MIN_SECRET_KEY_LENGTH
_migrate_schema
_build_cors_origins
security_headers_middleware
trace_id_middleware
_setup_prometheus
lifespan
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/platform.md`

## 6. 反向引用（22 份资料、194 处提及）

- `cases/assistant-agent.json`：L18
- `cases/auth-console.json`：L343, L349
- `cases/evaluation.json`：L18
- `cases/kb-ingest.json`：L18
- `cases/platform.json`：L36, L37, L38, L44, L66, L78, L79, L85, L120, L121, L128, L163 …共 32 处
- `cases/rag-qa.json`：L669
- `cases/storage-queue.json`：L18
- `requirements/index.json`：L230, L234, L235, L236, L237, L239, L241, L242, L244, L268, L269, L270 …共 40 处
- `requirements/modules/aiops-diagnosis.md`：L143, L621, L629
- `requirements/modules/auth-console.md`：L320
- `requirements/modules/evaluation.md`：L61, L88, L389
- `requirements/modules/kb-ingest.md`：L67, L136
- `requirements/modules/platform.md`：L54, L64, L70, L72, L75, L76, L77, L78, L86, L97, L98, L99 …共 40 处
- `requirements/modules/rag-qa.md`：L288
- `requirements/overview.md`：L116, L121, L142, L228
- `requirements/project-card.md`：L98, L100, L112, L113, L114, L120
- `specs/feature-index.json`：L58, L85, L131, L154, L181, L205
- `specs/modules/auth-console.md`：L120, L303
- `specs/modules/evaluation.md`：L31
- `specs/modules/kb-ingest.md`：L37, L272
- `specs/modules/platform.md`：L20, L33, L34, L35, L36, L37, L38, L39, L47, L48, L49, L50 …共 40 处
- `specs/questions.md`：L10, L17, L93, L123

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

