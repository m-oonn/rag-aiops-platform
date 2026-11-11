# spec · kb-ingest（知识库与文档摄取）

- 模块：`kb-ingest`，规则前缀 `RULE-KB-`，断言前缀 `ASRT-KB-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 需求依据：`requirements/modules/kb-ingest.md`（REQ-KB-001 ~ REQ-KB-010）
- 断言被 `cases/kb-ingest.json` 的 `assertion_id` 引用。**断言只描述可判定的观察点**，不描述"应该更好用"。
- 所有 `source` 均为 `完整相对路径:行号`。`basis=observed` 表示读源码核实；无一条 `confirmed`（本模块没有写着理由的产品决定文档）。
- 流程引用：`FLOW-KB-INGEST`（上传 → 解析 → 切分 → 向量化 → 就绪），流程正文与流程图见 `requirements/modules/kb-ingest.md:17`。

---

## 1. 交互与接口状态

### 1.1 入口清单（前端 → 接口）

| 用户动作 | 页面/元素 | 接口 | 方法 | source |
|---|---|---|---|---|
| 创建知识库 | `/knowledge-bases` →「创建知识库」按钮 | `/api/v1/knowledge-bases/` | POST | `frontend/src/views/KnowledgeBase.vue:5`、`src/api/routers/knowledge_base.py:219` |
| 查看我的知识库 | `/knowledge-bases` 卡片列表 | `/api/v1/knowledge-bases/` | GET | `frontend/src/views/KnowledgeBase.vue:190-197`、`src/api/routers/knowledge_base.py:239` |
| 改库 | 卡片右上编辑圆钮 | `/api/v1/knowledge-bases/{kb_id}` | PUT | `frontend/src/views/KnowledgeBase.vue:41-54,224-233`、`src/api/routers/knowledge_base.py:285` |
| 删库 | 卡片右上删除圆钮 | `/api/v1/knowledge-bases/{kb_id}` | DELETE | `frontend/src/views/KnowledgeBase.vue:235-244`、`src/api/routers/knowledge_base.py:248` |
| 上传文件 | `/knowledge-bases/:id` →「批量上传」 | `/api/v1/knowledge-bases/{kb_id}/upload` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:23-36`、`src/api/routers/knowledge_base.py:311` |
| 看文档列表/进度 | 文档表格 | `/api/v1/knowledge-bases/{kb_id}/documents` | GET | `frontend/src/views/KnowledgeBaseDetail.vue:303-328,492` |
| 单条重试 | 行内「重试」（仅 status=3 显示） | `/api/v1/knowledge-bases/documents/{doc_id}/retry` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:103,395-403`、`src/api/routers/knowledge_base.py:459` |
| 批量重试 | 工具栏「批量重试」 | `/api/v1/knowledge-bases/documents/batch-retry` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:38,372-381`、`src/api/routers/knowledge_base.py:413` |
| 批量删除 | 工具栏「批量删除」 | `/api/v1/knowledge-bases/documents/batch-delete` | DELETE | `frontend/src/views/KnowledgeBaseDetail.vue:39,383-393`、`src/api/routers/knowledge_base.py:436` |
| 本地关键词检索 | bm25 库顶部检索区「检索手册」 | `/api/v1/knowledge-bases/{kb_id}/search` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:9-20,277-291`、`src/api/routers/knowledge_base.py:507` |
| 生成 QA | 行内「生成 QA」 | `/api/v1/knowledge-bases/documents/{doc_id}/generate-qa?num_pairs=N` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:96,405-439`、`src/api/routers/knowledge_base.py:521` |
| 手建 QA | QA 对话框「新增 QA 对」 | `/api/v1/knowledge-bases/documents/{doc_id}/qa-pairs` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:152,575` |
| 改/删 QA | QA 对话框 | `/api/v1/knowledge-bases/qa-pairs/{qa_id}` | PUT / DELETE | `frontend/src/views/KnowledgeBaseDetail.vue:469-497`、`src/api/routers/knowledge_base.py:604,632` |
| 下载 QA | QA 对话框「下载 MD」 | `/api/v1/knowledge-bases/documents/{doc_id}/qa-pairs/download` | GET | `frontend/src/views/KnowledgeBaseDetail.vue:499-516`、`src/api/routers/knowledge_base.py:650` |
| 看分片 | 行内「分片」 | `/api/v1/knowledge-bases/documents/{doc_id}/chunks` | GET | `frontend/src/views/KnowledgeBaseDetail.vue:101,518-526`、`src/api/routers/knowledge_base.py:681` |
| 重新切分 | 行内「重新切分」 | `/api/v1/knowledge-bases/documents/{doc_id}/reprocess` | POST | `frontend/src/views/KnowledgeBaseDetail.vue:102,543-609`、`src/api/routers/knowledge_base.py:698` |
| 预览原文 | 行内「预览」/检索结果「查看引用原文」 | `/api/v1/knowledge-bases/documents/{doc_id}/preview` | GET | `frontend/src/views/KnowledgeBaseDetail.vue:528-541`、`src/api/routers/knowledge_base.py:735` |
| 查 QA 列表 | 行内「管理 QA」 | `/api/v1/knowledge-bases/documents/{doc_id}/qa-pairs` | GET | `frontend/src/views/KnowledgeBaseDetail.vue:441-450`、`src/api/routers/knowledge_base.py:755` |

统一前缀 `/api/v1`（`src/settings.py:12`），挂载点 `src/main.py:257`。

### 1.2 关键状态迁移（`knowledge_documents.status`）

| 起点 | 触发 | 终点 | source |
|---|---|---|---|
| — | 上传落盘成功建行 | `0` 上传中 | `src/api/routers/knowledge_base.py:385-396` |
| 0 | `process_document` 入口 | `1` 处理中 | `src/worker/tasks.py:60` |
| 1 | 切出 0 个 chunk | `2`（chunk_count=0） | `src/worker/tasks.py:122-128` |
| 1 | bm25 短路完成 | `2` | `src/worker/tasks.py:130-140` |
| 1 | 向量化 + 写库 + 插入成功 | `2` | `src/worker/tasks.py:195-206` |
| 1 | 任一步抛异常 | `3` + error_msg | `src/worker/tasks.py:208-229` |
| 3 | 单条重试 / 批量重试 | `0`（error_msg 清空） | `src/api/routers/knowledge_base.py:425-426,478-480` |
| 2/3 | 重新切分 | `0` | `src/api/routers/knowledge_base.py:719-721` |

状态字面量映射：`0 上传中 / 1 处理中 / 2 已完成 / 3 失败`（`frontend/src/utils/status.js:30`、`src/database/models.py:53`）。

### 1.3 功能单元（FEAT-KB-\*，供 `cases/kb-ingest.json` 的 `feature_id` 解析）

| feature_id | 用户目标 | 主入口 | requirement_refs | 源码锚点 |
|---|---|---|---|---|
| FEAT-KB-001 | 建/改知识库并选定检索方式 | `/knowledge-bases` →「创建知识库」 | REQ-KB-001 | `src/api/routers/knowledge_base.py:219-237,285-309` |
| FEAT-KB-002 | 上传文档并通过四道前置校验 | 详情页「批量上传」 | REQ-KB-002 | `src/api/routers/knowledge_base.py:143-215,311-411` |
| FEAT-KB-003 | 上传后任务派发与异步边界 | 上传接口响应 | REQ-KB-003 | `src/api/routers/knowledge_base.py:29-41,131-141` |
| FEAT-KB-004 | 解析与切分（页号感知） | `process_document` | REQ-KB-004 | `src/worker/tasks.py:84-128`、`src/processors/text_chunker.py:9-95` |
| FEAT-KB-005 | 向量化、双写与 bm25 短路就绪 | `process_document` | REQ-KB-005 | `src/worker/tasks.py:130-206`、`src/database/vector_db.py:108-151` |
| FEAT-KB-006 | 失败落库、重试与重新切分 | 行内「重试」/「重新切分」 | REQ-KB-006 | `src/worker/tasks.py:208-229`、`src/api/routers/knowledge_base.py:413-490,698-733` |
| FEAT-KB-007 | bm25 库本地关键词检索 | 详情页「检索手册」 | REQ-KB-007 | `src/api/routers/knowledge_base.py:507-519`、`src/retrieval/knowledge_bm25.py:7-19` |
| FEAT-KB-008 | QA 对的生成/手建/改/删/导出 | 行内「生成 QA」「管理 QA」 | REQ-KB-008 | `src/api/routers/knowledge_base.py:521-679` |
| FEAT-KB-009 | 分片查看与原文预览 | 行内「分片」「预览」 | REQ-KB-009 | `src/api/routers/knowledge_base.py:681-753`、`src/utils/preview_utils.py:56-183` |
| FEAT-KB-010 | 跨用户权限与删除影响 | 各端点 | REQ-KB-010 | `src/api/routers/knowledge_base.py:239-283,436-457` |

---

## 2. 规则

### RULE-KB-001 retrieval_mode 只接受 hybrid 与 bm25
- **要求**：`chunking_config.retrieval_mode` 若出现且不为 `hybrid`/`bm25`，建库与改库都必须失败。
- **适用条件**：`POST /knowledge-bases/`、`PUT /knowledge-bases/{kb_id}`，`chunking_config` 为对象且含 `retrieval_mode` 键。
- **可观察**：HTTP 422，`detail` 中含 `retrieval_mode must be hybrid or bm25`。
- **source**：`src/api/routers/knowledge_base.py:51-56,64,219-237,285-309`
- **requirement_refs**：REQ-KB-001　**basis**：observed

### RULE-KB-002 文件名净化：拒绝路径穿越
- **要求**：文件名（含客户端传来的带路径名）若为空、含 `..`、`/`、`\`，或 `Path(filename).name` 为空/为 `.`/`..`，必须 400 拒绝，**不落盘**。
- **适用条件**：所有 `upload` 请求。
- **可观察**：三种 detail 之一——空串 → `Filename cannot be empty`；含 `..`/`/`/`\` → `Invalid filename: path traversal detected`；base 名为 `.`/`..` → `Invalid filename`。`data/raw` 下无新增文件。
- **source**：`src/api/routers/knowledge_base.py:197-215,328`
- **requirement_refs**：REQ-KB-002　**basis**：observed

### RULE-KB-003 扩展名白名单共 13 项
- **要求**：仅 `.pdf .docx .doc .xlsx .xls .csv .pptx .ppt .md .html .htm .txt` 可上传，其余 400。
- **适用条件**：upload。
- **可观察**：400，`detail` 前缀 `Unsupported file type: {ext}. Allowed: `。
- **注意**：`src/api/routers/loadfile.py:16` 另有 9 项白名单（无 `.ppt`、`.htm`、`.txt`），那是遗留上传链路，**不适用于知识库上传**。
- **source**：`src/api/routers/knowledge_base.py:145-148,331-336`
- **requirement_refs**：REQ-KB-002　**basis**：observed

### RULE-KB-004 大小上限 50MB，超限返回 413（不是 400）
- **要求**：`len(file_content) > 50*1024*1024` 时必须返回 **413**。
- **适用条件**：upload，且请求已通过扩展名检查。
- **可观察**：HTTP 413，`detail` 形如 `File too large: {n} bytes exceeds limit of 52428800 bytes`。
- **风险**：读取发生在判大小**之前**（`src/api/routers/knowledge_base.py:339`），因此不能把 413 当作内存保护证据。
- **source**：`src/api/routers/knowledge_base.py:143,339-345`
- **requirement_refs**：REQ-KB-002　**basis**：observed

### RULE-KB-005 魔数校验：二进制 7 类校验，文本 5 类跳过
- **要求**：`.pdf` 头须为 `%PDF`；`.docx/.xlsx/.pptx` 须为 `PK\x03\x04`；`.doc/.xls/.ppt` 须为 `\xd0\xcf\x11\xe0`；`.txt/.md/.csv/.html/.htm` 直接放行；内容长度 `< 4` 字节时 400 `文件内容过短，无法验证类型`。
- **适用条件**：upload，且扩展名在白名单内。
- **可观察**：不匹配时 400，`detail` 为 `文件内容与扩展名 '{ext}' 不匹配（magic number 校验失败）`。
- **推论**：`.txt` 上传二进制内容不会被本规则拦截。
- **source**：`src/api/routers/knowledge_base.py:151-194,349`
- **requirement_refs**：REQ-KB-002　**basis**：observed

### RULE-KB-006 上传权限只认 owner，is_public 不放宽
- **要求**：`kb.owner_id != current_user.id` 时 upload 必须 403；`kb` 不存在时 404。
- **适用条件**：upload。**不适用于** GET 单库/文档列表（那两处允许 `is_public`）。
- **可观察**：403 `Not authorized`；404 `Knowledge Base not found`。
- **source**：`src/api/routers/knowledge_base.py:320-324`（对比读权限 `:281-282`、`:501-502`）
- **requirement_refs**：REQ-KB-002, REQ-KB-010　**basis**：observed

### RULE-KB-007 派发三分支与 5 秒超时
- **要求**：`_dispatch_document` 必须满足：`retrieval_mode=="bm25"` → 进程内 BackgroundTasks 且 `celery_task_id=None`；否则先试 Celery，`future.result(timeout=5)` 内成功则写 `celery_task_id`，超时/异常则回落 BackgroundTasks 且 `task_id` 返回 `null`。
- **适用条件**：upload / retry / batch-retry / reprocess 四处派发。
- **可观察**：响应 `message` 为 `File uploaded successfully`（异步）或 `File uploaded (sync mode)`（回落）；`task_id` 为字符串或 `null`。
- **source**：`src/api/routers/knowledge_base.py:29-41,131-141,402-411`
- **requirement_refs**：REQ-KB-003　**basis**：observed

### RULE-KB-008 MinIO 镜像失败不阻断上传
- **要求**：`storage_service.upload_file` 抛异常时只打印日志，接口仍返回成功，文档行仍创建。
- **适用条件**：upload 且落盘成功。
- **可观察**：响应 200 且返回 `doc_id`；服务端日志（stdout）出现 `Failed to upload to MinIO: …`；`data/raw` 有文件。
- **source**：`src/api/routers/knowledge_base.py:367-380`
- **requirement_refs**：REQ-KB-002　**basis**：observed

### RULE-KB-009 切分配置优先级 doc > kb > 1000/200
- **要求**：`config = doc.chunking_config or kb.chunking_config`，`chunk_size` 默认 1000、`chunk_overlap` 默认 200。
- **适用条件**：`process_document` 的 hybrid 与 bm25 两条路径。
- **可观察**：用不同 `chunk_size` 建档并上传同一文件，`GET .../chunks` 返回的条数与 `chunk_count` 随之变化。
- **反例（必须记录）**：前端的 `method`（recursive/fixed/separator/semantic）与 `separator` **不参与切分**，只读写 `chunk_size`/`chunk_overlap`/`retrieval_mode`。改 `method` 不改变切分结果。
- **source**：`src/worker/tasks.py:95-107`、`src/processors/text_chunker.py:9-16`、`frontend/src/views/KnowledgeBase.vue:77-93`
- **requirement_refs**：REQ-KB-004　**basis**：observed

### RULE-KB-010 PDF 用真实页码切分，非 PDF 用正则启发式
- **要求**：PDF 必须先 `re.split(r"\[Page (\d+)\]", content)` 还原页边界，再 `split_text_with_pages`，chunk 的 `page_num` 等于真实页号；非 PDF 走 `split_document`，页号靠正文残留 `[Page N]`/`[Slide N]` 推断。
- **适用条件**：`file_type == "pdf"` 与否。
- **可观察**：PDF 的 chunk `page_num` 落在 `1..page_count` 且单调不减；非 PDF 可能出现跨页 chunk 的页码失真。
- **source**：`src/worker/tasks.py:112-117`、`src/processors/text_chunker.py:18-95`
- **requirement_refs**：REQ-KB-004　**basis**：observed

### RULE-KB-011 切出 0 个 chunk 记成功而非失败
- **要求**：chunks 为空时删旧 chunk、`status=2`、返回 `Completed (No content)`，**不置 3**。
- **适用条件**：任何文档（典型为扫描件 PDF、空文件）。
- **可观察**：列表显示"已完成"，`chunk_count=0`，`GET .../chunks` 返回空数组。
- **source**：`src/worker/tasks.py:122-128`
- **requirement_refs**：REQ-KB-004, REQ-KB-006　**basis**：observed

### RULE-KB-012 bm25 库短路：不调 embedding、不写向量
- **要求**：`config.retrieval_mode == "bm25"` 时，必须写 `DocumentChunk(vector_id="")`、置 `status=2`、返回 `Success (BM25 only)`，且**不调用** embedding、**不调用** Milvus。
- **适用条件**：文档的 `chunking_config.retrieval_mode` 或所属 kb 的为 `bm25`。
- **可观察**：`status=2`；`GET .../chunks` 有内容；Milvus 中查不到该 doc 的向量；无 embedding 网络调用。
- **source**：`src/worker/tasks.py:130-140`、`src/api/routers/knowledge_base.py:125-128`
- **requirement_refs**：REQ-KB-005　**basis**：observed

### RULE-KB-013 向量与 SQL 双写，向量 ID 等于 chunk 主键
- **要求**：hybrid 路径写 `DocumentChunk` 时 `vector_id` 必须等于该行 `id`，同一条记录写入 Milvus；Milvus 侧必须先写本地 `LocalVectorStore` 再写远端，远端不可用/异常时**不抛异常**、返回 `False`。
- **适用条件**：hybrid 路径。
- **可观察**：`document_chunks.vector_id` 非空且等于 `id`；`data/vectors/vectors_meta.json` 中存在对应 id；Milvus 断开时上传仍显示"已完成"。
- **source**：`src/worker/tasks.py:159-198`、`src/database/vector_db.py:108-151`、`src/database/local_vector_store.py:64-87`
- **requirement_refs**：REQ-KB-005　**basis**：observed

### RULE-KB-014 embedding 数量不一致必须失败
- **要求**：`len(embeddings) != len(chunks)` 时抛异常，最终 `status=3`、`error_msg` 含 `Mismatch between chunks`。
- **适用条件**：hybrid 路径。
- **可观察**：`status=3`；`error_msg` 形如 `Mismatch between chunks (n) and embeddings (m) count`。
- **source**：`src/worker/tasks.py:144-150`
- **requirement_refs**：REQ-KB-005　**basis**：observed

### RULE-KB-015 失败必须落库为 status=3 且不 re-raise
- **要求**：`process_document` 的 `except` 分支必须 `rollback` → 重查 doc → `status=3` + `error_msg=str(e)` → commit，并**不得**把异常抛给 Celery（否则任务会被标成 FAILURE 且 meta 反序列化报错）。
- **适用条件**：处理链任一环节抛异常。
- **可观察**：`status=3`；函数返回值为字符串 `Failed: {e}`；Celery 任务状态不是 FAILURE 异常态。
- **附带事实**：`error_msg` **不出现在** `DocumentOut`（`src/api/routers/knowledge_base.py:78-89`），界面上无展示位。
- **source**：`src/worker/tasks.py:208-229`
- **requirement_refs**：REQ-KB-006　**basis**：observed

### RULE-KB-016 单条重试要求原文件仍在磁盘
- **要求**：`doc.file_path` 不存在时 400 `Original file not found on server`，且不重置状态；存在时置 `status=0` 并重新派发。
- **适用条件**：`POST /knowledge-bases/documents/{doc_id}/retry`。
- **可观察**：400 或 200 + `{"message":"Retry started", …}`；随后文档状态回到 0→1→2/3。
- **source**：`src/api/routers/knowledge_base.py:459-490`
- **requirement_refs**：REQ-KB-006　**basis**：observed

### RULE-KB-017 批量重试逐条鉴权，只重启有权的
- **要求**：body 为 `List[int]`；逐条查文档所属 kb 校验 `owner_id`，仅命中的重置为 `status=0`/`error_msg=None` 并派发；返回 `Restarted {n} documents`，**不报告被跳过的 id**。
- **适用条件**：`POST /knowledge-bases/documents/batch-retry`。
- **可观察**：响应 message 中的 n ≤ 请求 id 数；无权的文档状态不变。
- **source**：`src/api/routers/knowledge_base.py:413-434`、`frontend/src/views/KnowledgeBaseDetail.vue:372-381`
- **requirement_refs**：REQ-KB-006　**basis**：observed

### RULE-KB-018 重新切分可改配置，非法 retrieval_mode 返回 422
- **要求**：`POST /documents/{doc_id}/reprocess` 的 body 可选；`mode = config.retrieval_mode or previous.retrieval_mode or "hybrid"`；`mode` 不在 `{hybrid,bm25}` 时 422 `Invalid retrieval_mode`；通过则合并进 `doc.chunking_config` 并置 `status=0` 重派。
- **适用条件**：需 owner。
- **可观察**：422 时文档状态不变；200 时状态回 0，`GET /documents` 里 `chunking_config` 变为新值。
- **source**：`src/api/routers/knowledge_base.py:698-733`
- **requirement_refs**：REQ-KB-006　**basis**：observed

### RULE-KB-019 本地关键词检索仅 bm25 库可用，且每次现场重建索引
- **要求**：`kb.chunking_config.retrieval_mode != "bm25"` 时 400 `此入口仅用于本地关键词知识库`；命中时返回 `{data_source:"knowledge_base", retrieval_mode:"bm25", results:[{chunk_id,content,score,**metadata}]}`，其索引**由本次请求从 SQLite 现场构建**，不使用进程内缓存。
- **适用条件**：`POST /knowledge-bases/{kb_id}/search`，`query` 长度 1–1000，`top_k` 1–20（默认 5）。
- **可观察**：新上传的文档（`status=2`）无需重启服务即可被该入口检索到——这是它与混合检索的**关键区别**。
- **source**：`src/api/routers/knowledge_base.py:120-122,507-519`、`src/retrieval/knowledge_bm25.py:7-19`
- **requirement_refs**：REQ-KB-007　**basis**：observed

### RULE-KB-020 generate-qa 的取数与硬编码
- **要求**：`num_pairs` 被夹到 `[1,20]`；取该文档前 10 条 chunk；**无 chunk 时使用占位串** `Document content for {filename}`；落库每条 `qa_type="single_hop"`、`status=0`。
- **适用条件**：owner 的 `POST /documents/{doc_id}/generate-qa`。
- **可观察**：`num_pairs=100` 实际最多生成 20 条；chunk_count=0 的文档也能"生成"出 QA；返回的 `qa_type` 恒为 `single_hop`。
- **source**：`src/api/routers/knowledge_base.py:521-570`
- **requirement_refs**：REQ-KB-008　**basis**：observed

### RULE-KB-021 手建 QA 默认已确认
- **要求**：`POST /documents/{doc_id}/qa-pairs` 落库 `status=1`（已确认）、`created_by=当前用户名`；与之相对，生成路径落库 `status=0`（待确认）。
- **适用条件**：owner。
- **可观察**：两条路径新建的 QA `status` 不同（1 vs 0）。
- **source**：`src/api/routers/knowledge_base.py:575-602`（对比 `:561`）
- **requirement_refs**：REQ-KB-008　**basis**：observed

### RULE-KB-022 QA 导出为 Markdown 附件
- **要求**：响应 `media_type="text/markdown"`，`Content-Disposition: attachment; filename=qa_pairs_{doc.filename}.md`，正文含 `# QA Pairs for {filename}` 与每对 `## Question {i} ({qa_type})` + `**Q:**` + `**A:**`。
- **适用条件**：owner 的 `GET /documents/{doc_id}/qa-pairs/download`。
- **可观察**：响应头 MIME 与文件名；下载内容可按上述结构解析。
- **已知不一致**：前端另存为 `qa_pairs_{docId}.md`（`frontend/src/views/KnowledgeBaseDetail.vue:499-516`），与服务端文件名不同。
- **source**：`src/api/routers/knowledge_base.py:650-679`
- **requirement_refs**：REQ-KB-008　**basis**：observed

