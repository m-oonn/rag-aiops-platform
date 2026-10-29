# 配置字段全表（2026-10-27）

本表已按同日用户授权的全局GLM切换更新，来源为 `runtime/glm-default-switch-20261027-a/configuration.json`。由脱敏审计生成，记录本次审计进程按项目根目录 `.env` 解析的结果，不代表常驻服务内存。密钥仅显示是否配置；结构化内容省略。132个字段全部列出，源码无直接消费者不代表无效，可能通过间接引用使用。

| 字段 | 本机解析值（脱敏） | 来源 | 源码默认值（脱敏） | 静态消费者 |
| --- | --- | --- | --- | --- |
| `APP_NAME` | "RAG-PDF-System" | source_default | "RAG-PDF-System" | `src/main.py:190` |
| `APP_ENV` | "development" | source_default | "development" | `src/api/routers/agent.py:73`, `src/api/routers/agent.py:83`, `src/main.py:70`, `src/main.py:181`, `src/main.py:287` |
| `DEBUG` | true | source_default | true | 未检出直接引用 |
| `API_PREFIX` | "/api/v1" | source_default | "/api/v1" | `src/api/dependencies.py:10`, `src/main.py:255`, `src/main.py:256`, `src/main.py:257`, `src/main.py:258`, `src/main.py:259`, `src/main.py:260`, `src/main.py:261`, `src/main.py:262`, `src/main.py:263`, `src/main.py:264`, `src/main.py:265` |
| `BASE_DIR` | "D:\\ragPdfSystem++agent" | source_default | "D:\\ragPdfSystem++agent" | `src/agent/aiops/local_retrieval.py:17` |
| `UPLOAD_DIR` | "D:\\ragPdfSystem++agent\\data\\raw" | source_default | "D:\\ragPdfSystem++agent\\data\\raw" | `src/api/routers/knowledge_base.py:351`, `src/api/routers/knowledge_base.py:354`, `src/api/routers/loadfile.py:74`, `src/settings.py:371`, `scripts/import_ops_runbooks.py:30`, `scripts/import_ops_runbooks.py:40` |
| `PROCESSED_DIR` | "D:\\ragPdfSystem++agent\\data\\processed" | source_default | "D:\\ragPdfSystem++agent\\data\\processed" | `src/settings.py:372` |
| `VECTOR_DIR` | "D:\\ragPdfSystem++agent\\data\\vectors" | source_default | "D:\\ragPdfSystem++agent\\data\\vectors" | `src/database/local_vector_store.py:44`, `src/settings.py:373` |
| `SECRET_KEY` | {"configured": true} | .env | {"configured": false} | `src/api/dependencies.py:19`, `src/main.py:48`, `src/main.py:57`, `src/main.py:51`, `src/main.py:60`, `src/utils/security.py:30` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 480 | source_default | 480 | `src/utils/security.py:26` |
| `ALLOWED_ORIGINS` | "" | source_default | "" | `src/main.py:72` |
| `ALLOWED_HOSTS` | "*" | source_default | "*" | `src/main.py:207` |
| `DASHSCOPE_API_KEY` | {"configured": true} | .env | {"configured": false} | `src/agent/aiops/strategies/dynamic_classification.py:530`, `src/embedding/dashscope_embedding.py:11`, `src/llm/llm_client.py:24`, `src/retrieval/reranker.py:10`, `scripts/diag_net.py:38`, `scripts/diag_net.py:53`, `scripts/diag_net.py:68`, `scripts/diag_net.py:69`, `scripts/probes/probe_all_models.py:118`, `scripts/probes/probe_all_models.py:74`, `scripts/probes/probe_all_models.py:88`, `scripts/probes/probe_all_models.py:122`, `scripts/probes/probe_available_models.py:90`, `scripts/probes/probe_available_models.py:47`, `scripts/probes/probe_livetranslate_params.py:229`, `scripts/probes/probe_livetranslate_params.py:90`, `scripts/probes/probe_livetranslate_params.py:234`, `scripts/probes/probe_llm.py:65`, `scripts/probes/probe_llm.py:44`, `scripts/probes/probe_llm_react.py:50`, `scripts/probes/probe_llm_with_mcp.py:55`, `scripts/probes/probe_llm_with_mcp.py:77`, `scripts/probes/probe_more_models.py:108`, `scripts/probes/probe_more_models.py:83`, `scripts/probes/probe_nonchat_models.py:323`, `scripts/probes/probe_nonchat_models.py:319`, `scripts/probes/probe_nonchat_models.py:83`, `scripts/probes/probe_nonchat_models.py:175`, `scripts/probes/probe_nonchat_models.py:192`, `scripts/probes/probe_nonchat_models.py:201`, `scripts/probes/probe_nonchat_models.py:211`, `scripts/probes/probe_nonchat_models.py:222`, `scripts/probes/probe_nonchat_models.py:285`, `scripts/probes/probe_nonchat_models.py:340`, `scripts/probes/probe_nonchat_models.py:245`, `scripts/probes/probe_realtime_models.py:302`, `scripts/probes/probe_realtime_models.py:98`, `scripts/probes/probe_realtime_models.py:287`, `scripts/probes/probe_realtime_models.py:307`, `scripts/run_explainability.py:487`, `scripts/run_ragas_eval.py:111`, `scripts/run_robustness.py:251` |
| `DASHSCOPE_API_BASE` | "https://dashscope.aliyuncs.com/compatible-mode/v1" | source_default | "https://dashscope.aliyuncs.com/compatible-mode/v1" | `scripts/diag_net.py:67`, `scripts/diag_net.py:37`, `scripts/diag_net.py:52`, `scripts/probes/probe_all_models.py:117`, `scripts/probes/probe_all_models.py:73`, `scripts/probes/probe_all_models.py:89`, `scripts/probes/probe_available_models.py:89`, `scripts/probes/probe_available_models.py:48`, `scripts/probes/probe_llm.py:64`, `scripts/probes/probe_llm.py:45`, `scripts/probes/probe_llm_react.py:51`, `scripts/probes/probe_llm_with_mcp.py:56`, `scripts/probes/probe_more_models.py:107`, `scripts/probes/probe_more_models.py:84`, `scripts/probes/probe_nonchat_models.py:284`, `scripts/probes/probe_nonchat_models.py:70`, `scripts/probes/probe_realtime_models.py:286`, `scripts/run_explainability.py:488`, `scripts/run_robustness.py:252` |
| `LLM_API_BASE` | "https://www.rightapi.ai/v1" | .env | "https://www.rightapi.ai/v1" | 未检出直接引用 |
| `LLM_API_KEY` | {"configured": true} | .env | {"configured": false} | 未检出直接引用 |
| `DEEPSEEK_API_KEY` | {"configured": false} | source_default | {"configured": false} | 未检出直接引用 |
| `EMBEDDING_MODEL` | "BAAI/bge-m3" | .env | "qwen3.7-text-embedding" | `src/embedding/dashscope_embedding.py:15`, `src/embedding/openai_compat_embedding.py:24`, `scripts/_verify_fixes.py:45`, `scripts/run_ragas_eval.py:189`, `scripts/run_ragas_eval.py:212` |
| `EMBEDDING_BATCH_SIZE` | 20 | source_default | 20 | `src/embedding/dashscope_embedding.py:21`, `src/embedding/openai_compat_embedding.py:50` |
| `EMBEDDING_MAX_BATCH_SIZE` | 25 | source_default | 25 | `src/embedding/dashscope_embedding.py:21`, `src/embedding/openai_compat_embedding.py:50` |
| `EMBEDDING_API_BASE` | "https://api.siliconflow.cn/v1" | .env | null | `src/embedding/__init__.py:15`, `src/embedding/openai_compat_embedding.py:22` |
| `EMBEDDING_API_KEY` | {"configured": true} | .env | {"configured": false} | `src/embedding/__init__.py:15`, `src/embedding/openai_compat_embedding.py:23` |
| `LLM_MODEL` | "glm-5.3-flash" | .env | "glm-5.3-flash" | `src/api/routers/assistant.py:18`, `src/api/routers/health.py:196`, `src/database/models.py:178`, `src/llm/llm_client.py:23`, `scripts/compare_with_project_evaluator.py:32`, `scripts/compare_with_project_evaluator.py:41` |
| `AGENT_MODEL` | "glm-5.3-flash" | .env | "glm-5.3-flash" | `src/agent/aiops_llm.py:50`, `src/services/agent_tool_service.py:69`, `scripts/audit_configuration.py:167`, `scripts/probes/probe_llm_react.py:92`, `scripts/probes/probe_llm_react.py:49`, `scripts/probes/probe_llm_with_mcp.py:76`, `scripts/probes/probe_llm_with_mcp.py:54`, `scripts/run_explainability.py:486`, `scripts/run_robustness.py:250`, `scripts/verify_deepseek.py:41` |
| `AGENT_MODEL_SIMPLE` | "glm-5.3-flash" | .env | "glm-5.3-flash" | `scripts/audit_configuration.py:167` |
| `AGENT_DISABLE_THINKING` | false | .env | false | `src/agent/aiops_llm.py:47`, `src/llm/llm_client.py:53`, `scripts/audit_configuration.py:171` |
| `ENABLE_LLM_EVIDENCE_JUDGE` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:528` |
| `EVIDENCE_LLM_MODEL` | "glm-5.3-flash" | .env | "glm-5.3-flash" | `src/agent/aiops/strategies/dynamic_classification.py:536`, `scripts/audit_configuration.py:168`, `scripts/run_robustness.py:183` |
| `AVAILABLE_MODELS` | "glm-5.3-flash" | .env | "glm-5.3-flash" | `src/api/routers/chat.py:37`, `src/api/routers/health.py:183`, `src/llm/llm_client.py:76`, `src/services/agent_tool_service.py:67`, `scripts/probes/probe_available_models.py:92` |
| `MODEL_DISPLAY_NAMES` | "GLM-5.3-Flash" | .env | "GLM-5.3-Flash" | `src/api/routers/health.py:184`, `scripts/probes/probe_available_models.py:93` |
| `MILVUS_HOST` | "localhost" | source_default | "localhost" | `src/api/routers/health.py:107`, `src/database/vector_db.py:30` |
| `MILVUS_PORT` | 19530 | source_default | 19530 | `src/api/routers/health.py:107`, `src/database/vector_db.py:31` |
| `MILVUS_COLLECTION_NAME` | "rag_documents_v2" | source_default | "rag_documents_v2" | `src/database/vector_db.py:32` |
| `MILVUS_DIMENSION` | 1024 | source_default | 1024 | `src/database/vector_db.py:33`, `scripts/_verify_fixes.py:45`, `scripts/_verify_fixes.py:49`, `scripts/_verify_fixes.py:48`, `scripts/index_runbooks.py:76` |
| `REDIS_URL` | "redis://127.0.0.1:6379/0" | .env | "redis://localhost:6379/0" | `src/api/routers/health.py:95`, `src/services/memory_service.py:15`, `src/worker/celery_app.py:11` |
| `RABBITMQ_HOST` | "localhost" | source_default | "localhost" | `src/api/routers/health.py:76`, `src/worker/celery_app.py:6` |
| `RABBITMQ_PORT` | 5672 | source_default | 5672 | `src/api/routers/health.py:77`, `src/worker/celery_app.py:6` |
| `RABBITMQ_USER` | {"configured": true} | source_default | {"configured": true} | `src/api/routers/health.py:74`, `src/worker/celery_app.py:6` |
| `RABBITMQ_PASSWORD` | {"configured": true} | source_default | {"configured": true} | `src/api/routers/health.py:74`, `src/worker/celery_app.py:6` |
| `MINIO_ENDPOINT` | "127.0.0.1:9000" | .env | "localhost:9000" | `src/api/routers/health.py:122`, `src/services/storage.py:19`, `src/services/storage.py:36` |
| `MINIO_ACCESS_KEY` | {"configured": true} | source_default | {"configured": true} | `src/api/routers/health.py:123`, `src/services/storage.py:20` |
| `MINIO_SECRET_KEY` | {"configured": true} | source_default | {"configured": true} | `src/api/routers/health.py:124`, `src/services/storage.py:21` |
| `MINIO_BUCKET_NAME` | "rag-documents" | source_default | "rag-documents" | `src/api/routers/health.py:127`, `src/services/storage.py:25` |
| `MINIO_SECURE` | false | source_default | false | `src/api/routers/health.py:125`, `src/services/storage.py:22` |
| `DATABASE_URL` | "sqlite:///./rag_system.db" | source_default | "sqlite:///./rag_system.db" | `src/database/sql_session.py:5`, `src/database/sql_session.py:8`, `scripts/verify_windows_local_faults.py:613`, `scripts/verify_windows_probe_evidence_api.py:46` |
| `CHUNK_SIZE` | 1000 | source_default | 1000 | 未检出直接引用 |
| `CHUNK_OVERLAP` | 200 | source_default | 200 | 未检出直接引用 |
| `TOP_K` | 20 | source_default | 20 | 未检出直接引用 |
| `RAG_MIN_SCORE` | 0.1 | source_default | 0.1 | `mcp_servers/rag_server.py:123`, `scripts/verify_windows_probe_graph.py:27` |
| `ENABLE_RERANK` | true | source_default | true | `src/agent/aiops/planner.py:168`, `src/retrieval/reranker.py:18`, `src/services/rag_service.py:241`, `src/services/rag_service.py:250`, `src/services/rag_service.py:323`, `src/services/rag_service.py:208`, `mcp_servers/rag_server.py:63`, `scripts/_verify_fixes.py:56` |
| `RERANK_MODEL` | "qwen3.7-text-rerank" | .env | "qwen3.7-text-rerank" | `src/retrieval/reranker.py:11`, `scripts/_verify_fixes.py:56` |
| `RERANK_TOP_N` | 5 | source_default | 5 | `src/retrieval/reranker.py:12` |
| `EXPERIENCE_KB_IDS` | "" | source_default | "" | `src/agent/aiops/planner.py:137`, `src/agent/aiops/planner.py:140`, `src/agent/aiops/planner.py:141` |
| `EXPERIENCE_MIN_SCORE` | 0.3 | source_default | 0.3 | `src/agent/aiops/planner.py:171` |
| `ENABLE_MULTI_HOP` | true | source_default | true | `src/services/rag_service.py:182` |
| `MAX_HOP` | 3 | source_default | 3 | `src/services/rag_service.py:309` |
| `ENABLE_DYNAMIC_CLASSIFICATION` | true | .env | false | `src/agent/aiops/graph.py:577`, `src/agent/aiops/graph.py:120` |
| `DISABLED_TOOL_GUARDS` | "" | source_default | "" | `src/agent/aiops/tool_guards.py:306` |
| `ENABLE_LLM_RETRY` | true | source_default | true | `src/agent/aiops_llm.py:109`, `scripts/evaluate_windows_probe.py:477`, `scripts/evaluate_windows_probe.py:489` |
| `LLM_RETRY_MAX_ATTEMPTS` | 3 | source_default | 3 | `src/agent/aiops_llm.py:108` |
| `ENABLE_CONTEXT_COMPACTION` | false | source_default | false | `src/agent/aiops/executor.py:524` |
| `ENABLE_SKILL_ROUTING` | false | source_default | false | 未检出直接引用 |
| `ENABLE_STEP_SNAPSHOTS` | false | source_default | false | `src/agent/aiops/graph.py:289`, `scripts/evaluate_autonomous_investigation.py:156` |
| `ENABLE_RAW_EVIDENCE_FOR_JUDGE` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:643` |
| `ENABLE_CONFIDENCE_CALIBRATION` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:548` |
| `BELIEF_SOFTMAX_TEMPERATURE` | 3.0 | source_default | 3.0 | `src/agent/aiops/strategies/dynamic_classification.py:550` |
| `ABLATION_DISABLE_HYPOTHESIS_PROTECTION` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:721`, `src/agent/aiops/strategies/dynamic_classification.py:453`, `src/agent/aiops/strategies/dynamic_classification.py:672`, `scripts/run_ablation_eval.py:91` |
| `ABLATION_DISABLE_EVIDENCE_GATE` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:700`, `src/agent/aiops/strategies/dynamic_classification.py:454`, `scripts/run_ablation_eval.py:92` |
| `ABLATION_DISABLE_DEGRADATION_LABEL` | false | source_default | false | `src/agent/aiops/strategies/dynamic_classification.py:704`, `scripts/run_ablation_eval.py:93` |
| `INVESTIGATION_HYPOTHESIS_PROTECTION` | true | source_default | true | `src/agent/aiops/strategies/investigation.py:382`, `scripts/evaluate_windows_probe.py:31` |
| `INVESTIGATION_CONTRADICTION_TRIGGER` | true | source_default | true | `src/agent/aiops/strategies/investigation.py:383`, `scripts/evaluate_windows_probe.py:32` |
| `INVESTIGATION_PROTECTION_STEPS` | 2 | source_default | 2 | `src/agent/aiops/strategies/investigation.py:384` |
| `ENABLE_SUPERVISOR` | false | source_default | false | 未检出直接引用 |
| `ENABLE_HITL` | false | source_default | false | `src/agent/aiops/graph.py:229`, `src/agent/aiops/graph.py:116`, `src/agent/aiops/graph.py:331`, `src/agent/aiops/graph.py:563`, `src/agent/aiops/graph.py:389`, `scripts/evaluate_autonomous_investigation.py:155`, `scripts/evaluate_windows_probe.py:476` |
| `HITL_TTL_SECONDS` | 600 | source_default | 600 | 未检出直接引用 |
| `ENABLE_PARALLEL_OBSERVATION` | false | source_default | false | `src/agent/aiops/executor.py:655` |
| `SHORT_TERM_MEMORY_TTL` | 3600 | source_default | 3600 | `src/services/memory_service.py:21` |
| `LONG_TERM_MEMORY_COLLECTION` | "user_memory" | source_default | "user_memory" | 未检出直接引用 |
| `MEMORY_HISTORY_LIMIT` | 10 | source_default | 10 | `src/services/memory_service.py:22` |
| `MCP_MONITOR_URL` | "http://127.0.0.1:8104/mcp" | source_default | "http://127.0.0.1:8104/mcp" | `src/api/routers/health.py:162` |
| `MCP_CLS_URL` | "http://127.0.0.1:8103/mcp" | source_default | "http://127.0.0.1:8103/mcp" | `src/api/routers/health.py:163` |
| `MCP_RAG_URL` | "http://127.0.0.1:8105/mcp" | source_default | "http://127.0.0.1:8105/mcp" | 未检出直接引用 |
| `MCP_CHANGE_URL` | "http://127.0.0.1:8106/mcp" | source_default | "http://127.0.0.1:8106/mcp" | 未检出直接引用 |
| `MCP_DIAGNOSTIC_URL` | "http://127.0.0.1:8107/mcp" | source_default | "http://127.0.0.1:8107/mcp" | `src/agent/aiops/tools.py:45` |
| `DIAGNOSTIC_ENABLED` | false | source_default | false | `src/agent/aiops/tools.py:43` |
| `DIAGNOSTIC_TOKEN` | {"configured": false} | source_default | {"configured": false} | `src/agent/aiops/tools.py:43`, `src/agent/aiops/tools.py:46` |
| `DIAGNOSTIC_TARGET_CATALOG` | "<structured value omitted>" | source_default | "<structured value omitted>" | `src/agent/aiops/planner.py:293`, `src/agent/aiops/planner.py:343`, `scripts/evaluate_autonomous_investigation.py:157`, `scripts/evaluate_windows_probe.py:473`, `scripts/evaluate_windows_probe.py:488` |
| `MCP_TERMCP_URL` | "http://127.0.0.1:18766/mcp" | source_default | "http://127.0.0.1:18766/mcp" | 未检出直接引用 |
| `TERMCP_ENABLED` | false | source_default | false | `src/agent/aiops/graph.py:331`, `src/agent/aiops/graph.py:330`, `src/agent/aiops/planner.py:300`, `src/agent/aiops/tools.py:36`, `src/api/routers/aiops.py:55`, `scripts/evaluate_autonomous_investigation.py:154`, `scripts/evaluate_windows_probe.py:475` |
| `TERMCP_APPROVAL_API_URL` | "http://127.0.0.1:18766" | source_default | "http://127.0.0.1:18766" | `src/agent/aiops/termcp_tools.py:54`, `src/agent/aiops/termcp_tools.py:141` |
| `TERMCP_UI_URL` | "http://127.0.0.1:18765" | source_default | "http://127.0.0.1:18765" | `src/agent/aiops/graph.py:383`, `src/agent/aiops/graph.py:493`, `src/api/routers/aiops.py:141` |
| `TERMCP_SSH_PROFILE` | "test-target" | source_default | "test-target" | `src/agent/aiops/graph.py:190` |
| `AIOPS_CHECKPOINT_DB_PATH` | "data/aiops_checkpoints.sqlite" | source_default | "data/aiops_checkpoints.sqlite" | `src/agent/aiops/graph.py:150` |
| `PROBE_ENABLED` | false | source_default | false | `src/agent/aiops/evidence_sources.py:60`, `src/agent/aiops/graph.py:331`, `src/agent/aiops/graph.py:361`, `src/agent/aiops/planner.py:313`, `src/agent/aiops/planner.py:344`, `src/agent/aiops/planner.py:300`, `src/agent/aiops/planner.py:377`, `src/agent/aiops/planner.py:391`, `src/agent/aiops/tools.py:31`, `scripts/evaluate_windows_probe.py:471` |
| `PROBE_TARGET_ID` | "windows-local-01" | source_default | "windows-local-01" | `src/agent/aiops/executor.py:366`, `src/agent/aiops/executor.py:257`, `src/agent/aiops/executor.py:437`, `src/agent/aiops/planner.py:344`, `src/agent/aiops/planner.py:349`, `src/agent/aiops/planner.py:326`, `src/agent/aiops/strategies/investigation.py:216`, `src/agent/aiops/strategies/investigation.py:748`, `src/agent/aiops/strategies/investigation.py:182`, `src/api/routers/aiops.py:213`, `scripts/evaluate_windows_probe.py:472`, `scripts/mechanism_behavior.py:49`, `scripts/replay_aiops_decision.py:52`, `scripts/serve_free_investigation_browser.py:95`, `scripts/verify_installed_windows_probe.py:70`, `scripts/verify_probe_mechanisms.py:139`, `scripts/verify_windows_local_faults.py:614`, `scripts/verify_windows_probe_graph.py:144` |
| `PROBE_TOKEN` | {"configured": false} | source_default | {"configured": false} | 未检出直接引用 |
| `PROBE_TLS_VERIFY` | true | source_default | true | 未检出直接引用 |
| `MCP_PROBE_URL` | "http://127.0.0.1:18767/mcp" | source_default | "http://127.0.0.1:18767/mcp" | 未检出直接引用 |
| `PROBE_EVIDENCE_DIR` | "data/aiops-evidence" | source_default | "data/aiops-evidence" | `src/agent/aiops/evidence_reader.py:26`, `src/agent/aiops/run_store.py:229`, `scripts/evaluate_windows_probe.py:474` |
| `MONITOR_BACKEND` | "prometheus" | .env | "mock" | `mcp_servers/monitor_server.py:135`, `mcp_servers/prometheus_client.py:38`, `scripts/probes/probe_real_backends.py:153` |
| `PROMETHEUS_URL` | "http://127.0.0.1:19090" | .env | "" | `mcp_servers/monitor_server.py:143`, `mcp_servers/monitor_server.py:145`, `mcp_servers/prometheus_client.py:127`, `mcp_servers/prometheus_client.py:39`, `scripts/discover_prometheus_metrics.py:110`, `scripts/probes/probe_real_backends.py:46`, `scripts/probes/probe_real_backends.py:160` |
| `PROMETHEUS_CPU_PROMQL` | "clamp_min(100 - avg(rate(node_cpu_seconds_total{mode=\"idle\", instance=~\"{service}.*\"}[5m])) * 100, 0)" | .env | "clamp_min(100 - avg(rate(node_cpu_seconds_total{mode=\"idle\", instance=~\"{service}.*\"}[5m])) * 100, 0)" | `mcp_servers/prometheus_client.py:148` |
| `PROMETHEUS_MEMORY_PROMQL` | "100 * (1 - node_memory_MemAvailable_bytes{instance=~\"{service}.*\"} / node_memory_MemTotal_bytes{instance=~\"{service}.*\"})" | .env | "100 * (1 - node_memory_MemAvailable_bytes{instance=~\"{service}.*\"} / node_memory_MemTotal_bytes{instance=~\"{service}.*\"})" | `mcp_servers/prometheus_client.py:154` |
| `PROMETHEUS_TIMEOUT_SECONDS` | 5.0 | .env | 5.0 | `mcp_servers/prometheus_client.py:128`, `scripts/discover_prometheus_metrics.py:36`, `scripts/probes/probe_real_backends.py:54` |
| `PROMETHEUS_USERNAME` | {"configured": false} | .env | {"configured": false} | `mcp_servers/prometheus_client.py:51`, `mcp_servers/prometheus_client.py:52`, `scripts/probes/probe_real_backends.py:52` |
| `PROMETHEUS_PASSWORD` | {"configured": false} | .env | {"configured": false} | `mcp_servers/prometheus_client.py:52` |
| `PROMETHEUS_BEARER_TOKEN` | {"configured": false} | .env | {"configured": false} | `mcp_servers/prometheus_client.py:49`, `mcp_servers/prometheus_client.py:50`, `scripts/probes/probe_real_backends.py:52` |
| `PROMETHEUS_VERIFY_SSL` | true | .env | true | `mcp_servers/prometheus_client.py:48`, `scripts/probes/probe_real_backends.py:53` |
| `MINIO_SOURCE_BUCKET` | "rag-documents" | source_default | "rag-documents" | 未检出直接引用 |
| `CLS_BACKEND` | "elasticsearch" | .env | "mock" | `mcp_servers/cls_client.py:40`, `mcp_servers/cls_server.py:77`, `scripts/probes/probe_real_backends.py:154` |
| `CLS_ES_URL` | "http://127.0.0.1:9200" | .env | "" | `mcp_servers/cls_client.py:55`, `mcp_servers/cls_client.py:41`, `mcp_servers/cls_server.py:85`, `mcp_servers/cls_server.py:162`, `mcp_servers/cls_server.py:87`, `mcp_servers/cls_server.py:167`, `scripts/probes/probe_real_backends.py:85`, `scripts/probes/probe_real_backends.py:161`, `scripts/seed_es_demo_logs.py:53`, `scripts/seed_es_demo_logs.py:60` |
| `CLS_INDEX_PATTERN` | "<structured value omitted>" | .env | "<structured value omitted>" | `mcp_servers/cls_client.py:97`, `mcp_servers/cls_client.py:138`, `scripts/probes/probe_real_backends.py:121`, `scripts/seed_es_demo_logs.py:48` |
| `CLS_LOG_TIMESTAMP_FIELD` | "@timestamp" | .env | "@timestamp" | `mcp_servers/cls_client.py:57`, `scripts/probes/probe_real_backends.py:94`, `scripts/seed_es_demo_logs.py:67` |
| `CLS_LOG_LEVEL_FIELD` | "level" | .env | "level" | `mcp_servers/cls_client.py:58`, `scripts/probes/probe_real_backends.py:95`, `scripts/seed_es_demo_logs.py:68` |
| `CLS_LOG_MESSAGE_FIELD` | "message" | .env | "message" | `mcp_servers/cls_client.py:59`, `scripts/probes/probe_real_backends.py:95`, `scripts/seed_es_demo_logs.py:69` |
| `CLS_TIMEOUT_SECONDS` | 5.0 | .env | 5.0 | `mcp_servers/cls_client.py:56`, `scripts/probes/probe_real_backends.py:93` |
| `CLS_ES_USERNAME` | {"configured": false} | .env | {"configured": false} | `mcp_servers/change_client.py:76`, `mcp_servers/change_client.py:77`, `mcp_servers/cls_client.py:71`, `mcp_servers/cls_client.py:72`, `scripts/probes/probe_real_backends.py:91` |
| `CLS_ES_PASSWORD` | {"configured": false} | .env | {"configured": false} | `mcp_servers/change_client.py:77`, `mcp_servers/cls_client.py:72` |
| `CLS_ES_API_KEY` | {"configured": false} | .env | {"configured": false} | `mcp_servers/change_client.py:74`, `mcp_servers/change_client.py:75`, `mcp_servers/cls_client.py:69`, `mcp_servers/cls_client.py:70`, `scripts/probes/probe_real_backends.py:91` |
| `CLS_ES_VERIFY_SSL` | true | .env | true | `mcp_servers/change_client.py:73`, `mcp_servers/cls_client.py:68`, `scripts/probes/probe_real_backends.py:92` |
| `CHANGE_ES_URL` | "" | .env | "" | 未检出直接引用 |
| `CHANGE_INDEX_PATTERN` | "change-events-*" | .env | "change-events-*" | `mcp_servers/change_client.py:57`, `scripts/seed_es_change_events.py:62` |
| `CHANGE_TIMESTAMP_FIELD` | "@timestamp" | .env | "@timestamp" | `mcp_servers/change_client.py:58` |
| `CHANGE_SERVICE_FIELD` | "service" | .env | "service" | `mcp_servers/change_client.py:59` |
| `CHANGE_ID_FIELD` | "change_id" | .env | "change_id" | `mcp_servers/change_client.py:60` |
| `CHANGE_TYPE_FIELD` | "change_type" | .env | "change_type" | `mcp_servers/change_client.py:61` |
| `CHANGE_OPERATOR_FIELD` | "operator" | .env | "operator" | `mcp_servers/change_client.py:62` |
| `CHANGE_VERSION_FIELD` | "version" | .env | "version" | `mcp_servers/change_client.py:63` |
| `CHANGE_DESCRIPTION_FIELD` | "description" | .env | "description" | `mcp_servers/change_client.py:64` |
| `CHANGE_STATUS_FIELD` | "status" | .env | "status" | `mcp_servers/change_client.py:65` |
| `CHANGE_TIMEOUT_SECONDS` | 5.0 | .env | 5.0 | `mcp_servers/change_client.py:56` |
| `SERVICE_ALIASES` | "<structured value omitted>" | .env | "<structured value omitted>" | `src/agent/aiops/planner.py:344`, `mcp_servers/service_map.py:82` |

## 直接环境变量读取入口

下列变量来自 `src/`、`mcp_servers/`、`scripts/` 的静态Python AST；它们不一定属于Settings，也可能仅用于某个评测脚本或系统运行时。不能把它们全部复制进主`.env`后就认为各进程会读取。嵌入字符串与第三方库内部读取不在本表穷尽范围。

| 名称 | 读取/写入位置 |
| --- | --- |
| `AGENT_MODEL` | `src/agent/aiops_llm.py:50` |
| `AIOPS_CHECKPOINT_DB_PATH` | `scripts/evaluate_autonomous_investigation.py:146`, `scripts/evaluate_windows_probe.py:404`, `scripts/serve_free_investigation_browser.py:21`, `scripts/verify_aiops_cross_process_resume.py:27`, `scripts/verify_windows_probe_browser.py:18` |
| `DASHSCOPE_API_KEY` | `scripts/run_full_pipeline.py:24` |
| `DATABASE_URL` | `scripts/evaluate_autonomous_investigation.py:145`, `scripts/evaluate_windows_probe.py:403`, `scripts/serve_free_investigation_browser.py:20`, `scripts/verify_aiops_cross_process_resume.py:26`, `scripts/verify_probe_retention.py:43`, `scripts/verify_windows_probe_browser.py:17`, `scripts/verify_windows_probe_evidence_api.py:35`, `scripts/verify_windows_probe_evidence_api.py:46` |
| `DIAGNOSTIC_ALLOWED_DEPENDENCIES` | `mcp_servers/diagnostic_server.py:201` |
| `DIAGNOSTIC_COLLECTOR_CONFIG` | `mcp_servers/diagnostic_collector.py:119` |
| `DIAGNOSTIC_EVIDENCE_DIR` | `mcp_servers/diagnostic_server.py:210`, `mcp_servers/diagnostic_server.py:118` |
| `DIAGNOSTIC_EXEC_ENABLED` | `mcp_servers/diagnostic_server.py:50` |
| `DIAGNOSTIC_HOST` | `mcp_servers/diagnostic_server.py:388` |
| `DIAGNOSTIC_LOCAL_TARGET_ID` | `mcp_servers/diagnostic_server.py:283` |
| `DIAGNOSTIC_PATH` | `mcp_servers/diagnostic_server.py:129` |
| `DIAGNOSTIC_PORT` | `mcp_servers/diagnostic_server.py:389` |
| `DIAGNOSTIC_SSH_CONFIG` | `mcp_servers/diagnostic_server.py:280`, `mcp_servers/diagnostic_server.py:324` |
| `DIAGNOSTIC_TOKEN` | `mcp_servers/diagnostic_server.py:27` |
| `DIAGNOSTIC_WORKDIR` | `mcp_servers/diagnostic_server.py:135` |
| `ENABLE_DYNAMIC_CLASSIFICATION` | `scripts/run_ablation_eval.py:45`, `scripts/run_blind_eval.py:38`, `scripts/run_explainability.py:63`, `scripts/run_full_pipeline.py:22`, `scripts/run_pi_opt_ab_eval.py:39`, `scripts/serve_free_investigation_browser.py:25` |
| `ENABLE_EXPERIENCE_CONTEXT` | `src/agent/aiops/planner.py:135`, `scripts/evaluate_windows_probe.py:405` |
| `ENABLE_HITL` | `scripts/run_ablation_eval.py:46`, `scripts/run_blind_eval.py:41`, `scripts/run_explainability.py:62`, `scripts/run_pi_opt_ab_eval.py:40`, `scripts/serve_free_investigation_browser.py:24`, `scripts/verify_aiops_cross_process_resume.py:30` |
| `ENABLE_LLM_EVIDENCE_JUDGE` | `scripts/run_blind_eval.py:310` |
| `HF_ENDPOINT` | `scripts/download_hf_datasets.py:14`, `scripts/download_hf_datasets.py:32` |
| `JOINT_MCP` | `scripts/evaluate_autonomous_investigation.py:191` |
| `MCP_HOST` | `mcp_servers/change_server.py:169`, `mcp_servers/cls_server.py:202`, `mcp_servers/monitor_server.py:365` |
| `MEASURE_LOG` | `scripts/_measure_resources.py:36` |
| `NO_PROXY` | `scripts/_verify_fixes.py:16`, `scripts/probes/probe_all_models.py:32`, `scripts/probes/probe_available_models.py:17`, `scripts/probes/probe_livetranslate_params.py:37`, `scripts/probes/probe_llm.py:24`, `scripts/probes/probe_llm_react.py:24`, `scripts/probes/probe_llm_with_mcp.py:26`, `scripts/probes/probe_more_models.py:15`, `scripts/probes/probe_nonchat_models.py:37`, `scripts/probes/probe_realtime_models.py:52`, `scripts/try_mcp_client.py:13` |
| `PATH` | `mcp_servers/diagnostic_server.py:129` |
| `PROBE_ENABLED` | `scripts/verify_aiops_cross_process_resume.py:31` |
| `PROBE_EVIDENCE_DIR` | `scripts/serve_free_investigation_browser.py:22`, `scripts/verify_probe_retention.py:44` |
| `PROBE_PORT` | `scripts/verify_probe_local_runtime.py:207` |
| `PROBE_STALE_SECONDS` | `mcp_servers/probe_gateway.py:25` |
| `PROBE_TARGET_ID` | `mcp_servers/probe_gateway.py:27`, `scripts/verify_probe_local_runtime.py:202`, `scripts/verify_probe_retention.py:45` |
| `PROBE_TOKEN` | `mcp_servers/probe_gateway.py:28`, `scripts/verify_probe_local_runtime.py:204`, `scripts/verify_probe_retention.py:46`, `scripts/verify_probe_retention.py:75` |
| `PROGRAMDATA` | `src/probe/windows/config.py:19` |
| `RAG_AIOPS_PROBE_CONFIG` | `src/probe/windows/service.py:46`, `scripts/windows_probe.py:33` |
| `RETENTION_TEST_PORT` | `scripts/verify_probe_retention.py:22` |
| `SECRET_KEY` | `scripts/serve_free_investigation_browser.py:23`, `scripts/verify_aiops_cross_process_resume.py:28`, `scripts/verify_windows_probe_browser.py:19`, `scripts/verify_windows_probe_evidence_api.py:36` |
| `SSL_CERT_FILE` | `scripts/evaluate_windows_probe.py:411`, `scripts/verify_windows_probe_tls.py:131` |
| `TERMCP_APPROVAL_API_URL` | `scripts/verify_aiops_cross_process_resume.py:32` |
| `TERMCP_ENABLED` | `scripts/verify_aiops_cross_process_resume.py:29` |
| `TERMCP_INTERNAL_URL` | `mcp_servers/termcp_gateway.py:13` |
| `TERMCP_SSH_PROFILE` | `mcp_servers/termcp_gateway.py:15`, `scripts/verify_aiops_cross_process_resume.py:33` |
| `TERMCP_TOKEN` | `mcp_servers/termcp_gateway.py:14` |
| `USE_TORCH` | `scripts/download_hf_datasets.py:13`, `scripts/download_kaggle_datasets.py:14`, `scripts/index_runbooks.py:14`, `scripts/try_aiops.py:25` |
| `WEBSITE_CHECK_USE_PROXY` | `mcp_servers/site_probe.py:52` |
