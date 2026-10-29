# 运维知识入库与调查轨迹免费验收（2026-10-23）

本轮完成真实 PDF 的本地入库、检索和引用追溯，以及隔离浏览器的调查轨迹验收。没有调用在线模型、embedding 或重排，不作为真实模型诊断效果或正式四组实验结果。代码基于 `main`、`830a0da` 的工作树，包含尚未提交修改。

## 1. 实际入库资料

当前项目 SQLite `rag_system.db` 新增独立知识库 **15：本科毕设运维手册（本地检索）**。旧知识库与向量索引未覆盖。三份手册是本项目依据公开文档编写的排查材料，作者、日期、适用范围和参考 URL 均写入原文；不是厂商原文，也不是本次现场事实。

| 文档 | 数据库文档 ID | 页数 | 片段数 | 首要参考来源 |
| --- | --- | --- | --- | --- |
| `fixtures/ops-runbooks/01-downstream-connectivity.pdf` | 34 | 2 | 3 | [Microsoft Test-NetConnection](https://learn.microsoft.com/en-us/powershell/module/nettcpip/test-netconnection) |
| `fixtures/ops-runbooks/02-application-errors.pdf` | 35 | 2 | 2 | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html) |
| `fixtures/ops-runbooks/03-latency-and-timeouts.pdf` | 36 | 2 | 3 | [Microsoft Measure-Command](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/measure-command) |

补充参考包括 Python 的 socket 和 traceback 官方文档。上述五个参考 URL 本轮只读核验返回 HTTP 200。Markdown 源文件与 PDF 一并保留。

生成时发现原 CID 字体会使英文提取缺失，已改为嵌入本机宋体，重新生成后再入库。最终六页完成渲染视觉检查，无文本裁切；八个 SQL 片段去除空白后，均可在对应 PDF 标记页的实际提取文本中找到。

实际链路：PDF → 既有解析器 → 按页切分 → SQL 文档/片段 → 指定知识库 BM25 → API/MCP → 文档与页码引用。八个片段的 `vector_id` 为空，不伪造向量，不调用 embedding/Milvus 写入。

导入记录及文件 SHA256：`runtime/ops-knowledge-import-c768988866974a56af05d70a4066b7cf/summary.json`。八个排查查询有结果，一个无关查询 `quantum entanglement` 返回空。此样本只验证功能，不估计通用检索准确率或诊断增益。

## 2. 实现与调用者

- `src/retrieval/knowledge_bm25.py` 每次从指定知识库的已完成文档读取 SQL 片段，避免新上传、重试和删除后索引陈旧；返回稳定片段 ID、文档 ID、文件名、真实页码及来源。
- `bm25_retriever.py` 修正小语料的负/零 IDF 问题，明确匹配在单片段和高频词场景也有正分；同时检查既有 BM25/hybrid 消费者。分数不是正确概率。
- `worker/tasks.py` 支持 `retrieval_mode=bm25`，跳过 embedding 与向量库，PDF 保留解析页边界；空原文重新处理时删除该文档旧 SQL 片段，避免继续命中旧内容。
- 知识库 API 支持检索模式配置、文档来源字段和带既有访问权限校验的 `POST /api/v1/knowledge-bases/{kb_id}/search`。上传、单次/批量重试和重新切分均按文档模式分发；本地模式直接后台处理，避免旧 Celery worker 误走在线 embedding。原 hybrid 默认保留。
- RAG MCP 的 `search_knowledge_base` 对本地库复用同一 SQL 检索函数，返回 `data_source=knowledge_base`；未初始化 hybrid/reranker。旧混检路径兼容保留。
- 前端知识库创建/编辑可选择本地关键词；详情显示检索、无结果提示、片段 ID、页码、来源和“查看引用原文”。PDF 预览使用实际文档及 `#page=N`。
- AIOps 引用定位先确认账本记录存在，再展开采集列表并滚动；不自动请求原始证据，不改变既有权限。

页面检索和进程内 MCP 直接调用已验证。尚未让真实自主模型选择这些资料，也未验证它们改善诊断；自主调查已有知识参考与现场证据分离的消费路径保持不变。

## 3. 浏览器实际核验范围

### 当前主页面

