# 模块规格：storage-queue（MinIO 文件、预览、Celery 队列监控与依赖健康）

- 模块 ID：`storage-queue`（前缀 `STORE`）
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 主链路：`FLOW-STORE`
- 依据来源：`requirements/modules/storage-queue.md`；除注明 confirmed 外均为 observed
- 生成时间：2026-11-11

## 1. 入口与接口清单

### 1.1 存储（前缀 `/api/v1/storage`）

| 用户动作 | 页面元素 | 接口 | 方法 | source |
| --- | --- | --- | --- | --- |
| 列出我的文件 | MinIO 页签文件表格 | `/api/v1/storage/files` | GET | `src/api/routers/storage.py:43` |
| 下载文件 | 行内「下载」 | `/api/v1/storage/download/{object_name:path}` | GET | `src/api/routers/storage.py:62` |
| 在线预览 | 行内「预览」→ iframe | `/api/v1/storage/preview/{object_name:path}` | GET | `src/api/routers/storage.py:98` |
| 上传文件 | 上传控件 | `/api/v1/storage/upload` | POST | `src/api/routers/storage.py:137` |
| 批量删除 | 多选后删除 | `/api/v1/storage/batch-delete` | POST | `src/api/routers/storage.py:170` |
| 获取临时访问链接 | **无界面** | `/api/v1/storage/url/{object_name:path}` | GET | `src/api/routers/storage.py:187` |
| 假登录 MinIO | MinIO 页签登录弹窗 | **无请求**，只写 localStorage | — | `frontend/src/views/Monitor.vue:264-283` |

### 1.2 队列监控（前缀 `/api/v1/monitor`）

| 用户动作 | 页面元素 | 接口 | 方法 | source |
| --- | --- | --- | --- | --- |
| 查看队列任务 | 队列页签表格 | `/api/v1/monitor/` | GET | `src/api/routers/monitor.py:32` |
| 查看四类计数 | 顶部四张统计卡 | `/api/v1/monitor/stats` | GET | `src/api/routers/monitor.py:91` |
| 删除单个任务 | 行内删除 | `/api/v1/monitor/tasks/{task_id}` | DELETE | `src/api/routers/monitor.py:108` |
| 批量删除任务 | 多选删除 | `/api/v1/monitor/tasks/batch-delete` | POST | `src/api/routers/monitor.py:134` |

### 1.3 健康与依赖（前缀 `/api/v1/health`）

| 用户动作 | 页面元素 | 接口 | 方法 | 鉴权 | source |
| --- | --- | --- | --- | --- | --- |
| 存活探测 | 无 | `/api/v1/health` | GET | 否 | `src/api/routers/health.py:14` |
| worker 队列统计 | `/queue-monitor` 页 | `/api/v1/health/queues` | GET | **是** | `src/api/routers/health.py:19` |
| 依赖健康总览 | **无界面** | `/api/v1/health/dependencies` | GET | **是** | `src/api/routers/health.py:155` |
| 可用模型列表 | 助手下拉框间接使用 | `/api/v1/health/models` | GET | 否 | `src/api/routers/health.py:176` |

### 1.4 降级矩阵（MinIO 缺席时各方法的表现）

| 方法 | 降级行为 | 接口可见效果 | source |
| --- | --- | --- | --- |
| `list_files` | 返回 `[]` | 200 + 空列表 | `src/services/storage.py:56-58` |
| `get_file_stream` | 返回 None | 404 `'File not found'` | `src/services/storage.py:90-98` |
| `get_file_url` | 返回 None | 404 `'File not found or error generating URL'` | `src/services/storage.py:100-111` |
| `upload_file` | `raise RuntimeError` | 500 | `src/services/storage.py:39-41` |
| `delete_file` / `batch_delete_files` | `raise RuntimeError` | 500 | `src/services/storage.py:113-137` |

### 1.5 功能单元（FEAT-STORE-\*，供 `specs/feature-index.json` 与 `cases/storage-queue.json` 的 `feature_id` 解析）

