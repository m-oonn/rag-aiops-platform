# spec · evaluation（评测）

- 模块：`evaluation`，规则前缀 `RULE-EVAL-`，断言前缀 `ASRT-EVAL-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 需求依据：`requirements/modules/evaluation.md`（REQ-EVAL-001 ~ REQ-EVAL-010）
- 断言被 `cases/evaluation.json` 的 `assertion_id` 引用。**断言只描述可判定的观察点。**
- 所有 `source` 均为 `完整相对路径:行号`。全部 `basis=observed`（无产品决定文档支撑，故无 `confirmed`）。

---

## 1. 交互与接口状态

链路名 `FLOW-EVAL`（建任务 → 数据集就绪 → 执行 → 报告），图见 `requirements/modules/evaluation.md` §1。

### 1.1 入口清单（前端 → 接口）

| 用户动作 | 页面/元素 | 接口 | 方法 | source |
|---|---|---|---|---|
| 新建评测（非 custom） | `/evaluation` →「新建评测」→「开始生成」 | `/api/v1/evaluations/generate` | POST | `frontend/src/views/Evaluation.vue:271-295`、`src/api/routers/evaluation.py:283` |
| 新建 + 上传自定义集 | 同上，勾选自定义数据集 | `/generate` + `/evaluations/{task_id}/upload-dataset` | POST ×2 | `frontend/src/views/Evaluation.vue:276-281`、`src/api/routers/evaluation.py:337` |
| 看历史列表 |「历史与报告」Tab（5000ms 轮询） | `/api/v1/evaluations/tasks` | GET | `frontend/src/views/Evaluation.vue:395-405,441-445`、`src/api/routers/evaluation.py:484` |
| 看数据集 | 行内「查看数据集」（仅 status=4 可点） | `/api/v1/evaluations/{task_id}/dataset` | GET | `frontend/src/views/Evaluation.vue:183-184,297-307`、`src/api/routers/evaluation.py:405` |
| 改一条题 | 弹窗内「保存」 | `/api/v1/evaluations/dataset-items/{item_id}` | PUT | `frontend/src/views/Evaluation.vue:309-332`、`src/api/routers/evaluation.py:417` |
| 删一条题 | 弹窗内删除 | `/api/v1/evaluations/dataset-items/{item_id}` | DELETE | `frontend/src/views/Evaluation.vue:333-342`、`src/api/routers/evaluation.py:438` |
| 运行评测 | 弹窗底部「确认并运行评测」（仅 status=4 显示） | `/api/v1/evaluations/{task_id}/run` | POST | `frontend/src/views/Evaluation.vue:191,344-358`、`src/api/routers/evaluation.py:387` |
| 看报告 | 行内「查看报告」 | `/api/v1/evaluations/{task_id}/report` | GET | `frontend/src/views/Evaluation.vue:407-416`、`src/api/routers/evaluation.py:514` |
| 下载报告 | 报告弹窗「下载报告」（**前端 Blob，不走后端**） | — | — | `frontend/src/views/Evaluation.vue:418-426` |
| 批量删除任务 | 工具栏「批量删除」 | `/api/v1/evaluations/tasks/batch-delete` | DELETE（body 为裸数组） | `frontend/src/views/Evaluation.vue:360-371`、`src/api/routers/evaluation.py:460` |
| 单任务详情 | （前端未调用） | `/api/v1/evaluations/{task_id}` | GET | `src/api/routers/evaluation.py:501` |

统一前缀 `/api/v1`（`src/settings.py:12`），挂载点 `src/main.py:264`。10 个端点**全部** `Depends(get_current_user)`。

### 1.2 状态迁移（`evaluation_tasks.status`）

| 起点 | 触发 | 终点 | source |
|---|---|---|---|
| — | 建任务 | `0` Pending | `src/api/routers/evaluation.py:316-323` |
| 0 | 生成任务成功收尾 | `4` DatasetGenerated | `src/api/routers/evaluation.py:151-154` |
| 0 | 自定义集上传成功 | `4` | `src/api/routers/evaluation.py:379-380` |
| 0 | 生成外层异常 | `3` + error_msg | `src/api/routers/evaluation.py:156-161` |
| 0 | 无文档可取 | `3` + `No documents found` | `src/api/routers/evaluation.py:104-108` |
| 4 | 执行入口 | `1` Running | `src/api/routers/evaluation.py:171-172` |
| 1 | 报告写完 | `2` Completed | `src/api/routers/evaluation.py:268-269` |
| 1 | 执行外层异常 | `3` + error_msg | `src/api/routers/evaluation.py:272-277` |

顺序是 **0 → 4 → 1 → 2**；`4` 在语义上早于 `1`。前端 `EVAL_TEXT_MAP` 无 `4` 的文案（`frontend/src/utils/status.js:36`）。

### 1.3 数据落点

| 数据 | 位置 | source |
|---|---|---|
| 任务 | `evaluation_tasks` | `src/database/models.py:123-141` |
| 每题结果 | `evaluation_results`（`metrics` 为 JSON） | `src/database/models.py:144-156` |
| 数据集条目 | `evaluation_dataset_items` | `src/database/models.py:158-167` |
| 报告 | `data/reports/eval_{task_id}.md`（**相对路径**） | `src/api/routers/evaluation.py:263-266` |

### 1.4 功能单元（FEAT-EVAL-\*，供 `cases/evaluation.json` 的 `feature_id` 解析）

| ID | 功能单元（用户视角） | 入口 | requirement_refs | source |
|---|---|---|---|---|
| FEAT-EVAL-001 | 选知识库、定题量、开始生成一次评测 | `/evaluation` →「新建评测」→「开始生成」 | REQ-EVAL-001 | `frontend/src/views/Evaluation.vue:271-295`、`src/api/routers/evaluation.py:283-335` |
| FEAT-EVAL-002 | 等数据集自动生成（真实调模型出题，按比例分三类） | 同一入口的异步阶段 | REQ-EVAL-002, REQ-EVAL-003 | `src/api/routers/evaluation.py:79-163`、`src/services/qa_generator.py:10-57` |
| FEAT-EVAL-003 | 拿自己的题库跑评测（上传 JSON/CSV/XLSX 或逐条改删） | 勾选自定义数据集 / 数据集弹窗 | REQ-EVAL-004, REQ-EVAL-005 | `src/api/routers/evaluation.py:337-458`、`frontend/src/views/Evaluation.vue:297-342` |
| FEAT-EVAL-004 | 逐题跑真实 RAG 再打分，跑到一半能看进度 | 数据集弹窗「确认并运行评测」 | REQ-EVAL-006 | `src/api/routers/evaluation.py:165-279,387-403` |
| FEAT-EVAL-005 | 拿一份 Markdown 报告，四个维度分数 + 延迟分位数 | 行内「查看报告」/「下载报告」 | REQ-EVAL-007, REQ-EVAL-008 | `src/services/evaluator.py:11-141`、`src/api/routers/evaluation.py:514-532` |
| FEAT-EVAL-006 | 管理历史任务（列表 / 批量删除 / 状态与进度） |「历史与报告」Tab | REQ-EVAL-009, REQ-EVAL-010 | `src/api/routers/evaluation.py:460-512`、`frontend/src/views/Evaluation.vue:395-405` |

---

## 2. 规则

### RULE-EVAL-001 非 custom 建任务的三道前置门，顺序与文案固定
- **要求**：`POST /generate` 非 custom 时必须依次判定：库不存在 → 404 `知识库不存在`；非 owner → 403 `无权操作该知识库`；无 `status==2 且 chunk_count>0` 的文档 → 400 `知识库为空或文档尚未处理完成，请先上传文档并等待处理完成`。建任务前不得产生任何行。
- **适用条件**：`is_custom_upload=false`。
- **可观察**：三种输入分别返回 404 / 403 / 400，detail 与上述中文串一致；`evaluation_tasks` 行数不变。
- **source**：`src/api/routers/evaluation.py:292-306`
- **requirement_refs**：REQ-EVAL-001　**basis**：observed

### RULE-EVAL-002 任务名由服务端拼接，含时间戳
- **要求**：名称必须是 `Eval-{kb.name}-{num_questions}-{时间戳}`；custom 为 `Eval-Custom-{num_questions}-{时间戳}`。客户端不能自定义名称。
- **适用条件**：所有 `/generate`。
- **可观察**：返回体 `name` 以 `Eval-` 或 `Eval-Custom-` 开头，且含请求里的 `num_questions` 数字。
- **source**：`src/api/routers/evaluation.py:310,314`
- **requirement_refs**：REQ-EVAL-001　**basis**：observed

### RULE-EVAL-003 后端不校验 num_questions / num_docs / ratios
- **要求**：`EvalConfig` 对 `num_questions`、`num_docs`、`ratios` 均无上下界与和校验；`num_questions=0` 或负数不得被接口拒绝。
- **适用条件**：所有 `/generate`。
- **可观察**：`num_questions=0` 返回 200（任务被创建）；`ratios` 和 ≠ 1 也返回 200。
- **注意**：前端有界（5–2000、1–50）且比例和不等于 1 只弹警告不阻止提交（`frontend/src/views/Evaluation.vue:85-92,256-261`）——**接口契约与前端约束不一致，断言只按接口写**。
- **source**：`src/api/routers/evaluation.py:44-52`、`frontend/src/views/Evaluation.vue:65-92`
- **requirement_refs**：REQ-EVAL-001　**basis**：observed

### RULE-EVAL-004 题目数量按 ceil 分配，超出从 single_hop 扣，不足不补
- **要求**：`targets[qa_type] = ceil(num_questions * ratio)`；若总和超 `num_questions`，从 `single_hop` 减；若总和不足 `num_questions`，**不得补足**。
- **适用条件**：非 custom 生成。
- **可观察**：默认比例、`num_questions=10` → 目标 7/2/1；比例全为 0.1、`num_questions=10` → 目标各 1、总目标 3（最终 `total_count` 由实际落库条数决定，可能 ≤ 3）。
- **source**：`src/api/routers/evaluation.py:111-114,148-154`
- **requirement_refs**：REQ-EVAL-002　**basis**：observed

### RULE-EVAL-005 出题必须真实调用 LLM，且失败不阻断整个任务
- **要求**：题目文本来自 `llm_client.generate_custom_response`，不得由模板拼接；单类出题失败（返回 `[]`）只跳过该类，任务仍以 `status=4` 结束。
- **适用条件**：非 custom 生成。
- **可观察**：同类比例下换不同文档，生成的 `question` 文本不同；故障注入让 LLM 返回不可解析内容时，任务 `status=4` 且该类题目条数为 0（不是 `status=3`）。
- **source**：`src/services/qa_generator.py:10-57`、`src/api/routers/evaluation.py:123-154`
- **requirement_refs**：REQ-EVAL-003　**basis**：observed

### RULE-EVAL-006 出题遇到无 chunk 的文档时用占位字符串
- **要求**：`get_doc_text` 取该文档前 5 条 `DocumentChunk.content` 拼接；无 chunk 时回退为 `Document content for {doc.filename}`。
- **适用条件**：非 custom 生成，且被抽中的文档没有 chunk。
- **可观察**：构造一个 `status=2`、`chunk_count=0` 的文档，其生成题目的 prompt 输入即为该占位串（题目内容与文档正文无关）。
- **source**：`src/api/routers/evaluation.py:116-119`
- **requirement_refs**：REQ-EVAL-003　**basis**：observed

### RULE-EVAL-007 上传自定义集：三种扩展名，无白名单兜底
- **要求**：仅按 `filename.endswith('.json'/'.csv'/'.xlsx')` 分支；其它扩展名不得报错，`items` 为空时仍把 `status` 置 4 并返回 `Uploaded 0 items`。
- **适用条件**：`POST /{task_id}/upload-dataset`。
- **可观察**：传 `.txt` → **200** 且 `message == "Uploaded 0 items"`、任务 `status==4`；传坏 JSON → **400** detail 前缀 `Invalid file:`。
- **source**：`src/api/routers/evaluation.py:357-385`
- **requirement_refs**：REQ-EVAL-004　**basis**：observed

### RULE-EVAL-008 自定义集列映射：answer 优先，回退 ground_truth
- **要求**：每行取 `question`、`answer` 或 `ground_truth`（`answer` 优先）、`type`（缺省 `single_hop`）。
- **适用条件**：CSV/XLSX 解析路径。
- **可观察**：CSV 同时含 `answer=a` 与 `ground_truth=b` 两列时，落库 `ground_truth` 字段值为 `a`；只含 `ground_truth` 时取 `b`。
- **source**：`src/api/routers/evaluation.py:361-368`
- **requirement_refs**：REQ-EVAL-004　**basis**：observed

### RULE-EVAL-009 重复上传叠加数据行但覆盖 total_count
- **要求**：`upload-dataset` 只 `db.add` 新条目，不删旧条目；随后无条件把 `task.total_count` 设为本次条数。
- **适用条件**：同一 custom 任务被上传两次及以上。
- **可观察**：第一次 5 条、第二次 3 条 → `GET /{task_id}/dataset` 返回 **8** 条，而任务 `total_count` 为 **3**。
- **source**：`src/api/routers/evaluation.py:370-380`
- **requirement_refs**：REQ-EVAL-004, REQ-EVAL-009　**basis**：observed

### RULE-EVAL-010 数据集条目端点只校验登录态，不校验任务归属
- **要求**：`PUT/DELETE /dataset-items/{item_id}` 按 item 存在与否返回 404/成功，**不得**调用 `_check_task_ownership`；`GET /{task_id}/dataset` 同样只校验登录态。
- **适用条件**：任意登录用户持有他人 `item_id` / `task_id`。
- **可观察**：用户 B 对用户 A 的 `item_id` 发 `PUT` → **非 403**（成功 200 或 404），与 `POST /{task_id}/run`（会 403）形成对照。
- **说明**：这正是待确认的越权风险点，用例以 `static_review` 记录，判为现状而非应有行为。
- **source**：`src/api/routers/evaluation.py:405-458,27-42`
- **requirement_refs**：REQ-EVAL-005　**basis**：observed

### RULE-EVAL-011 删条目改 total_count 但不改 status
- **要求**：`DELETE /dataset-items/{item_id}` 成功后 `task.total_count = max(0, total_count-1)`，不得改动 `status`。
- **适用条件**：任意 `status` 下删条目。
- **可观察**：把 `status=4` 的任务的全部条目逐条删光 → `total_count` 归 0，`status` 仍为 4；此时 `POST /run` 仍返回 200（不是 400），但不会产生任何结果行。
- **source**：`src/api/routers/evaluation.py:438-458,387-403`
- **requirement_refs**：REQ-EVAL-005, REQ-EVAL-010　**basis**：observed

### RULE-EVAL-012 执行入口只接受 status=4
- **要求**：`task.status != 4` 一律 **400** `Dataset not ready`；任务不存在 404 `Task not found`；非 owner 403。
- **适用条件**：`POST /{task_id}/run`。
- **可观察**：对 `status=0/1/2/3` 的任务调 run，均返回 400 且 detail 等于 `Dataset not ready`。
- **source**：`src/api/routers/evaluation.py:387-403`
- **requirement_refs**：REQ-EVAL-006　**basis**：observed

### RULE-EVAL-013 评测执行走 BackgroundTasks，不是 Celery
- **要求**：`/run` 必须通过 `background_tasks.add_task(run_evaluation_execution, ...)` 派发；不得调用 Celery `delay()`；`/generate` 的非 custom 分支同理。
- **适用条件**：`/run`、`/generate`。
- **可观察**：响应立即返回 `{"message":"Evaluation started"}`；随后任务 `status` 在**同一 API 进程内**变为 1/2；broker 全关时行为完全不变（不受 Celery/RabbitMQ 影响）。
- **source**：`src/api/routers/evaluation.py:329,402`
- **requirement_refs**：REQ-EVAL-006, REQ-EVAL-001　**basis**：observed

### RULE-EVAL-014 每题固定 top_k=5 调 RAG
- **要求**：`rag_service.query(item.question, top_k=5, kb_ids=[kb_id] if kb_id else None)` —— `top_k` 硬编码 5，custom 任务传 `kb_ids=None`。
- **适用条件**：所有评测执行。
- **可观察**：无论知识库或助手配置如何，评测的检索条数恒为 5（对比 `/chat` 可传 `top_k`）。
- **source**：`src/api/routers/evaluation.py:199`
- **requirement_refs**：REQ-EVAL-006　**basis**：observed

### RULE-EVAL-015 打分是本模块自研 prompt，四维固定，无 Recall
- **要求**：`RAGEvaluator.evaluate` 的 prompt 必须恰好包含 `faithfulness/relevancy/context_precision/accuracy` 四维、每维 0–10 分，并要求输出 JSON；**不得**引入 ragas 库，**不得**出现 recall 维度。
- **适用条件**：所有评测打分。
- **可观察**：`grep -r "ragas" src/` 为空；成功结果行的 `metrics.scores` 键集合为上述四维（可能因解析失败而缺失，见 RULE-EVAL-016）。
- **source**：`src/services/evaluator.py:11-47`
- **requirement_refs**：REQ-EVAL-007　**basis**：observed

### RULE-EVAL-016 打分解析用贪婪正则，失败静默返回 error 字典
- **要求**：解析必须是 `re.search(r'\{.*\}', response, re.DOTALL)` + `json.loads`；无匹配返回 `{"error": "Failed to parse evaluation JSON"}`，异常返回 `{"error": str(e)}`；**调用方不得检查 `error` 键**。
- **适用条件**：所有评测打分。
- **可观察**：让 LLM 返回两段 JSON（`{..} 说明 {..}`）→ 该题 `evaluation_results.metrics` 中**没有** `scores` 键，但仍产出结果行且 `completed_count` 递增；任务最终仍 `status=2`。
- **source**：`src/services/evaluator.py:48-61`、`src/api/routers/evaluation.py:202-244`
- **requirement_refs**：REQ-EVAL-007, REQ-EVAL-006　**basis**：observed

### RULE-EVAL-017 accuracy 不进报告汇总
- **要求**：`generate_summary_report` 的均值计算只覆盖 `faithfulness`/`relevancy`/`context_precision`/`overall_score`；报告正文不得出现 Accuracy 列。
- **适用条件**：所有已完成任务。
- **可观察**：报告字符串中 `accuracy` 不作为表头或统计行出现（仅可能出现在"典型案例"的原始摘要文本里）；四维分数中只有三维被平均。
- **source**：`src/services/evaluator.py:70-73,98-140`
- **requirement_refs**：REQ-EVAL-007, REQ-EVAL-008　**basis**：observed

### RULE-EVAL-018 报告写相对路径，接口读磁盘，缺文件 404
- **要求**：`report_path` 必须是相对路径 `data/reports/eval_{task.id}.md`；`GET /{task_id}/report` 在 `report_path` 为空或文件不存在时返回 **404** `Report not found`，否则返回 `{"content": <文件全文>}`。
- **适用条件**：任务已 `status=2`。
- **可观察**：删掉磁盘上的报告文件后再请求 → 404 detail `Report not found`；正常时 `content` 以 `# RAG 系统评测分析汇总报告` 开头。
- **source**：`src/api/routers/evaluation.py:263-269,514-532`
- **requirement_refs**：REQ-EVAL-008　**basis**：observed

