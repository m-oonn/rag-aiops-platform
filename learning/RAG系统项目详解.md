# RAG 系统项目详解

## 1. 项目概述

本项目是一个企业级检索增强生成（Retrieval Augmented Generation, RAG）系统，旨在解决大语言模型（LLM）在专业领域知识缺失、幻觉（Hallucination）以及数据时效性滞后等问题。通过引入私有知识库，系统能够将用户查询与向量化的文档片段进行匹配，并将召回的上下文信息注入 LLM，从而生成精准、可溯源的回答。

系统采用前后端分离架构，前端基于 Vue 3 + Element Plus 构建现代化交互界面，后端基于 FastAPI + Celery 构建高性能异步服务，底层存储采用 Milvus（向量）、MinIO（文件）和 SQLite/PostgreSQL（元数据）。

## 2. 系统架构深度解析

### 2.1 整体架构图

系统遵循微服务化设计思想，各组件职责解耦：

* **接入层**: Vue 3 SPA 应用。
* **服务层**: FastAPI 提供 RESTful API，处理认证、业务逻辑和请求分发。
* **任务层**: RabbitMQ + Celery 处理耗时任务（文档解析、向量化、评测）。
* **存储层**:
  * **Milvus**: 存储 Embedding 向量，支持高性能近似最近邻（ANN）搜索。
  * **MinIO**: 存储原始文档文件，支持 S3 协议。
  * **Redis**: 缓存会话状态、任务进度和热点数据。
  * **SQL DB**: 存储用户、知识库、助手配置、评测结果等关系型数据。
* **模型层**: 接入通义千问（Qwen）等 LLM 服务，支持 OpenAI 接口格式。

### 2.2 核心模块详解

#### A. 知识库管理模块 (Knowledge Base)

这是 RAG 的数据基石。

1. **多格式解析**:
   * 使用 `pdfplumber`/`pypdf` 解析 PDF，支持提取页码和表格。
   * 使用 `python-docx` 解析 Word，保留段落结构。
   * 使用 `openpyxl` 处理 Excel，将行转换为结构化文本。
2. **智能切分 (Chunking)**:
   * 采用递归字符切分器 (`RecursiveCharacterTextSplitter`)。
   * 支持自定义 `chunk_size` (默认 500-1000 tokens) 和 `chunk_overlap` (默认 100-200 tokens) 以保持上下文连贯性。
3. **向量化 (Embedding)**:
   * 调用 Embedding Model (如 `text-embedding-v3` 或 `qwen-embedding`) 将文本转换为稠密向量。
   * 向量异步写入 Milvus，支持 Collection 分区管理。

#### B. 检索增强生成模块 (RAG Engine)

1. **查询预处理**: 对用户 Query 进行改写或关键词提取（规划中）。
2. **混合检索 (Hybrid Search)**:
   * 目前主要基于 Dense Retrieval (向量相似度)。
   * 可扩展 BM25 稀疏检索，通过倒排索引补充关键词匹配能力。
3. **重排序 (Rerank)**:
   * 对召回的 Top-K (如 50 条) 文档进行二次精排，使用 Cross-Encoder 模型计算 Query 与 Document 的相关性得分，筛选出 Top-N (如 5 条) 最相关的片段。
4. **上下文组装**:
   * 将筛选后的片段按照 `[参考段落 x]` 格式拼接。
   * 注入 System Prompt，引导 LLM "根据以下上下文回答问题..."。

#### C. 智能助手模块 (Assistant)

1. **会话管理**: 每个助手拥有独立的 `session_id`，对话历史持久化存储。
2. **Prompt 工程**:
   * 支持自定义 `system_prompt` 设定人设（如“你是一个严谨的法律顾问”）。
   * 支持 `temperature` 调节回答的随机性。
3. **记忆系统**:
   * **Short-term**: 内存/Redis 中保留最近 N 轮对话。
   * **Long-term**: 将历史对话摘要向量化存储，长对话时检索相关历史记忆。

#### D. 自动化评测模块 (Evaluation)

基于 RAGAS 理念设计的评测体系。

1. **数据集生成**: 利用 LLM 逆向生成 QA 对 (Question, Ground Truth, Context)。
2. **评测执行**:
   * 运行 RAG 流程获取 `Answer` 和 `Retrieved Contexts`。
   * **忠实度 (Faithfulness)**: 检查 Answer 是否由 Context 推导得出。
   * **回答相关性 (Answer Relevance)**: 检查 Answer 是否直接回答了 Query。
   * **上下文召回率 (Context Recall)**: 检查 Retrieved Contexts 是否包含 Ground Truth 所需信息。
3. **报告生成**: 自动统计各指标分布，生成 Markdown 报告。

#### E. 存储与监控模块

1. **MinIO 浏览器**: 在前端直接浏览、下载、预览存储桶中的文件，解决 Docker 容器内文件访问难题。
2. **Celery 监控**: 集成 Flower，实时监控文档处理任务的成功率和耗时。

## 3. 技术栈深度剖析

### 后端 (Backend)

* **Framework**: FastAPI (高性能、异步、自动生成 OpenAPI 文档)。
* **ORM**: SQLAlchemy (ORM 映射) + Pydantic (数据校验)。
* **Async Task**: Celery + RabbitMQ (解耦耗时操作，保证 API 响应速度)。
* **Vector DB**: Milvus (云原生向量数据库，支持百亿级向量检索)。
* **LLM Integration**: LangChain (虽然部分逻辑手写，但设计思想借鉴了 LangChain 的 Chain 和 Retriever 概念)。

### 前端 (Frontend)

* **Core**: Vue 3 (Composition API)。
* **UI Library**: Element Plus (企业级组件库)。
* **State**: Pinia (轻量级状态管理，虽然本项目主要用 ref/reactive)。
* **Network**: Axios (拦截器封装，统一处理 Token 和错误)。
* **Tools**: Vite (极速构建)。

## 4. 关键流程源码导读

* **文档上传与处理**: `src/api/routers/knowledge_base.py` -> `upload_document` -> 触发 Celery Task -> `src/worker/tasks.py` -> `process_document_task`。
* **RAG 对话**: `src/api/routers/chat.py` -> `chat` -> `RagService.query` -> `VectorRetriever.retrieve` -> LLM 调用。
* **评测生成**: `src/api/routers/evaluation.py` -> `generate_dataset` -> `QAGenerator.generate_qa_pairs`。

## 5. 部署与运维

项目完全容器化，通过 `docker-compose.yml` 编排。

* **数据持久化**: 所有数据库（Redis, RabbitMQ, Milvus, MinIO）数据挂载到宿主机 `docker/volumes`。
* **网络隔离**: 所有服务运行在 `rag_net` 网络中，仅暴露必要的 8000 (API), 5173 (Web), 9001 (MinIO Console) 等端口。
* **扩展性**: Worker 节点可以水平扩展以提高文档处理吞吐量。

## 6. 未来规划

1. **多模态支持**: 支持图片、表格图片的理解（RAG with Vision）。
2. **Graph RAG**: 引入知识图谱，解决实体关系复杂的问题。
3. **Agent 升级**: 赋予 Assistant 工具调用能力（如搜索、计算、代码执行）。