| ID | 功能单元（用户视角） | 入口 | requirement_refs | source |
| --- | --- | --- | --- | --- |
| FEAT-STORE-001 | 打开「MinIO 存储」页，看得到自己名下的文件清单；页上的「登录」只是界面假象 | `/monitor` →「MinIO 存储」页签 | REQ-STORE-001, REQ-STORE-005 | `src/api/routers/storage.py:43-60,170-197`、`frontend/src/views/Monitor.vue:264-304` |
| FEAT-STORE-002 | 点一下就下载文件，中文名也不乱码 | 行内「下载」 | REQ-STORE-002 | `src/api/routers/storage.py:62-96`、`frontend/src/views/Monitor.vue:306-315` |
| FEAT-STORE-003 | 不下载直接在线预览（pdf / md / txt / docx / xlsx） | 行内「预览」 | REQ-STORE-003 | `src/api/routers/storage.py:98-135`、`src/utils/preview_utils.py:56-183` |
| FEAT-STORE-004 | MinIO 挂了系统照样起得来；读写行为有明确差别（读空、写报错） | 后端启动 / 上传 / 知识库上传 | REQ-STORE-006, REQ-STORE-007 | `src/services/storage.py:7-41`、`src/api/routers/knowledge_base.py:356-383` |
| FEAT-STORE-005 | 看排队与处理中的文档任务，并按需删掉 | `/monitor` →「队列监控」页签 | REQ-STORE-008, REQ-STORE-009 | `src/api/routers/monitor.py:32-163`、`frontend/src/views/Monitor.vue:174-233` |
| FEAT-STORE-006 | 看 worker 侧队列统计与外部依赖健康 | `/queue-monitor` 页 | REQ-STORE-010, REQ-STORE-011 | `src/api/routers/health.py:19-173`、`frontend/src/views/QueueMonitor.vue:90-113` |

## 2. 规则

### RULE-STORE-001 全部存储端点要求登录态

- **要求**：`src/api/routers/storage.py` 的 6 个端点均挂 `Depends(get_current_user)`，无 token → 401。
- **适用条件**：全部存储请求。
- **可观察**：不带 `Authorization` 请求 `GET /api/v1/storage/files` → 401。
- **source**：`src/api/routers/storage.py:43-197`
- **requirement_refs**：REQ-STORE-001
- **basis**：observed

### RULE-STORE-002 对象名前缀强制隔离

- **要求**：每次访问都把对象名重写为 `user_{current_user.id}/...`；`_safe_object_name` 先 `replace("..","")` 与 `lstrip("/")`；若已是本人前缀直接返回；若是他人 `user_N` 前缀则先剥掉再拼本人前缀。
- **适用条件**：`/files`、`/download`、`/preview`、`/upload`、`/batch-delete`、`/url`。
- **可观察**：请求 `/storage/download/../other.txt` 仍解析到本人目录；请求带 `user_999/` 前缀的对象名会被改写成 `user_<我>/`，无法读到他人对象。
- **source**：`src/api/routers/storage.py:18-40`
- **requirement_refs**：REQ-STORE-001
- **basis**：observed

### RULE-STORE-003 文件列表的排序与检索在后端完成

- **要求**：`list_files(prefix, sort_by, order, search_query)`；`search_query` 在 `object_name` 上做子串过滤；`sort_by` 支持 `last_modified` / `size` / `name`；`order` 支持升/降。返回项字段 `object_name` / `size` / `last_modified` / `etag`。
- **适用条件**：`GET /storage/files`。
- **可观察**：`?search_query=<子串>` 只返回含该子串的对象；`?sort_by=size&order=asc` 结果按体积升序。
- **source**：`src/services/storage.py:56-88`
- **requirement_refs**：REQ-STORE-001
- **basis**：observed

### RULE-STORE-004 下载以附件流形式返回

- **要求**：`StreamingResponse` 32KB 分块，`media_type="application/octet-stream"`，头 `Content-Disposition: attachment; filename*=UTF-8''<quote(filename)>`，`filename` 取 object_name 最后一段。
- **适用条件**：`GET /storage/download/{object_name:path}` 且对象存在。
- **可观察**：HTTP 200，响应头含 `attachment; filename*=UTF-8''...`；大文件不被一次性读入内存。
- **source**：`src/api/routers/storage.py:62-96`
- **requirement_refs**：REQ-STORE-002
- **basis**：observed

### RULE-STORE-005 前端下载/预览不带鉴权头