### RULE-EVAL-019 报告落盘但删除任务不清理报告文件
- **要求**：批量删除任务只删 `evaluation_results` / `evaluation_dataset_items` / `evaluation_tasks`，**不得** `os.remove` 报告文件。
- **适用条件**：`DELETE /tasks/batch-delete`。
- **可观察**：删除一个 `status=2` 的任务后，`data/reports/eval_{id}.md` **仍然存在**。
- **source**：`src/api/routers/evaluation.py:460-482`
- **requirement_refs**：REQ-EVAL-009　**basis**：observed

### RULE-EVAL-020 任务列表用 or_ 双条件，删除逐个校验并静默跳过
- **要求**：`GET /tasks` 过滤条件为 `or_(KnowledgeBase.owner_id == 当前用户, EvaluationTask.created_by == 当前用户)`；`DELETE /tasks/batch-delete` 对无权任务 `continue` 跳过，不得整体 403。
- **适用条件**：任意登录用户。
- **可观察**：B 的列表不含 A 的任何任务；B 提交 `[A的任务id, B的任务id]` → 返回 `Deleted 1 tasks`（成功 200，不是 403/400），A 的任务仍在。
- **source**：`src/api/routers/evaluation.py:460-499`
- **requirement_refs**：REQ-EVAL-009　**basis**：observed

