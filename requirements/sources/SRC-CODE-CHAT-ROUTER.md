# SRC-CODE-CHAT-ROUTER

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-CHAT-ROUTER` |
| 类型 | `code`（源码） |
| 位置 | `src/api/routers/chat.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:25:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `8a883a52e4e91be4458ad6c0313cd0df37557629fb847dc1729f7949acf655fa` |
| 字节数 | 14309 |

## 3. 摘要

对话 7 端点：同步问答、SSE 流式问答（iterate_in_threadpool）、会话创建/列举/取消息/单删/批量删；问答结果写 ChatInteraction 留痕。

## 4. 登记的符号

```
chat
chat_stream
_resolve_plain_session
_save_chat_interaction
create_session
list_sessions
get_session_messages
delete_session
batch_delete_sessions
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/rag-qa.md`

## 6. 反向引用（10 份资料、102 处提及）

- `cases/assistant-agent.json`：L328
- `cases/rag-qa.json`：L49, L50, L96, L134, L135, L271, L315, L316, L526, L527, L578
- `requirements/index.json`：L1135, L1137, L1138, L1139, L1140, L1146, L1270, L1274, L1276, L1330, L1332, L1354 …共 29 处
- `requirements/modules/assistant-agent.md`：L97, L104, L114, L167, L174, L190
- `requirements/modules/evaluation.md`：L386
- `requirements/modules/rag-qa.md`：L84, L85, L87, L88, L95, L190, L198, L202, L228, L229, L235, L243 …共 25 处
- `specs/feature-index.json`：L725, L890, L912, L935, L1695
- `specs/modules/assistant-agent.md`：L53, L143
- `specs/modules/rag-qa.md`：L18, L19, L23, L31, L41, L42, L43, L44, L45, L51, L58, L59 …共 21 处
- `specs/questions.md`：L51

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

