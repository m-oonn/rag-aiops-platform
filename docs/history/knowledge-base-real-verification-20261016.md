# 知识库与现场诊断联合验收（2026-10-16）

## 结论

知识库已经能被真实 AIOps Agent 使用，并能和受限现场诊断串成一次真实调查链路。联合场景中，Agent 先通过知识库 MCP 查询运维手册，再调用隔离目标上的诊断 MCP 获取健康检查、依赖连通性、端口、进程和日志证据；知识库只提供排查方向，最终判断仍以现场原始证据为准。

本次验收没有把“数据库未运行”硬报成已证实根因。现场证据明确指向数据库不可用，但测试目标没有提供数据库历史、配置来源或变更记录，因此报告保留为“未定位”，并列出无法排除的替代解释。这符合当前证据门槛。

## 实际运行

- 场景：隔离 `test-target`，`orders` 服务保留，数据库进程停止；用户只提供“核实订单服务是否可用”。
- 真实模型：`deepseek-v4-flash`（实际服务返回 `deepseek-flash`）。
- 业务 MCP 工具：指标、日志、知识库、变更共 14 个工具；自动调查模式过滤了任意网址/端口/业务接口探测工具。
- 诊断 MCP 工具：`diagnostic_query`、`diagnostic_probe_dependency`、`diagnostic_exec`。
- 费用账本：预留 4.05 元，上限 5 元；按实际 token 估算约 0.86 元。

知识库服务日志记录了真实 MCP 调用：

1. `list_knowledge_bases` 返回 12 个知识库，运维排查库为 `kb_id=14`；
2. `search_knowledge_base` 查询“订单服务依赖数据库不可用 连接被拒绝 排查手册”，命中运维文档并走本地持久化向量检索、BM25 和重排；
3. 返回结果包含 `source/page/chunk_id`，不是模型预置文本。

现场诊断返回了可追溯原始证据：

- `/health` 返回 503，响应体为数据库连接失败；
- 数据库 `127.0.0.1:15432` TCP 探测返回 `ConnectionRefusedError`；
- `/tmp/api.log` 记录 `database=127.0.0.1:15432` 和 `Connection refused`；
- 监听端口原文没有 15432（十六进制 `3C48`）；
- 全量进程列表只有 `api-worker`，没有数据库进程。

完整结果、事件和现场工具轨迹：[`results.json`](../../data/autonomous-model-evaluation/e3e3bc605a9946639e3a27368e556e99/results.json)。费用账本：[`cost.json`](../../data/autonomous-model-evaluation/e3e3bc605a9946639e3a27368e556e99/cost.json)。知识库服务原始调用日志：[`demo_rag.log`](../../logs/demo_rag.log)。

## 代码修正与验证

联合评测脚本现在支持 `JOINT_MCP=true`：加载真实四类业务 MCP 和隔离诊断 MCP，并在自动调查模式移除任意地址探测工具。调查报告在成功或“未定位”两种路径都会保留知识库来源小节，避免知识库证据只存在于中间事件而在最终报告消失。

相关回归测试：`21 passed, 1 warning`。warning 是 PyMilvus ORM API 弃用提醒，不影响本次实际检索。

## 当前限制

- 本次场景证明了知识库与现场诊断能协同运行，但没有证明所有故障类型都能一次定位；还需要正常场景、配置错误和应用进程停止等隔离剧本。
- 当前报告仍可能因为替代解释缺少现场数据而保持“未定位”；下一步应在诊断目录中提供配置来源/变更证据，减少模型重复检查。
- Compose 的 app/worker/Termcp/gateway/diagnostic-target 已在本机完成容器级联调。Compose app 通过 `host.docker.internal` 访问当前单机上的四类业务 MCP；生产部署时应把这些地址改成同一内网服务名。

## Compose 容器级复验（同日）

- `docker compose --profile termcp ps`：app、worker、Termcp、gateway、diagnostic-target、前端及依赖均为 `Up`。
- `GET http://127.0.0.1:8200/api/v1/health/health` 返回 200，前端 5273 返回 200。
- app 容器加载 22 个工具且无降级错误，包含知识库、现场诊断和 Termcp 会话工具。
- app 容器调用知识库 `search_knowledge_base(数据库连接失败, kb_id=14)`，真实返回 `source/page/chunk_id`。
- app 容器通过诊断 MCP 查询目标 `test-target` 的 catalog、进程、端口和 orders 日志，返回 `data_source=diagnostic_target`、采集时间和证据文件名。
- app 容器通过 gateway 调用 Termcp `session_list`，返回空会话且无认证错误。

为兼容 Windows Docker 的 SQLite WAL，Compose 将运行数据库和 AIOps checkpoint 放在 named volume；应用镜像继续使用 Python 3.10，并从 `typing_extensions` 导入 `NotRequired`。

## 证据链修正（同日）

联合重跑确认知识库 MCP 的原始返回已进入 LangGraph checkpoint，包含 `data_source=knowledge_base`、`source`、`page` 和 `chunk_id`。此前多个工具返回在执行器中以多行双重 JSON 拼接，报告格式化器没有逐行拆解，导致最终文本偶尔漏掉知识库引用；现已补充逐行解析，并增加回归测试。真实 checkpoint 复核可还原如下引用：

- `03-生产问题快速排查要义.md`，第 1 页，chunk `doc_a9301ce0-21af-4fbb-9217-6dd541ee2e0a_chunk_0`
- `02-接口响应变慢-分层排查法.md`，第 1 页，chunk `doc_bd1fe6d3-3b4a-4a8e-b270-5b728669f1d4_chunk_0`

本次修正后的离线回归为 `14 passed, 1 warning`；warning 仍为 PyMilvus ORM API 弃用提醒。真实模型联合调查结果保存在 `data/autonomous-model-evaluation/34f49649615745448e84c2d56b3f01fc/`，实际估算费用低于本轮 5 元授权上限；该次调查最终仍按证据门槛报告“未定位”，因为测试目标没有提供数据库历史/变更记录。
