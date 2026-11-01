# 能力边界修复后 G11 单场复验结果（2026-10-30）

**本场失败，停在模型连接阶段，未验证新版结构化输出、知识查询或下游补查。** 用户在明确单场 G11、最多新增 24 次/累计 47 次、费用未知后回复“继续”，执行一次。实际新增 3 次连接尝试，全部 ConnectError，未取得 HTTP 响应或 usage；累计账本为 26 条，实际金额未知。没有重开场次、换模型或追加真实调用。

## 1. 来源、时间和边界

- 准备协议：[能力边界修复后G11单场复验准备](g11-boundary-fixes-retest-protocol-20261030.md)。准备时的“未授权”状态保持历史原样，后续授权与执行另存 `runtime/g11-retest-preparation-20261030-a/execution.json`；该文件已存在，一次执行入口拒绝再次启动。
- 控制器：`runtime/windows-local-faults-8cb1f5c48486489faa80ffbf0dfdf698/`。
- 模型子场：其下 `model-d775dd96ddc141f5b65f2e850ba2e755/`。实际源码仍是准备时的 `f0c568e` 及 135 份选定源码，运行快照与准备逐项一致；下述发送门槛和审计修复晚于本次运行，不能算入本场。
- 北京时间 2026-10-30 **10:11:26—10:12:47**，控制器 80.69 秒；子场 `run_model` 65.77 秒，两种计时范围不同。
- 主/简单/证据模型仍为私有 profile 指定的 GLM；SDK 重试 0、Agent 重试关闭。服务、端口、数据库、thread、证据及知识夹具独立，本场重置前观测边界有效，禁用共享历史。

## 2. 实际失败过程

| 累计编号 | 调用位置 | 结果 |
| --- | --- | --- |
| 24 | 初始 Plan | 连接阶段约 21.04 秒失败，无 HTTP 状态、响应正文、usage；未发生可恢复格式降级 |
| 25 | 执行器 | 再次连接约 21.04 秒失败，无 HTTP 状态及 usage |
| 26 | InvestigationDecision | 再次连接约 21.05 秒失败，策略返回 `model_request_failed / APIConnectionError`，保留失败报告，图落失败 |

三次是不同逻辑位置的请求尝试，不是 SDK 默认重试复发。初始规划异常被 `planner` 捕获后产生默认三步计划；执行器又把请求异常转为步骤结果，因此继续到了调查决策。默认计划不是 GLM 成功生成的计划，步骤完成事件也不等于完成了检查。

这暴露了**本次承诺的失败停止条件执行不完整**：前两次连接失败后程序仍尝试后续发送。虽然未超新增上限，也没有另开场次，但不能将其写成“首个失败后即停止”。已保留三次尝试及失败链，并在本场结束后免费修补发送门槛。

实际只有自动采集的 `probe_inventory` 一条有效现场观测；没有入口/下游依赖探测、监听、映射进程、独立日志或知识查询。第25条准备的工具 schema 已含知识库 enum/default 14，记录的 `knowledge_kb_ids=[14]`，但请求没有取得响应，不能据此宣称真实知识检索通过。控制器知道的故障事实不计为 Agent 自主采证。

最终有失败报告和 error，没有 complete，`workflow_completed=false`；机制行为 `not_assessed`。外层机制审计异常是未形成有效决策轨迹的结果，不是第一处失败原因，也不证明两个机制配置错误或无效。

## 3. 免费网络排查：查到哪里，哪里仍未知

记录在准备目录的 `connectivity-after-failure.json`、`public-dns-comparison.json`、`fixed-ip-dns-comparison.json`、`domestic-dns-comparison.json`、`apex-domain-comparison.json`。均为公开 DNS/TCP/TLS 核对，不携带模型凭据，不发送推理请求。

- 当时本机将 `www.rightapi.ai` 解析为 `31.13.83.34`，直接 TCP 连接在 5 秒检查窗口超时。三次实际模型尝试也均停在 connect 阶段，不是等待 HTTP 响应头的历史 ReadTimeout。
- 同时对 `api.deepseek.com` 的 TCP/TLS 核对成功，TLSv1.3；只证明该公开端点在当时可连接，不是 DeepSeek 推理或 Agent 对照实验。
- hosts 没有 RightAPI/DeepSeek 相关覆盖；WLAN DNS 为 `192.168.5.1`，当前 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 未设置。这些是当时本机状态，不能反推历史环境。
- Google/Cloudflare 的域名 DNS 查询均未成功，固定解析器 IP 的 HTTPS 检查分别遭连接拒绝或超时；AliDNS/DNSPod 的查询返回不同地址。这些差异不足以确认权威地址或 DNS 劫持。RightAPI 裸域与文档域在本机的连接核对也失败。