### RULE-KB-023 分片查看 limit 默认 100 且无上限校验
- **要求**：`GET /documents/{doc_id}/chunks?limit=N`，`limit` 默认 100，**不做最大值限制**；返回 `id/chunk_uid/content/page_num`。
- **适用条件**：owner 或 `is_public` 库的读者。
- **可观察**：`chunk_count > 100` 的文档，不传 limit 时最多返回 100 条 → 界面看不全（无翻页）。
- **source**：`src/api/routers/knowledge_base.py:681-696,111-117`
- **requirement_refs**：REQ-KB-009　**basis**：observed

### RULE-KB-024 预览按类型分流，未知类型强制下载
- **要求**：`pdf` → `application/pdf` + `inline`；`md` → 净化后 `text/html`；`txt` → `text/plain` 转义；`docx/doc` → HTML；`xlsx/xls` → `pandas.read_excel` 转 HTML（`escape=True`）；其余类型 → `application/octet-stream` + `attachment`。文件不在磁盘 → 404 `File not found on server`。
- **适用条件**：`GET /documents/{doc_id}/preview`。
- **可观察**：响应 `Content-Type` 与 `Content-Disposition`；未知类型（如 `.csv`、`.pptx`）返回下载而非内联。**注意 `.csv`/`.pptx`/`.ppt`/`.html` 均落入"其余"分支**。
- **source**：`src/utils/preview_utils.py:56-183`、`src/api/routers/knowledge_base.py:735-753`
- **requirement_refs**：REQ-KB-009　**basis**：observed