### RULE-EVAL-021 批量删除 body 是裸 int 数组
- **要求**：`DELETE /evaluations/tasks/batch-delete` 的请求体必须是 JSON **数组**（`List[int]`），不是 `{"task_ids": [...]}` 对象。
- **适用条件**：所有批量删除调用。
- **可观察**：发 `{"task_ids":[1]}` → **422**；发 `[1]` → 200。
- **source**：`src/api/routers/evaluation.py:462`、`frontend/src/views/Evaluation.vue:364`
- **requirement_refs**：REQ-EVAL-009　**basis**：observed

### RULE-EVAL-022 权限判定三档
- **要求**：`_check_task_ownership` 必须按 `task.kb_id` 是否为空分流：非空比 `kb.owner_id`（kb 不存在也算不匹配），为空比 `task.created_by`；不匹配一律 403 `无权操作该评估任务`。
- **适用条件**：`/generate`(库维度)、`/upload-dataset`、`/run`、批量删除。
- **可观察**：B 对 A 的 custom 任务调 `/run` → 403 detail `无权操作该评估任务`；对 A 的 kb 任务调 `/run` → 同一 403。
- **source**：`src/api/routers/evaluation.py:27-42,347,397,472-473`
- **requirement_refs**：REQ-EVAL-009, REQ-EVAL-004　**basis**：observed