- **要求**：现状为前端用 `window.open(url,'_blank')` 与 `<iframe :src="url">` 直连后端 URL，不经 axios 拦截器，因此不携带 `Authorization`；后端强制鉴权 → 401。
- **适用条件**：`frontend/src/views/Monitor.vue` 的下载与预览动作。
- **可观察**：界面点「下载」打开的新标签页显示 401；点「预览」的 iframe 内容为 401 响应体；用 curl 带 token 请求同一 URL 则 200。
- **source**：`frontend/src/views/Monitor.vue:306-315`、`:317-335`、`:137`、`frontend/src/api/index.js:7-13`、`src/api/routers/storage.py:62`、`:98`
- **requirement_refs**：REQ-STORE-002、REQ-STORE-003
- **basis**：observed

### RULE-STORE-006 预览按后缀分派并在临时文件上工作

- **要求**：先把对象分块写入 `tempfile.mkstemp`（无后缀按 `.txt`），再 `get_preview_response(tmp_path, suffix)`；分派：pdf → FileResponse inline；md → markdown + 净化 + 内联 CSS；txt → escape + pre-wrap；docx/doc → 段落/标题/表格转义；xlsx/xls → `pd.read_excel` + `to_html(escape=True)`；其它 → octet-stream + attachment。
- **适用条件**：`GET /storage/preview/{object_name:path}`。
- **可观察**：`.md` 返回 HTML（含内联样式）；`.txt` 返回 `<pre>` 包裹的转义文本；`.unknown` 触发下载而不是渲染。
- **source**：`src/api/routers/storage.py:98-135`、`src/utils/preview_utils.py:56-183`
- **requirement_refs**：REQ-STORE-003
- **basis**：observed

### RULE-STORE-007 HTML 预览经过 bleach 白名单净化

- **要求**：`_sanitize_html` 用 bleach 白名单（h1-h6/p/br/hr/table 系列/pre/code/blockquote/ul/ol/li/strong/em/del/a/img/span/div；`a` 保留 href/title，`img` 保留 src/alt/title），`strip=True`；无 bleach 时退化为正则剥 `script`/`iframe`/`object`/`embed` 与三种 `on*` 写法。
- **适用条件**：`md` 预览路径。
- **可观察**：Markdown 里内嵌的 `<script>alert(1)</script>` 在输出 HTML 中不出现；`<img src=x onerror=...>` 的 `onerror` 被移除。
- **source**：`src/utils/preview_utils.py:12-53`
- **requirement_refs**：REQ-STORE-003
- **basis**：observed

### RULE-STORE-008 预览临时文件不清理

- **要求**：现状为预览端点写完临时文件、返回 `get_preview_response(...)` 之后没有任何 `os.unlink` 或 `finally` 清理逻辑。
- **适用条件**：每次预览。
- **可观察**：连续预览同一文件 N 次，系统临时目录新增 N 个副本文件。
- **source**：`src/api/routers/storage.py:118-135`
- **requirement_refs**：REQ-STORE-003
- **basis**：observed

### RULE-STORE-009 上传文件名清洗与空名拒绝

- **要求**：`safe_filename = filename.replace("..","").replace("/","_").lstrip("\\")`；清洗后为空 → 400 `'Invalid filename'`；对象名为 `user_{id}/{prefix}/{filename}`。
- **适用条件**：`POST /storage/upload`。
- **可观察**：上传文件名 `..%2F..%2Fetc` 被清洗；上传空文件名 → 400。
- **source**：`src/api/routers/storage.py:147-161`
- **requirement_refs**：REQ-STORE-004
- **basis**：observed

### RULE-STORE-010 上传无扩展名与体积限制

- **要求**：现状为 `/storage/upload` 不校验扩展名、不校验文件大小；对比知识库上传有 `MAX_UPLOAD_SIZE = 50MB` 与 10 种扩展名白名单。
- **适用条件**：`POST /storage/upload`。
- **可观察**：上传一个 `.exe` 或 200MB 文件仍返回 200（受反向代理/服务器限制另行约束）。
- **source**：`src/api/routers/storage.py:137-168`、`src/api/routers/knowledge_base.py:143-148`
- **requirement_refs**：REQ-STORE-004
- **basis**：observed

### RULE-STORE-011 MinIO 不可用时写操作抛 RuntimeError

