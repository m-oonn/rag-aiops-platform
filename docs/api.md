# API Documentation

## 1. Authentication

### Register
- **POST** `/api/v1/auth/register`
- **Body**: `{"username": "user", "password": "pw", "email": "e@mail.com"}`

### Login
- **POST** `/api/v1/auth/login/access-token`
- **Body**: `username`, `password` (FormData)
- **Response**: `{"access_token": "...", "token_type": "bearer"}`
- 若 `username` 命中 `settings.ADMIN_USERNAMES` 且当前不是 `admin`,登录时自动提权为 `admin`(首个管理员引导口,幂等)。

### Current User
- **GET** `/api/v1/auth/me`
- **Headers**: `Authorization: Bearer <token>`
- **Response**: `{"id": 1, "username": "u", "email": "e@mail.com", "is_active": true, "role": "user"}`

### List Users (admin only)
- **GET** `/api/v1/auth/users`
- 非 `admin` 返回 403「需要管理员权限」。

### Update User Role (admin only)
- **PATCH** `/api/v1/auth/users/{user_id}/role`
- **Body**: `{"role": "auditor"}` (`user` / `auditor` / `admin`)
- 修改自己 → 400「不能修改自己的角色」;用户不存在 → 404;非法角色 → 422。

## 1.1 Health

### Health Check
- **GET** `/api/v1/health`
- **Response**: `{"status": "ok", "version": "1.0.0"}`
- `/api/v1/health/health` 是历史双前缀地址,保留为兼容别名(不出现在 OpenAPI schema 中)。

### Dependencies
- **GET** `/api/v1/health/dependencies`(需登录)
- 返回 `overall`(`ok` / `degraded`)与逐项状态(mcp_monitor、mcp_cls、rabbitmq、redis、milvus、minio、llm)。

### Queues
- **GET** `/api/v1/health/queues`(需登录)
- 三态语义:`ok`(+ `summary.workers` 在线 Worker 数)、`degraded`(中间件正常但无在线 Worker,任务只会堆积)、`unavailable`(中间件不可达,附 `detail`)。

### Models
- **GET** `/api/v1/health/models`
- 返回后端配置的可用模型列表(前端下拉数据源)。

## 2. Knowledge Base Management

### List KBs
- **GET** `/api/v1/knowledge-bases/`
- **Headers**: `Authorization: Bearer <token>`

### Create KB
- **POST** `/api/v1/knowledge-bases/`
- **Body**: `{"name": "My KB", "description": "..."}`

### Upload Document
- **POST** `/api/v1/knowledge-bases/{kb_id}/upload`
- **Body**: `file` (Multipart)

### Generate QA Pairs
- **POST** `/api/v1/knowledge-bases/documents/{doc_id}/generate-qa?num_pairs=5`
- **Response**: List of generated QA pairs.

## 3. Chat (RAG)

### Send Message
- **POST** `/api/v1/chat/`
- **Body**:
```json
{
  "query": "What is RAG?",
  "kb_id": 1,
  "session_id": "optional-uuid"
}
```
- **Response**:
```json
{
  "session_id": "uuid",
  "answer": "RAG is...",
  "source_documents": [...]
}
```

### Get History
- **GET** `/api/v1/chat/sessions`
- **GET** `/api/v1/chat/sessions/{session_id}/messages`

## 4. Evaluation

### Start Evaluation
- **POST** `/api/v1/evaluations/start`
- **Body**:
```json
{
  "kb_id": 1,
  "num_questions": 10
}
```

### Get Report
- **GET** `/api/v1/evaluations/{task_id}/report`
- **Response**: `{"content": "# Markdown Report..."}`