### RULE-EVAL-023 状态五态与前端文案缺口
- **要求**：`status` 取值只能是 0/1/2/3/4；`4` 表示"数据集就绪"且发生在 `1` 之前；前端 `EVAL_TEXT_MAP` 不提供 4 的文案。
- **适用条件**：全生命周期。
- **可观察**：新建非 custom 任务在生成完成后 `status==4`（而非 2）；前端状态标签对 4 显示 `未知`。
- **source**：`src/database/models.py:130`、`frontend/src/utils/status.js:13,36-40`
- **requirement_refs**：REQ-EVAL-010　**basis**：observed

### RULE-EVAL-024 进度只能靠 completed_count/total_count 轮询
- **要求**：系统不得提供评测进度的推送通道（无 WS/SSE）；前端必须每 5000ms 且仅在「历史与报告」Tab 激活时轮询 `GET /tasks`；进度百分比 = `round(completed/total*100)`，`total==0` 时为 0。
- **适用条件**：所有运行中任务。
- **可观察**：Network 面板在 history Tab 可见约 5 秒一次 `/tasks` 请求；切到「新建评测」Tab 后轮询停止。
- **source**：`frontend/src/views/Evaluation.vue:428-431,441-445`、`frontend/src/composables/usePolling.js:9`
- **requirement_refs**：REQ-EVAL-010　**basis**：observed