- **要求**：`upload_file` / `delete_file` / `batch_delete_files` 在 `_available` 为 False 时 `raise RuntimeError('MinIO 不可用,无法上传文件')` / `('MinIO 不可用,无法删除文件')`；接口层未捕获 → 500。
- **适用条件**：MinIO 不可达。
- **可观察**：关掉 MinIO 后 `POST /storage/upload` → 500；`POST /storage/batch-delete` → 500。
- **source**：`src/services/storage.py:39-41`、`:113-137`
- **requirement_refs**：REQ-STORE-004、REQ-STORE-006
- **basis**：observed

### RULE-STORE-012 MinIO 不可用时读操作静默返回空

- **要求**：`list_files` 返回 `[]`，`get_file_stream` / `get_file_url` 返回 None，均不抛异常。
- **适用条件**：MinIO 不可达。
- **可观察**：`GET /storage/files` → 200 `{"files": []}`；`GET /storage/download/x` → 404；`GET /storage/url/x` → 404。
- **source**：`src/services/storage.py:56-58`、`:90-98`、`:100-111`
- **requirement_refs**：REQ-STORE-006
- **basis**：observed

### RULE-STORE-013 启动降级不阻断

- **要求**：`storage_service = StorageService()` 在 import 时即建连并 `_ensure_bucket()`；连接用 3 秒超时 + 零重试；失败只 `logger.warning("MinIO 不可用(...),文件存储降级: ...")` 并 `_available=False`。
- **适用条件**：任何进程 import 该模块。
- **可观察**：MinIO 关闭时服务仍能启动；启动日志含"文件存储降级"warning；服务启动耗时不被拖长（约 3 秒内失败）。
- **source**：`src/services/storage.py:7-37`、`:139`
- **requirement_refs**：REQ-STORE-006
- **basis**：observed

### RULE-STORE-014 预签名链接有效期 1 小时

- **要求**：`get_file_url` 用 `presigned_get_object(..., expires=timedelta(hours=1))`。
- **适用条件**：`GET /storage/url/{object_name:path}`。
- **可观察**：返回 URL 的查询串含 3600 秒有效期参数；超时后访问失效。
- **source**：`src/services/storage.py:100-111`
- **requirement_refs**：REQ-STORE-005
- **basis**：observed

### RULE-STORE-015 知识库上传的 MinIO 备份失败只打印

- **要求**：知识库上传先落本地盘，再 try 备份到 MinIO；`except` 里只 `print(f"Failed to upload to MinIO: {e}")`，不影响接口返回。
- **适用条件**：`POST /knowledge-bases/{kb_id}/upload`。
- **可观察**：MinIO 关闭时该上传仍 200，stdout 出现 `Failed to upload to MinIO`，本地磁盘有文件而 `/storage/files` 无该对象。
- **source**：`src/api/routers/knowledge_base.py:356-383`
- **requirement_refs**：REQ-STORE-007
- **basis**：observed

### RULE-STORE-016 队列列表按知识库归属过滤并限 50 条

- **要求**：join `KnowledgeBase` 并过滤 `owner_id == current_user.id`；`order_by(desc(created_at)).limit(50)`；`status_filter` 只认 `processing`/`pending`/`failed` 三个值（分别对应 status 1/0/3）。
- **适用条件**：`GET /api/v1/monitor/`。
- **可观察**：返回条数 ≤ 50；看不到他人知识库的文档；`status_filter=failed` 只返回 status=3。
- **source**：`src/api/routers/monitor.py:32-89`
- **requirement_refs**：REQ-STORE-008
- **basis**：observed

### RULE-STORE-017 task_id 是字符串且可能是 Celery UUID

- **要求**：`task_id = doc.celery_task_id or str(doc.id)`；`QueueItem.task_id` 为字符串。
- **适用条件**：`GET /api/v1/monitor/`。
- **可观察**：走 Celery 的文档 `task_id` 形如 UUID；走同步回落的文档 `task_id` 是数字字符串。
- **source**：`src/api/routers/monitor.py:53`
- **requirement_refs**：REQ-STORE-008、REQ-STORE-009
- **basis**：observed

### RULE-STORE-018 进度由 Celery 状态与本地状态共同决定

