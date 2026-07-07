# RAG 智库系统 + AIOps 运维诊断 Agent

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/vue-3.x-green)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-teal)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-orange)](https://langchain-ai.github.io/langgraph/)

企业级 RAG 知识库问答系统，并在其上构建了一条基于 **LangGraph 的 AIOps 运维诊断 Agent** 支线。前者支持多格式文档的解析、切分、向量化存储、智能问答与自动化评测；后者通过 **Plan-Execute-Replan** 工作流 + **MCP 协议**工具，演示 Agent 自主故障诊断。

## 🌟 核心特性

### 1. 📚 多模态知识库管理

- **多格式支持**: 支持 PDF, Word (.docx), Excel (.xlsx), PPT (.pptx), Markdown (.md), TXT 等多种文件格式。
- **智能解析**: 内置 OCR 和文档结构分析，精准提取文本、表格和元数据（页码、章节）。
- **自动化处理**: 文件上传后自动触发 Celery 异步任务进行切分 (Chunking) 和向量化 (Embedding)。
- **MinIO 集成**: 原生支持 MinIO 对象存储，提供文件预览、下载和版本管理。

### 2. 🤖 智能对话助手 (Assistant)

- **自定义角色**: 支持创建多个助手，配置不同的系统提示词 (System Prompt)、温度系数 (Temperature) 和模型参数。
- **记忆机制**:
  - **短期记忆**: 基于滑动窗口的历史对话保留。
  - **长期记忆**: (规划中) 基于语义检索的历史信息召回。
- **混合检索**: 结合关键词检索 (BM25) 和 向量检索 (Dense Retrieval)，支持重排序 (Rerank) 优化。
- **源文档溯源**: 每一条回答均可精确溯源到引用文档的具体段落和页码。

### 4. 🔧 AIOps 运维诊断 Agent

在 RAG 底座之上构建的自主故障诊断 Agent,基于 **LangGraph StateGraph** 实现经典 **Plan-Execute-Replan** 工作流:

- **Planner(规划)**: 将故障现象拆解为可执行的诊断步骤,并检索历史排查经验(runbook)注入上下文。
- **Executor(执行)**: 逐步执行,通过 **MCP 协议**调用监控指标 / 日志查询工具获取真实数据;工具不可用时降级为基于 LLM 知识的分析。
- **Replanner(重规划)**: 每轮评估战场态势,三选一决策 `continue` / `replan` / `respond`,并以硬限制(最大步数 / 禁 replan 阈值)防止无限循环。
- **MCP 工具解耦**: 监控(`monitor`)与日志(`cls`)服务作为独立进程通过 HTTP + MCP 暴露,Agent 只认 URL —— Mock → 真实 Prometheus 只需改配置,不动 Agent 代码。
- **优雅降级**: Milvus 不可用时自动降级到本地文件检索(runbook / JSONL / Kaggle / HuggingFace 数据集);MCP 服务不可达时不阻断诊断链路。
- **SSE 流式**: 诊断过程(计划 → 逐步执行 → 报告)通过 Server-Sent Events 实时推送前端。

### 5. 📊 RAG 自动化评测 (Evaluation)

- **数据集生成**: 基于知识库文档自动生成 QA 问答对 (Question-Answer Pairs)，包含单跳 (Single-hop) 和多跳 (Multi-hop) 问题。
- **多维指标**: 结合 RAGAS 框架思想，提供忠实度 (Faithfulness)、相关性 (Relevance)、召回率 (Recall) 等多维度自动打分。
- **自定义评测**: 支持上传 JSON/Excel 格式的自定义评测集。
- **可视化报告**: 自动生成 Markdown 格式的评测报告，包含详细的错误分析和改进建议。

### 6. 🛡️ 企业级权限与架构

- **RBAC 权限**: 基于角色的访问控制，支持多用户隔离。
- **高可用架构**:
  - **API**: FastAPI 高性能异步框架。
  - **Task Queue**: RabbitMQ + Celery 分布式任务队列。
  - **Vector DB**: Milvus 高性能向量数据库。
  - **Storage**: MinIO 分布式对象存储。
  - **Cache**: Redis 缓存与会话管理。

## 🏗️ 系统架构

```
                          ┌─────────────┐
     Vue3 前端 ──HTTP──►   │   FastAPI    │
                          └──────┬──────┘
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        RAG 问答链路        AIOps Agent         异步任务
     (retrieval+rerank)   (LangGraph 图)      (Celery)
              │            planner→executor        │
              │              →replanner            │
              ▼                  │                  ▼
     ┌────────────────┐         │          文档解析→切分→向量化
     │ Milvus / Redis │◄────────┤                  │
     │ MinIO / SQLite │         ▼                  ▼
     └────────────────┘   MCP 工具服务        写入 Milvus + SQLite
                          (monitor / cls)
```

RAG 与 AIOps 两条链路共享底座(Milvus/Redis/MinIO/SQLite + DashScope LLM),但编排相互独立 —— RAG 走同步检索生成,AIOps 走 LangGraph 异步流式。

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- Python 3.10+
- Node.js 16+
- DashScope API Key (通义千问)

### 1. 启动基础服务 (Docker)

```bash
cd docker
docker-compose up -d
# 启动 Milvus, MinIO, Redis, RabbitMQ
```

### 2. 后端部署

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY 等信息

# 初始化数据库
python create_tables.py

# 启动 API 服务
python -m src.main

# 启动 Celery Worker (另开终端)
celery -A src.worker.celery_app worker --loglevel=info -P solo
```

### 3. 前端部署

```bash
cd frontend
npm install
npm run dev
```

### 4. AIOps 诊断 Agent (可选)

```bash
# 一键启动 MCP 指标服务 + 日志服务 + FastAPI 后端
bash scripts/demo.sh

# 或手动分别启动:
python mcp_servers/monitor_server.py   # 指标服务 (127.0.0.1:8004)
python mcp_servers/cls_server.py       # 日志服务 (127.0.0.1:8003)

# 诊断端点(SSE): POST /api/v1/aiops
```

访问地址:

- 前端页面: http://localhost:5173
- API 文档: http://localhost:8000/docs
- MinIO 控制台: http://localhost:9001
- Flower 监控: http://localhost:5555

## 📂 目录结构

```
rag-aiops-platform/
├── docker/           # Docker 部署文件
├── frontend/         # Vue3 前端源码
│   ├── src/views/    # 页面组件 (Assistant, Evaluation, KnowledgeBase...)
│   └── src/api/      # Axios 接口封装
├── mcp_servers/      # MCP 工具服务 (monitor 指标 / cls 日志, Mock 版)
├── scripts/          # 验证与运维脚本 (demo.sh 一键启动 / try_aiops.py 验证)
├── src/
│   ├── agent/        # AIOps Agent
│   │   └── aiops/    # Plan-Execute-Replan 图 (planner/executor/replanner/graph)
│   ├── api/          # API 路由 (Endpoints)
│   ├── database/     # ORM 模型与数据库连接 (含 Milvus 封装)
│   ├── embedding/    # 向量化服务封装
│   ├── llm/          # 大模型客户端
│   ├── processors/   # 文档解析与切分核心逻辑
│   ├── retrieval/    # 检索与重排序逻辑
│   ├── services/     # 业务逻辑层 (RAG, Evaluation, Storage, Memory)
│   └── worker/       # Celery 异步任务
└── data/             # 本地数据存储 (SQLite db / runbooks, 未纳入版本管理)
```

## 🧭 技术选型说明

- **LangGraph StateGraph(而非 ReAct 自由循环)**: 诊断任务需收敛出报告,`StateGraph` + 硬限制保证终止;Plan-Execute-Replan 的显式节点也便于扩展决策逻辑。
- **MCP 协议(而非 `@tool` 写死)**: 工具作为独立服务,客户端只认 URL,Mock → 真实后端零改动 Agent。
- **ChatOpenAI compatible-mode(Agent) + ChatTongyi(RAG)**: 两条 LLM 路径分离 —— Agent 侧需 function calling 走兼容模式,RAG 侧走 DashScope 原生 SDK。
- **优雅降级**: Milvus / MCP 任一不可用都不阻断主流程,分别降级到本地文件检索 / LLM 知识分析。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源。