### RULE-EVAL-025 失败原因不对外暴露
- **要求**：`EvalTaskOut` 不得包含 `error_msg`；失败任务的唯一对外信号是 `status=3`。
- **适用条件**：任意失败任务。
- **可观察**：`GET /tasks` 与 `GET /{task_id}` 的响应键集合中**没有** `error_msg`；数据库里该字段非空。
- **source**：`src/api/routers/evaluation.py:54-64,501-512`、`src/database/models.py:137`
- **requirement_refs**：REQ-EVAL-010　**basis**：observed

### RULE-EVAL-026 单题失败可跳过，任务不算失败
- **要求**：逐题循环内的异常只写该题 `error_msg` 并 `print`，不得把任务置 3；只有外层异常才置 3。
- **适用条件**：执行阶段。
- **可观察**：让某一道题的 RAG 调用抛错 → 该题有一条 `evaluation_results` 行且 `error_msg` 非空，`metrics` 无 `scores`；任务最终 `status=2`，`completed_count` 仍递增。
- **source**：`src/api/routers/evaluation.py:216-248`
- **requirement_refs**：REQ-EVAL-006　**basis**：observed

### RULE-EVAL-027 报告取前 3 条做典型案例且分位数表独立拼接
- **要求**：`## 4. 典型案例分析` 固定取 `eval_results[:3]`；延迟分位数表使用 `[50,60,70,80,90,95]` 且仅在存在非零延迟时追加。
- **适用条件**：`status=2` 的任务。
- **可观察**：10 题全部成功时报告"典型案例"恰 3 条；若所有题的 `first_token_latency`/`total_latency` 都是 0（如 metrics 缺失），报告中没有分位数表。
- **source**：`src/services/evaluator.py:100-135`、`src/api/routers/evaluation.py:213-214,254-261`
- **requirement_refs**：REQ-EVAL-008　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
|---|---|---|---|---|
| ASRT-EVAL-001 | `POST /evaluations/generate` 传不存在的 `kb_id` → **404** detail `知识库不存在`；传他人库 → **403** detail `无权操作该知识库`；传自己但无就绪文档的库 → **400** detail 含 `知识库为空或文档尚未处理完成` | RULE-EVAL-001 | REQ-EVAL-001 | observed |
| ASRT-EVAL-002 | 成功建任务返回 200，`name` 以 `Eval-` 开头且含请求的 `num_questions`；custom 时以 `Eval-Custom-` 开头 | RULE-EVAL-002 | REQ-EVAL-001 | observed |
| ASRT-EVAL-003 | `num_questions=0` 或 `ratios={"single_hop":0.3,"multi_hop":0.3,"error":0.0}` → **200**（不被 422 拒绝） | RULE-EVAL-003 | REQ-EVAL-001 | observed |
| ASRT-EVAL-004 | 默认 `num_questions=10`、默认 ratios，生成成功后 `evaluation_dataset_items` 的 `qa_type` 计数为 `single_hop≈7 / multi_hop≈2 / error≈1`（允许因 LLM 失败少题），且 `total_count` 等于实际行数 | RULE-EVAL-004 | REQ-EVAL-002 | observed |
| ASRT-EVAL-005 | 同一文档、同一 `num_questions`，两次生成的 `question` 文本不相同（证明非模板固定输出） | RULE-EVAL-005 | REQ-EVAL-003 | observed |
| ASRT-EVAL-006 | 用故障注入让出题 LLM 恒返回非 JSON 文本 → 任务最终 `status=4`（**不是 3**），且数据集行数为 0 | RULE-EVAL-005 | REQ-EVAL-003 | observed |
| ASRT-EVAL-007 | `POST /{task_id}/upload-dataset` 上传 `.txt` → **200**，message 等于 `Uploaded 0 items`，任务 `status==4` | RULE-EVAL-007 | REQ-EVAL-004 | observed |
| ASRT-EVAL-008 | 上传语法错误的 `.json` → **400**，detail 以 `Invalid file:` 开头 | RULE-EVAL-007 | REQ-EVAL-004 | observed |
| ASRT-EVAL-009 | 上传含 `answer` 与 `ground_truth` 两列的 CSV → 落库 `ground_truth` 等于 `answer` 列的值（answer 优先） | RULE-EVAL-008 | REQ-EVAL-004 | observed |
| ASRT-EVAL-010 | 同一 custom 任务上传 5 条后再上传 3 条 → `GET /{task_id}/dataset` 返回 **8** 条，任务 `total_count` 为 **3** | RULE-EVAL-009 | REQ-EVAL-004, REQ-EVAL-009 | observed |
| ASRT-EVAL-011 | 用户 B 对用户 A 的 `item_id` 发 `PUT /dataset-items/{id}`，响应状态码**不是 403**（200 或 404） | RULE-EVAL-010 | REQ-EVAL-005 | observed |
| ASRT-EVAL-012 | 把 `status=4` 任务的条目逐条删光 → `total_count==0`、`status` 仍为 **4**；再调 `POST /run` 返回 **200** 且 `evaluation_results` 不新增行 | RULE-EVAL-011 | REQ-EVAL-005, REQ-EVAL-010 | observed |
| ASRT-EVAL-013 | 对 `status=0` 的任务调 `POST /{task_id}/run` → **400** detail `Dataset not ready`；`status=4` → **200** detail/message `Evaluation started` | RULE-EVAL-012 | REQ-EVAL-006 | observed |
| ASRT-EVAL-014 | 断开 RabbitMQ/Redis（故障注入）后调 `POST /run`，响应与 `status` 推进**与断开前完全一致**（证明不依赖 Celery） | RULE-EVAL-013 | REQ-EVAL-006 | observed |
| ASRT-EVAL-015 | 执行 1 道题时，`evaluation_results.metrics` 中 `first_token_latency`/`total_latency` 为数值（或缺失），且 `top_k` 恒为 5 —— 通过对比 `/chat` 传 `top_k=20` 时的检索条数差异旁证 | RULE-EVAL-014 | REQ-EVAL-006 | observed |
| ASRT-EVAL-016 | 成功评测的结果行 `metrics` 含 `scores` 与 `qa_type`，`scores` 键集合为 `{faithfulness, relevancy, context_precision, accuracy}`（无 `recall`） | RULE-EVAL-015 | REQ-EVAL-007 | observed |
| ASRT-EVAL-017 | 对 `src/` 做 `grep -r "ragas"` → **无匹配**；`grep -rn "recall"` 在评测相关文件里**无** recall 维度 | RULE-EVAL-015 | REQ-EVAL-007 | observed |
| ASRT-EVAL-018 | 故障注入让打分 LLM 返回两段 JSON（`{...} 说明 {...}`）→ 该题结果行存在但 `metrics` 无 `scores`，任务最终 `status=2`、`completed_count` 仍递增 | RULE-EVAL-016 | REQ-EVAL-007, REQ-EVAL-006 | observed |
| ASRT-EVAL-019 | 一份 10 题全部成功的报告正文**不含** `Accuracy` 作为章节/表头；均值区只出现忠实度/相关性/上下文精度/综合分四项 | RULE-EVAL-017 | REQ-EVAL-007, REQ-EVAL-008 | observed |
| ASRT-EVAL-020 | 删除磁盘上 `data/reports/eval_{id}.md` 后 `GET /{task_id}/report` → **404** detail `Report not found`；文件存在时 `content` 以 `# RAG 系统评测分析汇总报告` 开头 | RULE-EVAL-018 | REQ-EVAL-008 | observed |
| ASRT-EVAL-021 | 删除一个 `status=2` 的任务成功后，`data/reports/eval_{id}.md` **仍然存在** | RULE-EVAL-019 | REQ-EVAL-009 | observed |
| ASRT-EVAL-022 | 用户 B 提交 `[A的任务id, B的任务id]` → **200**，body 为 `Deleted 1 tasks`；A 的任务仍在 | RULE-EVAL-020 | REQ-EVAL-009 | observed |
| ASRT-EVAL-023 | `DELETE /evaluations/tasks/batch-delete` body 为 `{"task_ids":[1]}` → **422**；body 为 `[1]` → 200 | RULE-EVAL-021 | REQ-EVAL-009 | observed |
| ASRT-EVAL-024 | 用户 B 对用户 A 的 custom 任务调 `POST /{task_id}/run` → **403** detail `无权操作该评估任务` | RULE-EVAL-022 | REQ-EVAL-009, REQ-EVAL-004 | observed |
| ASRT-EVAL-025 | 非 custom 任务在生成完成后 `GET /{task_id}` 的 `status` 为 **4**；前端状态标签文本为 `未知`（`EVAL_TEXT_MAP` 无 4） | RULE-EVAL-023 | REQ-EVAL-010 | observed |
| ASRT-EVAL-026 | `GET /tasks` 响应项**不含** `error_msg` 键；对一个 `status=3` 的任务，接口只暴露状态码 3 | RULE-EVAL-025 | REQ-EVAL-010 | observed |
| ASRT-EVAL-027 | 让某一道题的 RAG 调用抛错 → 该题结果行 `error_msg` 非空、无 `scores`；任务最终 `status=2`（不是 3） | RULE-EVAL-026 | REQ-EVAL-006 | observed |
| ASRT-EVAL-028 | 在 `/evaluation` 页切到「历史与报告」Tab，5 秒内至少发出 2 次 `GET /evaluations/tasks`；切到「新建评测」Tab 后 10 秒内 `/tasks` 请求数为 0 | RULE-EVAL-024 | REQ-EVAL-010 | observed |
| ASRT-EVAL-029 | 10 题全部成功的报告「典型案例分析」恰含 3 条题目；若所有题延迟都为 0，报告中没有 P50–P95 分位数表 | RULE-EVAL-027 | REQ-EVAL-008 | observed |
| ASRT-EVAL-030 | 未登录（无 Authorization 头）调 10 个端点中任意一个（如 `GET /evaluations/tasks`）→ **401** | RULE-EVAL-022 | REQ-EVAL-001, REQ-EVAL-009 | observed |