- **要求**：`celery_task_id` 存在且 `status==1` 时用 `AsyncResult(...).state` 覆盖状态串，PENDING→10、STARTED→50、SUCCESS|FAILURE→100；否则 `status==1 → 50`、`status==2 → 100`、其它默认 0。`AsyncResult` 查询异常被 `pass` 吞掉。
- **适用条件**：`GET /api/v1/monitor/`。
- **可观察**：RabbitMQ 关闭时进度回落到本地值（50/100），不报错。
- **source**：`src/api/routers/monitor.py:58-74`
- **requirement_refs**：REQ-STORE-008
- **basis**：observed

### RULE-STORE-019 删除任务端点强制 int 转换

- **要求**：路径参数声明为 `str`，内部 `doc_id = int(task_id)`，`ValueError` → 400 `'Invalid ID format'`；不存在 → 404 `'Task/Document not found'`；`kb.owner_id != current_user.id` → 403 `'Not authorized'`。
- **适用条件**：`DELETE /api/v1/monitor/tasks/{task_id}`。
- **可观察**：`DELETE /monitor/tasks/abc-uuid` → 400；`DELETE /monitor/tasks/999999` → 404；删他人知识库的文档 → 403。
- **source**：`src/api/routers/monitor.py:108-132`
- **requirement_refs**：REQ-STORE-009
- **basis**：observed

### RULE-STORE-020 批量删除跳过非法 id

- **要求**：body `{"task_ids": [str, ...]}`；逐个 `int(tid)`，失败的 `pass` 跳过；全部无效返回 `{"message": "No valid IDs provided"}`；逐 doc 校验 kb 归属；返回 `f"Deleted {count} tasks"`。
- **适用条件**：`POST /api/v1/monitor/tasks/batch-delete`。
- **可观察**：`{"task_ids":["abc","def"]}` → 200 `'No valid IDs provided'`；`{"task_ids":["1"]}`（有效）→ `'Deleted 1 tasks'`。
- **source**：`src/api/routers/monitor.py:134-163`
- **requirement_refs**：REQ-STORE-009
- **basis**：observed

### RULE-STORE-021 前端删除传 task_id 导致类型不匹配

- **要求**：现状为前端单条删除 `api.delete(`/monitor/tasks/${row.task_id}`)`、批量删除 `task_ids: selectedQueueItems.map(item => item.task_id)`，传的可能是 UUID 字符串，与后端 `int()` 冲突。
- **适用条件**：`frontend/src/views/Monitor.vue` 的删除动作。
- **可观察**：删除一个走 Celery 的文档 → 400 `'Invalid ID format'`，前端提示"删除失败"；删除走同步回落的文档（task_id 为数字串）→ 200 成功。
- **source**：`frontend/src/views/Monitor.vue:210-233`、`src/api/routers/monitor.py:117-119`
- **requirement_refs**：REQ-STORE-009
- **basis**：observed

### RULE-STORE-022 删除任务不撤销 Celery 任务

- **要求**：删除端点只 `db.delete(doc)` + `commit`，无 `AsyncResult.revoke`、不清 chunk、不清向量。
- **适用条件**：`DELETE /monitor/tasks/{id}` 与批量删除。
- **可观察**：删掉一个 processing 状态的文档后，worker 侧任务仍在跑，chunk 行可能继续写入或残留。
- **source**：`src/api/routers/monitor.py:130`、`:156-160`
- **requirement_refs**：REQ-STORE-009
- **basis**：observed

### RULE-STORE-023 /health/queues 需要鉴权

- **要求**：`async def get_queue_stats(current_user=Depends(get_current_user))`；`GET /api/v1/health` 与 `/health/models` 则不需要鉴权。
- **适用条件**：健康检查端点。
- **可观察**：不带 token 请求 `/health/queues` → 401；请求 `/health` → 200。
- **source**：`src/api/routers/health.py:14-20`、`:155-176`
- **requirement_refs**：REQ-STORE-010、REQ-STORE-011
- **basis**：observed

### RULE-STORE-024 检查器不可用时返回 200 + error 键