### RULE-KB-025 删除知识库不删物理文件
- **要求**：`DELETE /knowledge-bases/{kb_id}` 依次做：按 kb_id 删 Milvus/本地向量 → 级联删文档与 chunk → 级联删 QA → 删 KB 行；**不得**要求物理文件被删除。
- **适用条件**：owner。
- **可观察**：删除后 `GET /{kb_id}` 404；`data/raw` 下原文件**仍存在**（`os.remove` 只出现在批量删文档 `src/api/routers/knowledge_base.py:448-452`）。
- **source**：`src/api/routers/knowledge_base.py:248-270`、`src/database/vector_db.py:206-218`、`src/database/models.py:39-40`
- **requirement_refs**：REQ-KB-010　**basis**：observed

### RULE-KB-026 批量删文档吞掉文件删除异常且不清向量
- **要求**：`DELETE /knowledge-bases/documents/batch-delete` 的 `os.remove` 必须包在 `try/except: pass`，文件删不掉也返回成功；**不得**调用向量库删除。
- **适用条件**：owner。
- **可观察**：返回 `Deleted {n} documents`；若先 `chmod`/占用文件使其不可删，接口仍 200；该 doc 的向量仍在（删库时才按 kb_id 清）。
- **source**：`src/api/routers/knowledge_base.py:436-457`
- **requirement_refs**：REQ-KB-010, REQ-KB-006　**basis**：observed

