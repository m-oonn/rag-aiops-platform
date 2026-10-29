# AIOps 开源思路融合：实施与免费验收记录

日期：2026-10-18。分支：`codex/termcp-aiops-integration`。

阶段一的调查基础、接口和页面已实现，并完成本记录所列免费验证。阶段二已实现盲测控制和知识开关，完成免费预检；真实模型未知答案调查与知识作用对照尚未运行，本计划没有新增费用授权。阶段三未执行更新常驻 Probe、真实 Termcp UI、Compose 运行部署或真实业务接入。不能据此宣布全部计划完成，不能把测试数量换算成根因定位准确率。

## 设计融合与实现位置

参考固定提交、源码链接和许可记录沿用 [源码调研记录](research/github-aiops-reference-review-20261018.md)。吸收设计，没有复制上游代码，也没有升级 Termcp。

| 思路 | 实现位置 | 具体行为 |
| --- | --- | --- |
| HolmesGPT：核实目标与工具、大结果回读 | `src/agent/aiops/target_catalog.py`、`planner.py`、`evidence_reader.py` | 先读 inventory/状态，精确解析登记对象，与现场白名单核对，按运行证据 ID 回读 |
| K8sGPT：先识别确定性现象 | `src/agent/aiops/observations.py` | 服务未运行、完整查询进程缺失、端口和依赖异常作为线索，不直接解释深层原因 |
| Pi：工具前后事件、调查记忆 | `executor.py`、`strategies/investigation.py`、`state.py` | 参数守卫、脱敏执行状态与耗时、关键引用和未决解释持久保存，重复检查按具体参数范围判断 |
| Kagent：审批与运行状态绑定 | 复用既有 `termcp_tools.py`、持久 checkpoint | 保留原审批流程和过期修复，本轮没有改写审批节点；真实 UI 重验留阶段三 |
| AIOpsLab/ITBench：控制器与调查分离 | `scripts/verify_windows_local_faults.py`、`evaluate_windows_probe.py` | 随机场景、固定中性症状、独立答案记录、累计费用、轨迹与语义判定分离 |

## 业务目录与权限

继续使用 `DIAGNOSTIC_TARGET_CATALOG`、`SERVICE_ALIASES`，不建立另一套 CMDB。新结构示例：

```json
{"version":1,"target_id":"windows-local-01","services":{"orders":{"aliases":["订单"],"entries":{"http://127.0.0.1:18080/health":"orders-entry"},"probe_service":"orders","expected_ports":[18080],"log_refs":["orders"],"dependencies":["database"]}}}
```

目录表达预期，inventory 表达本次现场允许对象。只有精确服务名、完整别名、登记 URL 唯一匹配才定位；冲突、未知 URL 和无效新目录停止业务调查并返回未定位及候选。主机概况不自动查所有业务依赖。旧文本/旧无版本目录仍作参考，实际采集仍由 Probe 本地配置决定。原监控、日志和变更别名逻辑保留。

Probe inventory 现在公布每个获准服务的 `text_logs` 路径/模式，让模型能构造已有 `probe_text_log(service,path)` 查询；不公布 token、CA 或网关配置。路径仍受 `allowed_text_path` 和打开句柄校验，没有扩大白名单。常驻服务使用安装副本，工作区此改动尚未部署，旧服务不一定公布路径。

## 四类结论与证据门槛

| kind | 用户含义 |
| --- | --- |
| `confirmed_cause` | 当前范围内有直接现场支持，关键替代解释有排除依据，无未解决矛盾 |
| `localized_fault` | 具体故障对象/层已定位，更深原因未知 |
| `healthy_within_scope` | 实际检查范围和时刻未见异常，不能推出整机、所有业务或长期健康 |
| `unlocated` | 未定位，保留事实、假设、缺失证据及停止原因 |

替代解释默认关键；标为非关键必须说明理由。关键 unresolved/unavailable 禁止确认根因。仅服务停止、进程退出、TCP 失败等快照不足以说明为何停止或是否数据库崩溃。localized 文案从通过校验的确定性线索组装，避免把模型猜测夹带成原因。健康结论要求正常服务/入口证据，登记业务还检查依赖、服务和期望端口覆盖；inventory 或短时资源快照不足以宣布健康。

Probe 证据先校验 target、platform、source、operation、时间、payload hash；等待模型后重验新鲜度。引用必须原文匹配。同范围不同结果以采集时间判断更新，旧引用冲突时阻止确定结论。截断/失败查询不能证明对象不存在。知识资料和 sandbox 分析不是主机现场证据。

这些规则不能以程序完全证明任意文本的因果语义。日志引用存在仍不等于引用支持模型因果判断，必须靠未知答案盲测与人工复核。旧 Linux/Termcp 证据保留调查和展示，但来源字段不完整时新分级策略保守降级，不能把历史裸字典升级成已验证根因。

## 回读、持久化与兼容

`read_run_evidence(evidence_id, query?, offset?, limit?)` 是应用内闭包工具，服务端绑定真实 user/thread；模型不能指定用户、运行、路径或数据库条件。只读本运行既有脱敏文件，校验归属、路径、打开句柄、目标、时间、来源、平台和 payload hash；文件最多 1 MiB，输出最多 16 KiB，query 只做字面匹配。

回读返回 `data_source=evidence_excerpt`、原始采集时间、hash、fresh、分页和 `new_observation=false`；不刷新时间、不新增账本或现场观测计数，另记 `action=evidence_read`。旧 checkpoint 的 eN.M 继续展示，无映射时不伪造 ev ID。payload hash 不构成签名，也不能抵御拥有应用/管理员权限的主动篡改全部元数据。