- **要求**：`i = celery_app.control.inspect()` 为假时 `return {"error": "Could not connect to Celery inspector"}`（HTTP 200，**无 status 键**）；抛异常时 `return {"status": "error", "message": str(e)}`（HTTP 200）。
- **适用条件**：RabbitMQ 不可达或 worker 未启动。
- **可观察**：两种失败返回的 JSON 结构不同，前端只识别后者。
- **source**：`src/api/routers/health.py:23-25`、`:51-52`
- **requirement_refs**：REQ-STORE-010
- **basis**：observed

### RULE-STORE-025 依赖探测 7 项并发且各自超时

- **要求**：`asyncio.gather` 并发探测 `mcp_monitor` / `mcp_cls` / `rabbitmq` / `redis` / `milvus` / `minio` / `llm`，顺序固定；`overall = "ok"` 仅当 7 项全部 `status=="ok"`，否则 `"degraded"`。超时：http 3s、rabbitmq 3s、redis 3s、milvus 3s、minio 3s、llm 5s。
- **适用条件**：`GET /api/v1/health/dependencies`。
- **可观察**：返回 `services` 长度为 7 且 name 顺序与上述一致；关掉任一依赖后 `overall == "degraded"`。
- **source**：`src/api/routers/health.py:155-173`、`:59-67`
- **requirement_refs**：REQ-STORE-011
- **basis**：observed

### RULE-STORE-026 HTTP 探测口径与 LLM 探测口径不同

- **要求**：`_check_http` 认为"任何 HTTP 响应都算可达，不要求 200"；`_check_llm` 要求 `resp.status == 200`，否则报 `HTTP <code>`。
- **适用条件**：`/health/dependencies` 的各探测器。
- **可观察**：MCP 服务返回 500 时 `_check_http` 仍报 ok；LLM 返回 429 时报 unavailable + `HTTP 429`。
- **source**：`src/api/routers/health.py:59-67`、`:148-150`
- **requirement_refs**：REQ-STORE-011
- **basis**：observed

### RULE-STORE-027 Celery 生产者侧快速失败

- **要求**：`broker_connection_retry=False`、`broker_connection_timeout=4`；任务配置 `task_time_limit=600`、`task_acks_late=True`、`worker_prefetch_multiplier=1`、`task_track_started=True`、序列化 json。
- **适用条件**：任何向 broker 派发的动作。
- **可观察**：RabbitMQ 关闭时派发在约 4 秒内失败而不是长时间重试。
- **source**：`src/worker/celery_app.py:6-25`
- **requirement_refs**：REQ-STORE-012
- **basis**：observed

### RULE-STORE-028 派发 5 秒硬超时回落同步后台

- **要求**：`_try_celery_delay` 用 `ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=5)`；超时抛异常由调用方降级为 `background_tasks.add_task(process_document, doc.id)`，该路径下 `celery_task_id=None`。
- **适用条件**：文档上传后的派发。
- **可观察**：RabbitMQ 关闭时上传响应中 `task_id` 为 null，5 秒内返回，文档仍被处理。
- **source**：`src/api/routers/knowledge_base.py:29-41`、`:125-141`
- **requirement_refs**：REQ-STORE-012
- **basis**：observed

### RULE-STORE-029 MinIO 登录是纯前端模拟

- **要求**：`handleMinioLogin` 只校验 accessKey/secretKey 非空，然后 `localStorage.setItem('minio_auth_status','connected')`，**不发任何网络请求**；`checkMinioAuth` 只读该 localStorage 值。
- **适用条件**：MinIO 页签的登录/登出弹窗。
- **可观察**：打开浏览器 Network 面板点登录，无任何请求；`localStorage` 出现 `minio_auth_status=connected`；清掉 localStorage 后需要再"登录"一次。
- **source**：`frontend/src/views/Monitor.vue:264-283`
- **requirement_refs**：REQ-STORE-001
- **basis**：observed

### RULE-STORE-030 无版本管理端点

- **要求**：现状为 `src/api/routers/storage.py` 与 `src/services/storage.py` 内无任何版本管理路由或 MinIO 版本 API 调用；README 声称的"MinIO 版本管理"不存在。
- **适用条件**：存储模块全部能力。
- **可观察**：`grep -rn "version" src/api/routers/storage.py src/services/storage.py` 无版本管理相关命中。
- **source**：`src/api/routers/storage.py:1-197`、`src/services/storage.py:1-139`
- **requirement_refs**：REQ-STORE-005
- **basis**：observed