---

## 4. 未决（供 `specs/questions.md` 汇总）

见 `requirements/modules/evaluation.md` §4 的 8 条。规格层需要额外定的判定口径：

- **`ASRT-EVAL-011` / `ASRT-EVAL-012` 的性质**：这两条断言的是"现状"（越权与状态不同步），不是"应该这样"。若产品判定为缺陷，用例的 `evaluation_mode` 应从 `binary` 改为 `graded`，或在 `expected` 里写明"当前实现如此，按缺陷登记"。
- **`ASRT-EVAL-004` 的容差**：LLM 出题可能少于目标条数（重试 3 次仍空），断言只能给"≈7/2/1 且总数等于实际行数"，不能写死 7/2/1。这是**模型非确定性**导致的固有模糊，不属于实现缺陷。
- **`ASRT-EVAL-014` 的故障注入方式**：断开 broker 需要 `controlled_fixture`（停容器或改 `RABBITMQ_HOST` 到不可达地址后重启 API 进程），不能在 `live_api` 下完成。
- **`ASRT-EVAL-017` 是静态检查**：`grep` 结果可判定，但需要在资料基线提交上跑，`execution_kind=static_review`。
- **custom 任务 `kb_ids=None` 时的检索范围**（REQ-EVAL-006 第 2 步）本轮未核实，凡涉及 custom 评测"答案是否正确"的判定都应先补这条。