### RULE-KB-027 知识库列表只返回自己的库
- **要求**：`GET /knowledge-bases/` 必须只按 `owner_id == current_user.id` 过滤，即使存在 `is_public=True` 的他人库也不列出。
- **适用条件**：任何登录用户。
- **可观察**：A 建 `is_public=True` 的库，B 调 `GET /knowledge-bases/` 看不到；但 B 用该 kb_id 调 `GET /knowledge-bases/{kb_id}` 能读（200）。
- **source**：`src/api/routers/knowledge_base.py:239-246,272-283`
- **requirement_refs**：REQ-KB-010　**basis**：observed

### RULE-KB-028 进度只可轮询，无推送无取消
- **要求**：系统不得提供任务进度查询端点（`src/api/routers/tasks.py` 未挂载）也不提供取消端点；前端只能每 3000ms 轮询 `GET /knowledge-bases/{kb_id}/documents`。
- **适用条件**：所有上传/重试/重处理。
- **可观察**：`GET /api/v1/tasks/*` 返回 404；前端 Network 面板可见约 3 秒一次 documents 请求，且仅当存在 status 0/1 的文档时持续。
- **source**：`src/main.py:255-265`、`frontend/src/views/KnowledgeBaseDetail.vue:316-328`、`frontend/src/composables/usePolling.js:8`
- **requirement_refs**：REQ-KB-003　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
|---|---|---|---|---|
| ASRT-KB-001 | `POST /knowledge-bases/` 传 `chunking_config={"retrieval_mode":"vector"}` 返回 **422**，detail 含 `retrieval_mode must be hybrid or bm25`；合法值 `hybrid`/`bm25` 返回 200 且 `kb_uid` 非空 | RULE-KB-001 | REQ-KB-001 | observed |
| ASRT-KB-002 | 上传文件名 `/api/v1/../../etc/passwd.pdf` 或 `..%2Fevil.pdf` 返回 **400**，detail 含 `Invalid filename: path traversal detected`，且 `data/raw` 无新增 | RULE-KB-002 | REQ-KB-002 | observed |
| ASRT-KB-003 | 上传 `.exe` 返回 **400**，detail 以 `Unsupported file type:` 开头；上传 13 项白名单内的 `.md` 返回 200 | RULE-KB-003 | REQ-KB-002 | observed |
| ASRT-KB-004 | 上传 52428801 字节文件返回 **413**（非 400、非 422）；52428800 字节返回 200 | RULE-KB-004 | REQ-KB-002 | observed |
| ASRT-KB-005 | 把 `.pdf` 内容改成 `hello`（5 字节非 `%PDF`）上传 → **400**，detail 含 `magic number 校验失败`；把 `.txt` 上传二进制内容 → **200**（文本类不校验） | RULE-KB-005 | REQ-KB-002 | observed |
| ASRT-KB-006 | 用户 B 对用户 A 的库（即使 `is_public=true`）上传 → **403**；B 对同库 `GET /{kb_id}` → **200** | RULE-KB-006 | REQ-KB-002, REQ-KB-010 | observed |
| ASRT-KB-007 | 向 `retrieval_mode="bm25"` 的库上传成功后，响应 `message` 为 `File uploaded successfully`；若把 broker 断开（故障注入），响应 `message` 变 `File uploaded (sync mode)` 且 `task_id` 为 `null`，且**两种情况 HTTP 都是 200** | RULE-KB-007 | REQ-KB-003 | observed |
| ASRT-KB-008 | MinIO 不可用时上传仍返回 200 且带 `doc_id`；`data/raw` 有文件；服务端 stdout 含 `Failed to upload to MinIO` | RULE-KB-008 | REQ-KB-002 | observed |
| ASRT-KB-009 | 同一 PDF 在 `chunk_size=1000` 与 `chunk_size=300` 的库里分别上传，`chunk_count` 不同；但把 `method` 从 `recursive` 改成 `fixed` 而后端配置相同时，`chunk_count` 不变 | RULE-KB-009 | REQ-KB-004 | observed |
| ASRT-KB-010 | 多页 PDF 处理完成后 `GET .../chunks` 返回的每条 `page_num ≥ 1` 且最大值 ≤ PDF 页数 | RULE-KB-010 | REQ-KB-004 | observed |
| ASRT-KB-011 | 上传一个空 `.txt`，最终 `status=2` 且 `chunk_count=0`；`GET .../chunks` 返回空数组 | RULE-KB-011 | REQ-KB-004, REQ-KB-006 | observed |
| ASRT-KB-012 | 向 bm25 库上传后 `status=2`、`GET .../chunks` 非空；同一文档在向量侧的条数为 0（Milvus 不可用时可改判 `data/vectors/vectors_meta.json` 无该 doc_id） | RULE-KB-012 | REQ-KB-005 | observed |
| ASRT-KB-013 | hybrid 库处理完成后，每条 `document_chunks.vector_id` 等于其 `id` 且非空；Milvus 断开时上传仍为 `status=2`（不因向量库不可用而失败） | RULE-KB-013 | REQ-KB-005 | observed |
| ASRT-KB-014 | 故障注入使 embedding 返回条数与 chunk 数不一致时，`status=3` 且 `error_msg` 含 `Mismatch between chunks` | RULE-KB-014 | REQ-KB-005 | observed |
| ASRT-KB-015 | 故障注入使解析抛异常时，`status=3`、`error_msg` 非空、HTTP 层无 500；且 `GET .../documents` 响应体**不含** `error_msg` 字段 | RULE-KB-015 | REQ-KB-006 | observed |
| ASRT-KB-016 | 先删除 `data/raw` 下原文件，再调 `POST .../documents/{id}/retry` → **400**，detail 为 `Original file not found on server`，文档状态仍为 3 | RULE-KB-016 | REQ-KB-006 | observed |
| ASRT-KB-017 | `POST .../documents/batch-retry` body `[own_id, other_user_id]` → 返回 `Restarted 1 documents`（或 `Restarted 2` 之外的确定值，取决于前置），且 other 的文档状态不变 | RULE-KB-017 | REQ-KB-006 | observed |
| ASRT-KB-018 | `POST .../reprocess` body `{"retrieval_mode":"nope"}` → **422**（detail 为字符串 `Invalid retrieval_mode`），文档状态不变；body `{"chunk_size":300}` → 200 且状态回 0 | RULE-KB-018 | REQ-KB-006 | observed |
| ASRT-KB-019 | 向 hybrid 库 `POST /{kb_id}/search` → **400**，detail 为 `此入口仅用于本地关键词知识库`；向 bm25 库同请求 → 200 且 `results[].chunk_id` 存在 | RULE-KB-019 | REQ-KB-007 | observed |
| ASRT-KB-020 | 新建 bm25 库、上传文档至 `status=2` 后立刻（同一进程、未重启）调 `POST /{kb_id}/search` 关键词命中 → `results` 非空（证明该入口不等索引重建） | RULE-KB-019 | REQ-KB-007 | observed |
| ASRT-KB-021 | `POST .../generate-qa?num_pairs=100` 返回的条数 ≤ 20；返回项 `qa_type` 全为 `single_hop`；对 `chunk_count=0` 的文档调用也返回 200 | RULE-KB-020 | REQ-KB-008 | observed |
| ASRT-KB-022 | `POST .../documents/{id}/qa-pairs` 新建后 `GET .../qa-pairs` 中该项 `status=1`；而 generate-qa 产生的项 `status=0` | RULE-KB-021 | REQ-KB-008 | observed |
| ASRT-KB-023 | `GET .../qa-pairs/download` 响应头 `Content-Type` 含 `text/markdown`，`Content-Disposition` 含 `attachment` 与 `qa_pairs_{filename}.md`；正文首行以 `# QA Pairs for` 开头 | RULE-KB-022 | REQ-KB-008 | observed |
| ASRT-KB-024 | 对 `chunk_count > 100` 的文档 `GET .../chunks`（不带 limit）返回条数 = 100；带 `limit=500` 返回条数可 > 100 | RULE-KB-023 | REQ-KB-009 | observed |
| ASRT-KB-025 | `GET .../preview` 对 `.pdf` 返回 `Content-Type: application/pdf` 且 `Content-Disposition` 含 `inline`；对 `.pptx` 返回 `application/octet-stream` 且含 `attachment`；文件被删后 → **404** detail `File not found on server` | RULE-KB-024 | REQ-KB-009 | observed |
| ASRT-KB-026 | 删除知识库后 `GET /{kb_id}` → 404、`GET /{kb_id}/documents` → 404，且 `data/raw` 下原文件仍存在 | RULE-KB-025 | REQ-KB-010 | observed |
| ASRT-KB-027 | 批量删除 1 份文档后返回 `Deleted 1 documents`；即使人为使 `os.remove` 失败（文件被独占）仍返回 200 | RULE-KB-026 | REQ-KB-010 | observed |
| ASRT-KB-028 | A 建 `is_public=True` 的库，B 调 `GET /knowledge-bases/` 的结果中**不含**该库 id；B 调 `GET /knowledge-bases/{kb_id}` → 200 | RULE-KB-027 | REQ-KB-010 | observed |
| ASRT-KB-029 | `GET /api/v1/tasks/{any}` → 404（路由未挂载）；上传后前端在 3 秒间隔内重复请求 `GET /knowledge-bases/{kb_id}/documents` | RULE-KB-028 | REQ-KB-003 | observed |

---

## 4. 未决（供 `specs/questions.md` 汇总）

见 `requirements/modules/kb-ingest.md` §4 的 7 条。规格层需补充的判定口径：

- `specs/questions.md` 新增条目建议：**「上传 413 与 400 的契约」**——现实现 413 是否稳定（客户端/网关是否改写状态码）本轮未验证。
- **「`error_msg` 要不要暴露」**——若不暴露，ASRT-KB-015 的失败原因断言只能查 SQLite，不能查接口。
- **「`method`/`separator` 是未接线还是已废弃」**——决定 ASRT-KB-009 后半段是"现状断言"还是"缺陷断言"。
