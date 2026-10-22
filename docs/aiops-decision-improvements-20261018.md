# 调查结论改进与免费验收

日期：2026-10-18。分支：`codex/termcp-aiops-integration`。

本轮完成结论判断、调查记忆、页面与评测同步，以及免费回归和历史重放。真实模型自主调查能力仍未通过新的盲测，不能把本轮规则通过称作阶段二整体通过。未新增付费调用，未更新常驻 Probe，未正式部署、提交或推送。

## 前后效果

之前：已经采到入口 HTTP 503、下游 TCP ConnectionRefusedError，但因不知道下游为什么停止，最终把整场调查写成未定位；部分支持故障的引用被模型写为 excluded。

现在：调查仍优先继续合法的新检查；停止时，程序从当前目标、当前业务范围、有效时间和 hash 均通过校验的现场记录中保留故障层。可以报告“入口 HTTP 检查失败、配置下游 TCP 探测失败，更深原因未明”，不会因此报告数据库崩溃或服务被谁停止。原始模型建议与修正后的判断分别保存。

## 实现位置

| 位置 | 实现 |
| --- | --- |
| `src/agent/aiops/observations.py` | 按采集时间选取同查询范围最新 Probe 返回，过滤业务范围；实际 truncated/error 控制负面判断；TIME_WAIT 不算 LISTEN；进程缺失要求配置与完整查询，端口 PID 不符保留关联引用 |
| `src/agent/aiops/strategies/investigation.py` | 新增共享的纯判断入口 `decide_from_evidence`，实时调查与历史重放使用同一路径；先继续有效检查，停止后才保留独立核验的故障层 |
| 同上 | 替代解释支持 supported；有限 condition 校验操作、对象、字段、合法取值、引用方向和一致性；因果解释不因字段匹配变成已排除。缺失或反向依据降为 unresolved，保留 original_status、model_suggestion 和 validation_issues |
| 同上 | 调查记忆与 diagnosis 增加 observed_findings、unresolved_questions、validation_issues；问题使用稳定 ID；不直接修改传入状态或模型对象；等待模型后重新校验新鲜度 |
| `frontend/src/views/AIOps.vue` | 显示现场发现、未决问题、判断校验及可点击证据；旧报告仍兼容，原文继续受审计权限约束 |
| `scripts/verify_windows_local_faults.py` | 评测分别输出机械检查、流程完成、结论级别和待人工语义审核；保留 passed 兼容，其含义仅为机械门，不代表能力通过 |
| `scripts/replay_aiops_decision.py` | 只读历史 checkpoint/运行账本/证据文件；核对归属和完整性，按当时 checkpoint 时间验证证据，输出到原运行以外的新目录；不调用模型或目标工具 |
| `scripts/verify_windows_probe_graph.py`、`verify_windows_probe_browser.py` | 免费调查图、持久化与正式 API/浏览器消费者对照结构化结果，不继续以报告首行作为能力判定 |

API、SSE 和 checkpoint 原本传递可选 diagnosis 字典，本轮复用该契约，没有新增表或迁移系统。浏览器经正式登录和 API 验证新增字段可以恢复展示。

## 本轮验证

| 检查 | 结果 | 能证明什么 |
| --- | --- | --- |
| 五组相关后端测试 | 117 passed | 分级、条件方向、非法值、不同对象、错误目标/过期/hash/截断、继续调查、checkpoint 与重放拒绝 |
| 最终全量离线 pytest | 615 passed、99 deselected、1 warning | 默认离线回归通过，99 项集成测试未运行 |
| 前端 Vitest | 16 文件、86 passed | 新字段展示与历史报告兼容 |
| 前端生产构建 | 通过 | 可构建；保留既有大 chunk 提示 |
| Compose 静态检查 | 通过 | 配置语法与插值；既有 version 过时提示，不证明容器运行 |
| 本机临时采集链预检 | 24 项通过、44 条现场证据、0 模型调用 | 临时 Probe、MCP、SQLite、知识接线、故障控制、重连和持久快照 |
| 正式 API + Edge 浏览器 | 普通/审计用户各 2 场通过，每场 4 条证据 | 新结论与现场发现展示、证据链接、重载、跨拥有者拒绝、显式审计读取原文；不是正式部署 |
| 历史真实模型结果重放 | original=unlocated、replayed=localized_fault | 旧证据进入修正后生产判断路径会保留故障层；0 新模型调用、0 新观测、原文件 hash 不变 |

早期相关回归因缺少 unresolved_questions 抛出 NameError；之后修复了 HTTP 故障标签遗漏、旧结论预期和新增记忆字段的整字典比较。后续相关及最终全量回归通过，不能把中间失败记录抹成始终通过。PyMilvus 警告属于既有 ORM API 弃用提示。

## 可追溯产物

- 免费链路：`runtime/windows-local-faults-cf0fb7de67544b9b89d19ec74f0c7c14/summary.json`、`evidence.json`。所有自建进程已退出，remaining_listeners 为空、ports_released=true。
- 浏览器：上述目录下 `browser-verification-c9d4bc322d064bb8a5289d5befb7af41/summary.json` 与四张页面截图；独立数据库和 checkpoint 副本，source_modified=false，临时端口已释放。
- 历史重放：`runtime/decision-replay-0708efe5e4df4cc1b3c7ade50fde534a/replay.json` 和 `report.txt`；包含原始文件 SHA256、当时校验时间、模型原始建议和新判断。
- 原始真实模型失败结果仍保留：`runtime/windows-local-faults-d3ae4aeb3f8349d8b7662591844f2a1f/model-8dc6a8572d884aea925369dc19def623`，未改写为成功。

收尾时已用最终代码重新执行历史重放，仍为 localized_fault；原文件 hash 保持不变。自动测试覆盖同一生产判断入口与重放路径。

## 仍未验证的能力

1. 新版真实模型是否在不知道答案时自主选检查、避免重复，并稳定给出合理的故障层/健康范围结论。本轮没有新付费调用，历史重放和固定决策流程不证明模型自主性。
2. 知识库是否改善真实调查。免费链证明规划前和调查中知识接线；没有新真实模型知识开关对照，也没有外部 embedding/重排验收。
3. 日志引用的自由文本因果关系仍需独立人工审核。有限 predicate_verified 只证明字段条件，不是任意自然语言解释的语义证明；模型将因果句误标成 observed_condition 仍需盲测与复核发现。
4. 常驻 Probe 更新与 LocalService 业务日志权限、真实 Termcp UI、Compose/TLS 运行部署及真实业务对象验收仍属阶段三，未由本轮测试替代。

下一顺序：新费用授权后先复验正常和下游不可达；正常只能报告被覆盖的具体范围，下游只定位连通层。两场通过并经人工复核，再做知识开关对照及其余故障。既有累计预算账本保持原样，不重置、不将保守预留按 usage 估算返还。
