# 知识库真实可用性验收（2026-10-15）

## 结论

知识库已经能在当前环境真实运行：文档在 SQLite、Milvus/本地向量和 BM25 中可查；AIOps Agent 能通过 MCP 选择知识库、检索排查手册，再结合指标、日志和变更证据完成一次真实调查。

这次验收证明了“知识库参与 Agent 调查”的调用链。它还没有证明通用故障的检索准确率，也没有证明任意生产主机都能接入；当前仍是单实例、当前配置服务和测试数据范围。

## 真实验证结果

- 当前运行服务：MCP 知识库 `8105`、日志 `8103`、指标 `8104`、变更 `8106`，后端 `8200`，前端 `5273`；Milvus、MinIO、Redis、RabbitMQ、Elasticsearch 容器均在运行。
- 数据库中有 12 个知识库、203 个完成文档片段；运维排查库为 `kb_id=14`，包含 6 篇完成文档。
- 真实 MCP 客户端发现并调用了 3 个工具：`list_knowledge_bases`、`search_knowledge_base`、`get_document_info`。
- 查询“CPU 使用率突然飙升应该如何排查”命中 `cpu-spike.md`，返回页码 1、chunk_id 和原文；查询“量子纠缠实验怎么做”在最低相关度门槛后返回空结果，不再把运维手册冒充答案。
- 真实 Agent 使用 `deepseek-v4-flash` 执行了一次调查：Planner 生成“先查知识库，再查 CPU、内存、日志、变更”的计划；Executor 实际调用了 `list_knowledge_bases`、`search_knowledge_base`、指标、日志和变更工具。最终以现场数据为准，判断当前服务 CPU 最高约 1%，没有证据支持 CPU 飙升，并明确服务名可能不匹配的限制；未执行修改或重启。
- 该次 Agent 调查耗时约 33 秒，产生 10 个事件；完整事件和报告保存在 [`real-agent-kb-investigation.json`](../data/knowledge-base-verification-20261015/real-agent-kb-investigation.json)。MCP 原始验收结果保存在 [`mcp-client-results-after-threshold.json`](../data/knowledge-base-verification-20261015/mcp-client-results-after-threshold.json)。

## 本次修正

- 新增 `RAG_MIN_SCORE=0.10`，MCP 对外结果在重排后低于门槛时返回空列表。
- 报告生成阶段从原始知识库工具返回中提取 `source/page/chunk_id`，追加“参考知识库”小节，并明确现场指标、日志和变更证据优先。
- 相关回归测试 17 项通过；Milvus 仍有 PyMilvus 弃用提醒，但不影响本次连接和搜索。

## 限制和下一步

- 当前 Agent 真实场景是“告警与现场不一致”的正常现场，不是已构造的 CPU 真故障；根因定位能力仍需在隔离环境构造可控故障后验收。
- 知识库历史向量与 SQL 覆盖仍不完全一致，后续应补一次可审计的重建/对账；本次没有重建索引。
- 前端首页和后端健康接口已返回 200，但没有用具备 `kb_id=14` 权限的登录用户完成浏览器端上传、选择知识库和问答全链路验收。
