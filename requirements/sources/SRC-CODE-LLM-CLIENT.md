# SRC-CODE-LLM-CLIENT

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-LLM-CLIENT` |
| 类型 | `code`（源码） |
| 位置 | `src/llm/llm_client.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:36:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `ee27a0dee29f1336a42a527463e2720f1f5866c47acc3a7310b41bd004e7761c` |
| 字节数 | 12070 |

## 3. 摘要

OpenAI 兼容客户端（deepseek 名走 ChatOpenAI+base_url，qwen 名走 ChatTongyi）；主备模型 with_fallbacks（只对连接/超时/5xx/限流生效）；对 dashscope compatible-mode 注入 enable_thinking=False；请求 model 不在白名单则回落 settings.LLM_MODEL。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/rag-qa.md`

## 5. 反向引用（6 份资料、25 处提及）

- `cases/rag-qa.json`：L581, L666, L667, L668
- `requirements/index.json`：L1141, L1142, L1266, L1415, L1416, L1418
- `requirements/modules/rag-qa.md`：L89, L186, L280, L282, L286, L292, L334, L347
- `requirements/project-card.md`：L130, L176
- `specs/feature-index.json`：L936
- `specs/modules/rag-qa.md`：L60, L165, L221, L228

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

