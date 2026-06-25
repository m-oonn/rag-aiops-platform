# RAG 智库系统 (RAG Knowledge Base System)

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/vue-3.x-green)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-teal)](https://fastapi.tiangolo.com/)

基于大语言模型 (LLM) 和向量数据库的企业级检索增强生成 (RAG) 知识库问答系统。支持多种格式文档的解析、切分、向量化存储，并提供智能问答、自动化评测及全流程可视化管理。

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

### 3. 📊 RAG 自动化评测 (Evaluation)

- **数据集生成**: 基于知识库文档自动生成 QA 问答对 (Question-Answer Pairs)，包含单跳 (Single-hop) 和多跳 (Multi-hop) 问题。
- **多维指标**: 结合 RAGAS 框架思想，提供忠实度 (Faithfulness)、相关性 (Relevance)、召回率 (Recall) 等多维度自动打分。
- **自定义评测**: 支持上传 JSON/Excel 格式的自定义评测集。
- **可视化报告**: 自动生成 Markdown 格式的评测报告，包含详细的错误分析和改进建议。

### 4. 🛡️ 企业级权限与架构

- **RBAC 权限**: 基于角色的访问控制，支持多用户隔离。
- **高可用架构**:
  - **API**: FastAPI 高性能异步框架。
  - **Task Queue**: RabbitMQ + Celery 分布式任务队列。
  - **Vector DB**: Milvus 高性能向量数据库。
  - **Storage**: MinIO 分布式对象存储。
  - **Cache**: Redis 缓存与会话管理。

## 🏗️ 系统架构

![](./RAG架构图.png)

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

访问地址:

- 前端页面: http://localhost:5173
- API 文档: http://localhost:8000/docs
- MinIO 控制台: http://localhost:9001
- Flower 监控: http://localhost:5555

## 📂 目录结构

```
ragPdfSystem/
├── config/           # 全局配置
├── docker/           # Docker 部署文件
├── frontend/         # Vue3 前端源码
│   ├── src/views/    # 页面组件 (Assistant, Evaluation, KnowledgeBase...)
│   └── src/api/      # Axios 接口封装
├── src/
│   ├── api/          # API 路由 (Endpoints)
│   ├── database/     # ORM 模型与数据库连接
│   ├── embedding/    # 向量化服务封装
│   ├── llm/          # 大模型客户端
│   ├── processors/   # 文档解析与切分核心逻辑
│   ├── retrieval/    # 检索与重排序逻辑
│   ├── services/     # 业务逻辑层 (RAG, Evaluation, Storage)
│   └── worker/       # Celery 异步任务
└── data/             # 本地数据存储 (如 SQLite db)
```