`diagnosis` 进入 state/checkpoint，经 `graph.py`、`events.py` 的 report/complete 与 `GET /api/v1/aiops/runs/{thread_id}` 传递；API 先核对运行拥有者。保留原 response/report 和状态，completed 只表示结束。没有增加迁移框架或第二套证据存储。

`frontend/src/views/AIOps.vue` 显示分级、范围、未决解释、限制、矛盾和可点击 ev 引用；旧运行标历史格式。沿用证据 API 和审计权限，普通用户不能读取原文。工具来源显示注册、可调用、离线、权限/认证失败、陈旧等状态，available 保留注册语义；注册未核验不显示正常。

## 实际免费验收

按相关回归 → 后端全量 → 前端测试 → 构建 → Compose 静态检查执行。

| 检查 | 实际结果 | 证明范围 |
| --- | --- | --- |
| 直接相关 pytest 五个文件 | 151 passed | 目录、分级反例、引用回读、重复保护、时间更新、控制器与费用守卫 |
| `python -m pytest -q` | 578 passed，99 deselected，1 warning | 默认离线回归；99 项 integration 未运行 |
| `npm.cmd test` | 16 文件、86 passed | 前端状态、分级和旧格式兼容 |
| `npm.cmd run build` | 通过 | 生产构建；既有大 chunk 提示 |
| `docker compose -f docker/docker-compose.yml config --quiet` | 通过 | YAML/插值静态检查；既有 version 过时提示，未证明容器运行 |
| 免费本机隔离故障链 | 24 项通过、44 条现场证据、0 模型调用 | 真实临时 Probe/MCP/SQLite 与控制器，不证明模型自主归因 |
| 正式 API + Edge 浏览器 | 通过，普通/审计用户各 2 次运行，每次 4 条证据 | 登录、owner 隔离、checkpoint 结果恢复、ev 链接、fresh 对照、重载、原文显式审计读取 |

后端 warning 为既有 PyMilvus ORM 弃用。收尾时新增路径测试曾因对字典字符串的转义表示做比较而失败，改为比较路径列表后通过。此前浏览器脚本曾错误假定刚采集证据必然陈旧，已改为对照 API fresh；原失败记录保留，未覆盖。

本轮完整故障链输出：

- [链路 summary](../runtime/windows-local-faults-1b430c74af714708a2c9d9aaf19dfc5d/summary.json)
- [现场证据](../runtime/windows-local-faults-1b430c74af714708a2c9d9aaf19dfc5d/evidence.json)
- [浏览器 summary](../runtime/windows-local-faults-1b430c74af714708a2c9d9aaf19dfc5d/browser-verification-a7c55d43a97e48dda373b3046f293af9/summary.json)
- [普通用户页面截图](../runtime/windows-local-faults-1b430c74af714708a2c9d9aaf19dfc5d/browser-verification-a7c55d43a97e48dda373b3046f293af9/fixed_model_graph_downstream_unreachable-normal-user.png)

控制器六类预检为正常、下游不可达、自身 500、应用退出、端口冲突、关键证据缺失场景设置。缺证据在模型模式通过隐藏日志工具和限制 downstream 查询实现；删除日志本身不能保证请求后不重新生成。两次完整 LangGraph 调查使用固定决策替身，核对目录与白名单、规划/调查中知识传递、规范 ev ID、证据回读不增观测、checkpoint 重开；均诚实报告未定位。未停止真实服务，未制造整机 CPU/磁盘故障，所有测试进程退出、端口释放，浏览器使用独立数据库和 checkpoint 副本。

免费复验命令：

```powershell
& .\.venv\Scripts\python.exe scripts/verify_windows_local_faults.py --evaluation-preflight
& .\.venv\Scripts\python.exe scripts/verify_windows_probe_browser.py <上一步输出目录>
```

## 阶段二与三仍需验收

真实模型入口默认不执行；只有显式 `--run-model` 才进入付费模式。先 smoke 两场，再经人工 smoke-review 扩展四场；后续阶段要求 previous-cost 继承累计账本，重试不重置额度，未知成本或额度耗尽即停止。场景运行标识随机、症状中性，答案不传 prompt/知识/允许日志。控制器文件在受保护测试根目录中，Agent 工具没有任意文件读取能力；这不是 OS 级隔离沙箱的证明。

机械复核保存目标、当次 ev ID、现场原文片段、允许工具、期望结论级别；另留人工 correct_localization / honest_unlocated / wrong_cause_or_false_positive / incomplete 裁决。机械原文存在性检查不能替代逐引用语义支持审核。工具轨迹、模型请求、结构化结果、累计费用和恢复分别留档；本轮未产生真实付费结果。

知识对照开关同时关闭规划前注入和调查中检索，重置同一故障条件，使用同模型/中性症状。当前只证明免费本地手册词法检索和接线，没有证明知识提高真实诊断效果，也未验证外部 embedding/重排。

阶段三按原计划单独执行：测试副本通过后更新常驻 Probe、核验 LocalService 日志权限；真实 Termcp UI 验证批准一次、拒绝、过期和跨进程等待恢复；Docker 可用后实跑 TLS/隔离/持久化；最后接入用户登记的真实业务对象。普通调查崩溃的通用恢复仍是独立待验能力。

本轮没有提交、推送或正式部署，没有新增付费调用，工作树既有修改和数据均保留。
