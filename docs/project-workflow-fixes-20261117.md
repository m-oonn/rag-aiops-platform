# 项目调查流程逐项修复记录

日期：2026-11-17。承接[原批判报告](project-workflow-critique-20261117.md)，原报告与初次失败保持原样。本轮修复流程交接和审计能力，不消耗历史模型预算。

## 已实现的交接

| 原问题 | 当前处理 | 验收依据 |
| --- | --- | --- |
| 监察身份不能回读本轮证据 | 仅持久事故已关联的系统运行可回读本轮证据 | 系统身份、真实证据文件、越权拒绝回归 |
| 人工待审误记失败 | 保存 pending_review 和草稿，同线程恢复并同步原事故 | SQLite checkpointer 关闭重开与审核记录 |
| 管理员不能复查系统运行 | 限管理员访问与事故关联的 run | run、steps、evidence、tool-calls 权限回归 |
| 页面缺实际工具调用 | 正式 Diagnosis 展示提议/实际参数、拒绝、结果、耗时、截断 | 页面和组件回归 |
| 步快照查询错误伪装为空 | 区分 available/empty/disabled/partial/write_failed，关联调用、证据和决策 | 快照故障与关联回归 |
| 规划内部 RAG 缺账本 | retrieve_experience 进入同一工具账本，记录空结果与不可用原因 | RAG/PDF/规划回归 |
| 监察仅有 up | 白名单 HTTP 和桌面快照适配；保留测量值、阈值、原始证据；缺失/过期/模拟为 unknown | 本地真实 HTTP/Probe/SQLite 预检及明确合成的桌面单测 |
| 经验只能读不能沉淀 | 有报告和证据的完成诊断自动生成 pending 候选，管理员发布到自己的 BM25 库，可拒绝/撤回 | API→解析→分块→SQL→下一次实际关键词检索 |

候选保存来源运行、脱敏报告及哈希、目标范围、证据 ID/时间/哈希、工具参数、状态、拒绝、耗时及最多 800 字符的结果节选。超限标记截断，可回查原工具账本。账本本身仍有 64000 字符上限，非 Probe 的超长结果尚无统一完整原文归档，不能把节选称作完整输出。候选和审核均不是独立根因确认。未完成、无报告或无留存证据的运行不自动晋升经验。

发布复用 MultiDocParser、TextChunker、KnowledgeDocument、DocumentChunk 及既有文档预览/检索，不调用 embedding、重排或生成模型。SQL 事务提交文档、分块和发布状态；文件/解析/分块失败回滚，候选保持 pending。当前每个来源运行保留一个不可变 v1 快照，没有原地编辑及多版本修订功能。

撤回保留来源文档与审核历史。本地检索过滤发布状态；混合/向量检索返回缓存结果前再次核验，知识 MCP 按文档 ID 回读也拒绝未发布/已撤回经验。状态库不可读时不返回无法核验的 SQL 文档。撤回前已交给模型的上下文不会被追溯删除。

## 监察配置与限制

本轮未修改生产 .env。以下为接线示例，别名、路径、端口与阈值必须按现场核实，不表示已经启用：

    OPS_WATCH_ENABLED=true
    OPS_WATCH_SERVICES=mall-api,dsh
    OPS_WATCH_INTERVAL_SECONDS=30
    OPS_WATCH_STALE_AFTER_SECONDS=120
    OPS_WATCH_AUTO_DIAGNOSE=false
    OPS_WATCH_PROBE_CONFIG=D:/ragPdfSystem++agent/runtime/local-probe/config.toml
    OPS_WATCH_PROBE_CHECKS='{"mall-api":{"kind":"http","dependency":"mall-business","max_elapsed_ms":500},"dsh":{"kind":"desktop","path":"D:/ragPdfSystem++agent/runtime/dsh-live/runtime.json","max_event_loop_lag_ms":200}}'

Probe TOML 必须已登记 mall-business 的真实 host/port/health_scheme/业务 health_path，以及 dsh 的 kind=process、真实进程和 text_logs 白名单。环境变量不能替代白名单。未登记 Probe 检查的服务继续走 Prometheus，需配置真实后端和标签。

桌面 JSON 协议：recorded_at 带时区、simulation=false、errors 为字符串数组。新鲜异常可判异常；证明正常还必须 window_complete=true 且 event_loop_lag_ms 为真实测得的非负有限数值。宿主/插件版本和栈可留在原文。没有常驻采集器时不得手工把模拟数据改 false、把历史时间改现在；阈值必须按相同负载正常基线校准。

