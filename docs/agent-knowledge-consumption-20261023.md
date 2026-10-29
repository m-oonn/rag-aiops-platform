# Agent 知识消费与现场证据边界验收

日期：2026-10-23。范围：免费实现与离线验证，不是自主模型效果实验。

## 1. 本轮完成什么

核对规划前与调查中两条入口后发现：规划前 `_retrieve_experience` 忽略显式 `kb_ids`，始终初始化混检，且把来源压成纯文本；仅知识 MCP 支持新建本地 BM25 库。因此不能由知识库页面检索通过推断规划前已经使用该库。

本轮修改 `src/agent/aiops/planner.py`：显式 `kb_ids` 优先，其次使用既有 `settings.EXPERIENCE_KB_IDS` 逗号配置；根据 SQL 中知识库的 retrieval_mode 选择本地 BM25 或原混检。纯本地范围不构造 embedding、向量检索或在线重排器，即使全局 ENABLE_RERANK 开启也是如此。指定空范围、无效配置、库不存在、空库、无命中或异常时不扩大到其他库或内置 runbook；未指定范围时保留旧混检与本地 runbook 降级。

检索结果最多保留两条，每条内容经过既有压缩，携带 knowledge_base 标记、库/文档 ID、来源、页码与片段 ID。不同模式分数不可比，当前先保留本地库结果，再补混检结果；多个库可能因两条上限而未进入上下文。这里没有新增跨用户授权体系，规划前范围仍由系统配置指定。

规划前结果复用 raw_evidence 保存，既有 knowledge_context 分离为参考上下文，供执行器、调查策略和报告读取。raw_evidence 是原始返回容器，进入它不代表成为现场事实；evidence_index 仍按来源与 Probe 校验筛选现场记录。本轮未更改现场门槛或机制裁决。

`src/agent/aiops/evidence_sources.py` 补保留 kb_id、doc_id、source_url 和上游截断标记。调查中沿既有 MCP 工具调用路径检索同一 SQL 片段，最终报告保留 PDF、页码和片段引用。

## 2. 如何验证

新增 `tests/test_agent_knowledge_consumption.py` 在隔离测试 SQL 中真实处理仓库三份 PDF，使用测试库 901/902/903，不改主库 15 或原 PDF。在线检索、embedding、向量及重排构造被拦截；旧 hybrid 兼容测试使用替身，不发网络请求。

正式图验证复用 AIOpsService._build_graph、planner、executor、replanner 和 InvestigationStrategy。规划前真实本地检索，执行器调用真实 MCP 工具函数；模型决策固定，Probe 资源输入固定。分别验证只有手册、手册加资源观测两条链路：模型错误尝试用手册确认“应用内部异常”时，最终均为 unlocated；报告保留 02 手册第 2 页，现场索引分别为零条、一条。不能据此声称真实模型会自主选择正确工具。

`tests/test_investigation_mechanisms.py` 增加三类反例：只有知识、另有 TCP ok、另有 TCP failed。知识中即使嵌入格式合法的 Probe 示例，也不能进入现场索引、成为可靠反证或覆盖真正现场输入；TCP ok 对保存的 failed 预期触发改向时，事件只引用真正现场格式输入的 e2.1。这里的 Probe 内容仍为固定输入，不是本轮真实故障采集。

## 3. 实际检查结果

| 检查 | 结果 | 记录与限制 |
| --- | --- | --- |
| 首轮定向 | 24 通过、1 失败 | 新测试错误要求真实 PDF 命中段必须有“现场”二字；改为真实关键短语“应用内部异常”，未改 PDF |
| 修正并补反例后定向 | 118 通过 | runtime/knowledge-consumption-20261023-b.xml |
| 默认离线全量 | 837 通过、2 失败、99 integration 排除 | runtime/knowledge-consumption-20261023-full.xml；两项是已知 Windows 沙箱权限相关测试 |
| 两项正常权限复核 | 2 通过 | runtime/knowledge-consumption-20261023-permission.xml；保留首次失败 |
| 前端、外部集成、真实模型 | 本轮未运行 | 没有前端变更；保持免费，不替代正式效果实验 |

两项权限测试为 test_diagnostic_exec_kills_timed_out_process 与 test_restricted_token_can_access_control_but_not_protected_evidence。测试仍有四条既有 PyMilvus 弃用提醒。

正式图知识、最终报告与现场索引保存在 `runtime/pytest-knowledge-consumption-20261023-b/test_real_retrieval_consumed_b0/knowledge-investigation-trace.json` 和相邻 b1 目录；全量测试另有独立产物，不覆盖首轮失败输出。

## 4. 运行状态与下一步

本轮没有改 .env，没有硬编码知识库 15，没有重启服务或发起主页面诊断。常驻 API8200/RAG8105 上次重启已支持主知识库页面的本地检索，但本轮新增 planner 逻辑尚未在常驻 API 中重新加载；不能说主页面发起诊断已自动使用库 15。将来演示需在加载新版代码的进程中明确 EXPERIENCE_KB_IDS=15；该配置只保证规划前本地检索，不是整条诊断的免费调用开关。

计划阶段 D 的“真实 PDF 到知识消费与引用”的免费固定决策接线验收已完成；阶段 B/C 的自主模型机制表现、真实故障下知识使用及阶段 E 正式四组实验仍未验收。

下一步仍免费：在四组相同调查实现中联合核验固定知识条件、候选保留与可靠现场反证改向，检查完整轨迹可比较性；使用固定决策只验证程序行为。其后才准备真实模型小额预实验，继续遵守单独费用授权，不自动启动。

用户学习重点：能区分 raw_evidence 容器、knowledge_context 参考和 evidence_index 现场事实三者，知道为何有手册引用仍可能必须报告未定位。本轮完成系统验证，不据此认定用户已经独立掌握。未提交、推送或清理既有修改。
