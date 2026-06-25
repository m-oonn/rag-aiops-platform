# API Documentation

## 1. Authentication

### Register
- **POST** `/api/v1/auth/register`
- **Body**: `{"username": "user", "password": "pw", "email": "e@mail.com"}`

### Login
- **POST** `/api/v1/auth/login/access-token`
- **Body**: `username`, `password` (FormData)
- **Response**: `{"access_token": "...", "token_type": "bearer"}`

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