[知识库 15](http://127.0.0.1:5273/knowledge-bases/15) 使用当前已登录账号，实际显示三份 PDF、已完成状态及 3/2/3 片段；原文预览可打开。截图：`runtime/offline-knowledge-browser-20261023-c/main-knowledge-list.png`。

首轮验收时常驻 API8200/RAG8105 未重启，只有资料列表与原文预览可见；下述隔离结果当时不能代表主接口上线。用户随后明确授权仅重启这两个服务，主页面新版搜索与引用已完成，更新证据见第 6 节。

### 隔离知识库页面

临时服务 5286 仅从原库复制知识库 15、三份文档与八个片段；使用独立 SQLite 和测试账号，不复制原账号凭据，不写回主库。加载正式 auth/知识库路由与最终构建前端。

浏览器验证：三文档列表和官方来源链接；查询“应用内部异常”命中 `02-application-errors.pdf` 第 2 页、片段 `doc_9eac2f97-9499-4ad6-99fb-d37dac5a51a4_chunk_1`；无关查询显示无结果；点击引用原文实际打开该 PDF，iframe URL 带 `#page=2`。同一查询通过 `fastmcp.Client(server.mcp)` 命中相同片段与页码；不是常驻 8105 HTTP 服务验收。

检索截图：`runtime/offline-knowledge-browser-20261023-c/knowledge-search-final.png`。

### 隔离调查页面

`scripts/serve_free_investigation_browser.py` 使用正式调查图、API、SSE、checkpoint 和证据入账函数，替换模型输出及工具输入为固定测试夹具。机制事件由正式规则产生，未手工拼造保护/改向事件。页面明确标注离线固定输入，结果为“未定位”，不冒充真实故障或自主模型调查。

实际检查了：登录与 SSE；保护保留候选后安排检查及到期；刷新恢复保护轨迹；TCP `ok` 反驳当前 `failed` 预期后真实改向核查入口；规范 `ev-` 引用展开并定位账本摘要；普通用户无 raw 按钮；刷新矛盾结果后仅一条事件及一条账本记录，无重复。

首次夹具未入账，浏览器拒绝旧 `e1.1` 引用，已修正为复用执行器 `_record_probe_evidence` 后重新验收。审计员 raw 与跨用户访问未做浏览器检查，权限只由相关单测覆盖。

记录：`runtime/offline-browser-20261023-b/offline-contradiction-8359c9c541cc48f889f9.json`；截图：`runtime/offline-browser-20261023-b/investigation-contradiction.png`。旧失败夹具输出保留在 `offline-browser-20261023-a`，不混入修正后结果。

## 4. 检查结果与问题处理

| 检查 | 结果 | 边界 |
| --- | --- | --- |
| 后端扩大定向回归 | 38 通过 | 显式取消默认 addopts，覆盖检索/API/处理/MCP 等相关行为 |
| 最后空原文逻辑补强后的相关回归 | 32 通过 | 最后源码版本；没有在此后重复全仓 |
| 本轮后端默认离线全量 | 820 通过、2 失败、99 integration 排除 | 发生在最后空原文补强前；两项为 Windows 沙箱权限问题 |
| 上述两项正常权限单独复核 | 2 通过 | `test_diagnostic_exec_kills_timed_out_process`、`test_restricted_token_can_access_control_but_not_protected_evidence`；不抹去首次失败 |
| 最终前端全量 | 101 通过，17 文件 | 中途新测试选择器误用 button，改为真实 collapse header 后通过 |
| 最终生产构建 | 通过 | 浏览器隔离知识库使用该构建 |
| PDF 实际内容与引用 | 6 页视觉检查，8 片段逐页文本核对通过 | 仅本轮三份文本 PDF；扫描页未验证 |
| 外部集成/真实模型/正式效果实验 | 未运行 | 本轮保持免费；不以离线测试替代 |

测试仍有四条既有 PyMilvus 弃用提醒。隔离知识库启动因知识库路由既有模块级向量客户端发生本机 Milvus 加载超时，随后按既有行为降级；本地 BM25 检索仍通过，不依赖该服务。未将此超时算作 embedding/模型调用，也未扩大为向量服务重构。

默认 Temp 下 tmp_path 权限失败已改用项目内独立 basetemp 复验；未清理旧输出。最终 Git 空白检查与临时服务清理记录见本轮结构化 `verification-summary.json`。

## 5. 计划进度与后续入口

阶段 D 的小型真实 PDF 本地链路、隔离页面引用与主服务检索引用已完成；机制页面已完成免费固定输入浏览器核验。阶段 B 的真实模型表现、阶段 C 的机制适用真实调查、阶段 D 的自主消费仍需独立验收，阶段 E 正式四组实验未开始。

下一步保持免费：核对诊断知识读取确实携带知识库来源且不进入现场事实裁决，整理缺证据或误用知识的反例，不启动新付费实验。

本次学习关键：能区分“手册描述可能原因”和“当前工具证明发生了什么”，并沿文档 ID → 片段 ID → 页码找到原文。系统完成上述实现，不据此宣称用户已独立掌握所有代码。

保留所有既有修改、旧库、历史证据与失败产物；未提交或推送。临时 5284/5285/5286 已按本轮 exec 会话终止，端口均释放；8200/8105/5273 仍监听。

## 6. 用户授权后的限定重启与主页面验收

2026-10-23 用户明确回复“允许，仅重启这两个项目服务”。重启前核对 8200 的监听 PID34964/父 PID31024、8105 的监听 PID34184/父 PID33864，命令都指向本工作树 `.venv/Scripts/python.exe`。仅终止这四个对应父子进程，按原启动命令及目录隐藏启动；前端、Probe、其他 MCP 和数据库未重启、重建或接管。

新的启动器 PID：API22388、RAG35308；实际监听子 PID：API33000、RAG19412。只更新 `runtime/demo/pids.json` 的 api/rag 项，原文件在本次独立输出保存。8103/8104/8106/5273 的监听 PID 与重启前完全一致。API 启动仍发生既有 Milvus 加载超时后降级，本地 BM25 使用 SQL 不受影响；不宣称向量混检服务通过。

主 API 的 OpenAPI 已包含新增搜索路由。主 5273 页面刷新后显示三份资料及官方参考来源；查询“应用内部异常”命中 02 手册第 2 页，点击“查看引用原文”实际 iframe 带 `#page=2`；无关英文查询显示无匹配且不推断现场原因。最后页面保留正向查询结果供用户查看。

常驻 `http://127.0.0.1:8105/mcp` 使用真实 HTTP MCP 客户端核对两次查询：正向查询返回与主页面相同片段 `doc_9eac2f97-9499-4ad6-99fb-d37dac5a51a4_chunk_1` 和第 2 页，无关查询返回空；两次均 `retrieval_mode=bm25`、`data_source=knowledge_base`。没有发起诊断、在线模型、embedding 或重排请求。

独立产物目录 `runtime/service-reload-20261023-150123/`：前后监听记录、原 PID 记录、启动日志、`mcp-search.json`、`verification-summary.json` 及 `main-knowledge-search.png`。源码仅更新进度文档，无运行逻辑修改，因此不重复全仓回归；本次验证针对实际重启和主页面行为，Git 空白检查通过。此前的结构化验收摘要保留原时间点，主服务已加载的最新状态以本节和本次摘要为准。