**已确认本场阻塞发生在域名到连接的链路上，尚不能分离本地/路由器 DNS、上游网络策略、域名配置或供应商接入侧原因。** 未获得可用的独立权威解析及供应商侧记录，不能把失败归因于 GLM 模型本体或结构化 schema，也没有擅自修改 DNS、hosts、系统代理或模型端点。

## 4. 本轮免费修复

`PaidRequestBudget.reserve()` 增加实际发送前的已用量核对，由 Windows 与原自主评测两个 HTTP transport 显式启用。只要前一条尝试失败或缺 usage，下一次请求在预留和 HTTP 发送前拒绝，理由为 `previous_request_usage_unknown`，记 `blocked_requests(sent=false)`，不增加真实尝试计数。

这一门槛位于评测发送入口，即使上层规划/执行器继续降级，也不能继续产生实际模型发送。Windows 入口复用原失败/预算收束；没有改普通产品路径的默认计划逻辑，也不宣称图已在初始规划异常处立即终止。纯预留模拟保留旧行为，不能把模拟账本拿来实际续接。

实际失败材料还暴露记录审计读 `row['served_model']` 的 KeyError：连接失败本来就没有此字段，原审计会在记录“响应元数据不完整”后提前结束，遮住后续问题。改为保留未知值并继续核对，其失败门槛不变。修复后本场仍拒绝比较，能够完整列出无 complete、调查未完成、元数据与 usage 缺失等问题；没有把缺值补成供应商响应。

## 5. 验证与审核

连接失败后再调用、缺 usage 后再调用两个反例先失败，修复后仅第一次到达模拟 HTTP transport；成功且 usage 完整的正例仍可继续。发送门槛修复后相关六文件 **331 passed、1 deselected**，默认后端全量 **1335 passed、99 integration deselected**。随后 served_model 缺失遮挡后续审计的反例先失败；一行修复后相关六文件 **332 passed、1 deselected**。保留既有 PyMilvus 弃用警告，各阶段测试数不相加。

最终默认后端全量 **1336 passed、99 integration deselected、1 warning**，JUnit 为准备目录 `backend-final.xml`；相关332项包含在全量内，不累加。模型测试使用 MockTransport，不消耗模型；默认全量包含专用临时业务的真实故障/恢复与清理单测，它们是控制器回归，不计自主诊断样本。前端和浏览器没有重跑。

`outcome-audit.json` 核对本场135份源码、23条原前缀、三条连接失败、原时间窗口下的一条 inventory、恢复和清理；`record-integrity-after-fix.json` 保留更完整的拒绝理由。329份文本材料检查未发现现有模型凭据。机械审核中结构/引用检查可通过，但 `workflow_status=incomplete`、`capability_passed=false`；不据失败报告存在而计诊断成功。独立 human-review 包的诊断、引用、建议三维均为 pending，没有 AI 代填人审。

## 6. 费用、恢复与下一入口

- 最新链为 **26 条**，前 23 条逐项不变；新三条缺 usage，费率/实际金额未知。原13/16/23条账本 hash 不变，不把连接失败推定为0费用。
- 最新账本位于本次模型子场 `cost.json`。`read_cost_ledger(..., for_resume=True)` 已实际核对会拒绝：**不能退回23条、使用模拟账本或仅凭剩余额度绕过未知用量继续跑。** 以后即使连接恢复，也需先明确未知用量的核对/处理方式与新的有限范围。
- 控制器恢复 `normal_restored`，所属进程停止、端口释放、cleanup_errors为空；5273/8200/8105执行前后无监听，常驻服务未操作。
- 阶段E仍未完成。下一步优先免费核对 RightAPI 接入地址与本机解析/连接条件；有可核验的新网络条件及用量处理方案后，再准备独立有限调用，不原样反复付费试探。知识范围、结构化输出及下游补查仍待真实模型验收，四组实验和人工语义审核不能提前宣布通过。