## 3. 断言表

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
| --- | --- | --- | --- | --- |
| ASRT-STORE-001 | 不带 `Authorization` 头请求 `GET /api/v1/storage/files` 返回 401 | RULE-STORE-001 | REQ-STORE-001 | observed |
| ASRT-STORE-002 | `GET /api/v1/storage/files` 返回的每个 `object_name` 都以 `user_<当前用户 id>/` 开头 | RULE-STORE-002 | REQ-STORE-001 | observed |
| ASRT-STORE-003 | 请求 `GET /api/v1/storage/download/../secret.txt` 不返回他人对象（清洗后落在本人目录，返回 404 或本人文件） | RULE-STORE-002 | REQ-STORE-001 | observed |
| ASRT-STORE-004 | `GET /api/v1/storage/files?search_query=<子串>` 返回项的 `object_name` 全部含该子串；`?sort_by=size&order=asc` 结果按 size 升序 | RULE-STORE-003 | REQ-STORE-001 | observed |
| ASRT-STORE-005 | `GET /api/v1/storage/download/{存在的对象}` 返回 200，响应头 `Content-Disposition` 含 `attachment` 与 `filename*=UTF-8''` | RULE-STORE-004 | REQ-STORE-002 | observed |
| ASRT-STORE-006 | 用浏览器从界面点「下载」，新标签页返回 401（前端未带 Authorization）；用 curl 带 token 请求同一 URL 返回 200 | RULE-STORE-005 | REQ-STORE-002、REQ-STORE-003 | observed |
| ASRT-STORE-007 | 用浏览器从界面点「预览」，iframe 内显示 401；用 curl 带 token 请求同一 URL 返回 200 且 `Content-Type` 为 `text/html` 或对应类型 | RULE-STORE-005 | REQ-STORE-003 | observed |
| ASRT-STORE-008 | `GET /api/v1/storage/preview/{.md 对象}` 返回的 HTML 中不含 `<script` 子串 | RULE-STORE-007 | REQ-STORE-003 | observed |
| ASRT-STORE-009 | `GET /api/v1/storage/preview/{.txt 对象}` 返回 HTML 含 `<pre`，且原文中的 `<` 被转义为 `&lt;` | RULE-STORE-006 | REQ-STORE-003 | observed |
| ASRT-STORE-010 | 连续预览同一对象 3 次后，系统临时目录下该文件的副本数量增加 3 个（不清理） | RULE-STORE-008 | REQ-STORE-003 | observed |
| ASRT-STORE-011 | `POST /api/v1/storage/upload` 传文件名清洗后为空的文件返回 400，detail 等于 `'Invalid filename'` | RULE-STORE-009 | REQ-STORE-004 | observed |
| ASRT-STORE-012 | `POST /api/v1/storage/upload` 上传一个 `.exe` 文件返回 200（无扩展名白名单） | RULE-STORE-010 | REQ-STORE-004 | observed |
| ASRT-STORE-013 | MinIO 不可用时 `POST /api/v1/storage/upload` 返回 500；`GET /api/v1/storage/files` 返回 200 且 `files` 为空数组 | RULE-STORE-011、RULE-STORE-012 | REQ-STORE-006 | observed |
| ASRT-STORE-014 | MinIO 不可用时后端仍能启动，启动日志含 `文件存储降级` 关键字，且 `/api/v1/health` 返回 200 | RULE-STORE-013 | REQ-STORE-006 | observed |
| ASRT-STORE-015 | `GET /api/v1/storage/url/{存在的对象}` 返回的 URL 在无 token 的客户端可直接 GET 到对象内容 | RULE-STORE-014、RULE-STORE-002 | REQ-STORE-005 | observed |
| ASRT-STORE-016 | MinIO 不可用时上传知识库文档仍返回 200，服务端 stdout 出现 `Failed to upload to MinIO` | RULE-STORE-015 | REQ-STORE-007 | observed |
| ASRT-STORE-017 | `GET /api/v1/monitor/` 返回条数不超过 50，且不含他人知识库下的文档 | RULE-STORE-016 | REQ-STORE-008 | observed |
| ASRT-STORE-018 | `GET /api/v1/monitor/` 返回项的 `task_id` 为字符串；走 Celery 的为 UUID 形态，走同步回落的为纯数字字符串 | RULE-STORE-017 | REQ-STORE-008 | observed |
| ASRT-STORE-019 | `DELETE /api/v1/monitor/tasks/<非数字字符串>` 返回 400，detail 等于 `'Invalid ID format'` | RULE-STORE-019 | REQ-STORE-009 | observed |
| ASRT-STORE-020 | 对走 Celery 的文档从界面点删除 → 前端提示"删除失败"（后端 400）；对同步回落的文档 → 删除成功 | RULE-STORE-021 | REQ-STORE-009 | observed |
| ASRT-STORE-021 | `POST /api/v1/monitor/tasks/batch-delete` body `{"task_ids":["abc","def"]}` 返回 200 且 message 等于 `'No valid IDs provided'` | RULE-STORE-020 | REQ-STORE-009 | observed |
| ASRT-STORE-022 | 删除一个 status=1 的文档后，对应 Celery 任务仍在 worker 侧运行（无 revoke 调用） | RULE-STORE-022 | REQ-STORE-009 | observed |
| ASRT-STORE-023 | 不带 token 请求 `GET /api/v1/health/queues` 返回 401；请求 `GET /api/v1/health` 返回 200 | RULE-STORE-023 | REQ-STORE-010 | observed |
| ASRT-STORE-024 | RabbitMQ 关闭时 `GET /api/v1/health/queues` 返回 HTTP 200 且响应体为 `{"error": "Could not connect to Celery inspector"}`（无 `status` 键） | RULE-STORE-024 | REQ-STORE-010 | observed |
| ASRT-STORE-025 | `GET /api/v1/health/dependencies` 返回的 `services` 长度等于 7，name 顺序为 mcp_monitor/mcp_cls/rabbitmq/redis/milvus/minio/llm | RULE-STORE-025 | REQ-STORE-011 | observed |
| ASRT-STORE-026 | 关掉 MinIO 后 `/health/dependencies` 中 `minio.status == "unavailable"` 且 `overall == "degraded"` | RULE-STORE-025 | REQ-STORE-011 | observed |
| ASRT-STORE-027 | 界面点 MinIO「登录」时浏览器 Network 面板无新请求，`localStorage.minio_auth_status` 变为 `connected` | RULE-STORE-029 | REQ-STORE-001 | observed |
| ASRT-STORE-028 | `grep -rn "version" src/api/routers/storage.py src/services/storage.py` 无版本管理相关命中，确认无版本端点 | RULE-STORE-030 | REQ-STORE-005 | observed |
| ASRT-STORE-029 | RabbitMQ 关闭时上传文档的响应中 `task_id` 为 null，且请求在 6 秒内返回 | RULE-STORE-028 | REQ-STORE-012 | observed |
| ASRT-STORE-030 | `grep -n "broker_connection_retry" src/worker/celery_app.py` 命中值为 `False`，`broker_connection_timeout` 为 `4` | RULE-STORE-027 | REQ-STORE-012 | observed |

## 4. 未决

- SPEC_GAP-1：前端下载/预览 401 的修法未定（RULE-STORE-005 只记录现状）。已登记 `specs/questions.md` Q-09。
- SPEC_GAP-2：队列删除的 `task_id` 类型契约应为 UUID 还是数字 id 未定（RULE-STORE-017、RULE-STORE-021）。已登记 Q-10。
- SPEC_GAP-3：README 的"MinIO 版本管理"应删除还是应实现（RULE-STORE-030 记录"不存在"）。已登记文档冲突。
- SPEC_GAP-4：前端"MinIO 登录"交互应下线还是接真实凭证（RULE-STORE-029）。
- SPEC_GAP-5：`/health/queues` 两种失败返回结构不一致，应统一为哪种（RULE-STORE-024）。
- SPEC_GAP-6：预览临时文件清理、上传扩展名/体积限制、删除任务是否应 revoke，三项均需产品定性（RULE-STORE-008、RULE-STORE-010、RULE-STORE-022）。
- 未核实：MinIO/RabbitMQ/Redis/Milvus/LLM 的真实在线状态、`/health/dependencies` 的实际返回、compose 中 minio 镜像与 settings 默认值的匹配性（本次只读源码，不联网）。