HTTP 状态 200–399 且总耗时不超阈值才记该次正常。总耗时包括 DNS、TCP、HTTP 读取，不能据此直接确认应用内部慢原因。一个服务当前登记一个检查，不是完整错误率/多指标关联分析。

OPS_WATCH_AUTO_DIAGNOSE=true 可能调用付费模型，仍受单独授权和唯一预算账本限制；本轮未启用。

## 免费可复做预检

    .\.venv\Scripts\python.exe scripts/verify_watch_signals.py --output runtime/watch-preflight-new --dsh-snapshot runtime/dsh-evidence-20261117/live/console-stack.json

输出目录必须是新的。脚本在回环地址临时端口运行真实 HTTP 服务，经真实 WindowsCollector 读取 503、200 慢响应和正常响应，保存隔离 SQLite 事故、逐次参数/返回、触发摘要和恢复结果。不启动诊断，不发模型请求，不接管 mall。finally 停服务并核对线程停止和端口释放。

signals-live-01 已通过：三次新鲜 503 开事故，200 慢响应仍异常，两次新鲜正常响应关事故；历史 DSH 栈保持 unknown，线程已停、端口释放。桌面分支另用明确合成单测验证，不能替代当前 DSH 新鲜采样。

## 页面与 API

完成诊断后页面“经验复用”展示正文、来源、状态及审核历史；无候选可显式补建，读取错误单独提示。管理员选择自己拥有的 BM25 库并填写意见才能发布，可拒绝或撤回。普通用户没有审核按钮，服务端同时强制管理员和知识库所有权检查。

- GET/POST /api/v1/aiops/runs/{thread_id}/experience：读取/补建候选，沿用运行所有权及系统事故管理员权限。
- POST /api/v1/aiops/runs/{thread_id}/experience/review：publish/reject/withdraw，保存审核人、时间、意见、版本与文档编号。
- 既有 /review 仍处理报告人工审核，与经验审核及终端审批分别执行。

新增 aiops_experiences 表沿用 metadata.create_all，不改已有表字段。来源材料不重写；经验文件位于 UPLOAD_DIR/aiops-experience。本轮仅在隔离库验证发布，没有向生产知识库发布经验。

## 失败和验证记录

原始 batch-01 至 batch-34 保留；续接读取、实际命令、工具返回、补丁、失败换路从 batch-35 顺序追加。平台截断的输出仍标明截断，不补造未返回全文。

- signals-check-01：15 passed/1 failed，旧 Prometheus 缺 data_source 被误写 healthy；修后 signals-check-02：16 passed。
- experience-red：接口缺失时 7 failed；实现后 experience-check-01：7 passed。
- experience-cache-red：1 failed/6 passed，暴露混合检索缓存返回撤回经验；修后扩大知识回归 experience-check-02：28 passed。
- signal-context-and-vector-red：2 failed/9 passed，暴露触发摘要漏测量值、字符串文档 ID 绕过撤回比较；修后 boundary-check-01：14 passed。
- experience-frontend-red：缺组件而失败；修后 experience-frontend-check-01：19 passed（组件 4、正式页面 15）。
- integration-check-03：72 passed，4 条既有 PyMilvus 弃用警告。更早 integration-check-02 的 139 passed 是另一集合，不相加成唯一通过数。

final-check：17 个定向测试文件 223 passed，6 条既有 PyMilvus 弃用警告，覆盖身份/审核/快照/监察/执行器/调查/RAG/BM25/混合与向量检索；没有与早期不同集合累加。frontend-final：19 passed，frontend-build-final.log 构建成功。首次构建临时文件权限失败及工作区 TEMP/TMP 换路记录仍保留在旧批次。

signals-live-02 的恢复断言失败：第一条恢复响应实测 55ms，超过受控预检的 50ms 阈值，因此仍异常；下一条 26.3ms 只构成一个健康样本，产品正确保留事故。失败、参数和清理通过记录均保留。随后仅调整受控夹具为 500ms 阈值与 1200ms 注入延迟，扩大正常/异常间隔，不放宽产品判定规则。signals-live-03 已通过，使用新目录保存：三次 503 开事故、200 慢响应仍异常、两次新鲜正常响应完成恢复，历史 DSH 栈保持 unknown，线程停止且端口释放。

## 未完成的现场验收

本轮未调用付费模型、未运行 mall 正式页面真实自主诊断，没有改写历史 mall 结果、唯一预算、未知费用及初次失败。DSH teamMembersOf 现场栈保留可追溯，但完整成员功能恢复、卡顿根因及常驻新鲜性能采集尚未验证。未知项目原因覆盖率、机制收益、长期持续运维稳定性不能由这些回归推导。
