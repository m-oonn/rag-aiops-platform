# 请求头与代理路径免费核对（2026-10-28）

## 结论

**后续真实执行更新：用户确认后，仅对齐UA的候选已发送一次。北京时间2026-10-28 14:16:38—14:18:32，约114.00秒收到HTTP 502；不是本轮客户端ReadTimeout。实际UA=Python-urllib/3.13，JSON正文与上次最小schema请求一致，无重试。以下尚未发送的描述为免费准备时状态，以本段及末尾执行记录为准。**

本地已确认原Agent与独立重放存在User-Agent、Accept及SDK附加头差异；两个现有评测/重放入口都使用显式自定义HTTPX transport，不自动装载环境代理路由。没有发现可直接认定为本次超时根因的配置错误。免费准备完成，未发送新的模型请求，当前仍处于阶段E前置排障。

## 调用链与请求头

原评测入口evaluate_windows_probe._run_model通过create_agent_llm构建ChatOpenAI，随后替换底层HTTP客户端为BudgetTransport；后者保留SDK请求头、重序列化JSON并发送到显式AsyncHTTPTransport。独立replay入口直接用HTTPX和诊断transport发送历史JSON。

用实际create_agent_llm及当前OpenAI SDK配MockTransport重新捕获请求（构造离线消息、虚构凭据，不访问供应商），得到：

| 字段 | 原Agent工厂/SDK | 独立HTTPX重放 |
| --- | --- | --- |
| User-Agent | Python-urllib/3.13 | python-httpx/0.28.1 |
| Accept | application/json | */* |
| Accept-Encoding | gzip, deflate, zstd | 相同 |
| Content-Type | application/json | 相同 |
| Connection | keep-alive | 相同 |
| SDK附加头 | x-stainless-* | 无 |

仅保存允许字段值、请求头名称和authorization是否存在，不保存密钥、任意请求头值或回答。该捕获是当前代码的离线重建，不是历史HTTP报文存档；不能据此补写当时的精确头部。原工厂关于其他供应商UA拦截的注释不能作为RightAPI故障证据。

原Agent首次失败时按现有工厂已配置Python-urllib/3.13，因此UA差异不是该首次失败的充分解释。对齐UA只能核对独立重放是否受到额外头部差异影响。

## 代理与TLS口径

当前HTTPX代码为allow_env_proxies = trust_env and transport is None。两个现有入口均显式传入自定义transport，内层AsyncHTTPTransport没有proxy参数，因此采用AsyncConnectionPool而非HTTPProxy池。retries默认0或显式0，HTTP2未开启。

在测试中注入虚构HTTPS_PROXY后，普通AsyncClient选择代理路由，而自定义transport客户端无代理mount且仍选择自身transport；全程不建立连接。实际专用profile继承环境的只读检查也得到proxy_mounts=0、inner_pool_class=AsyncConnectionPool。当前HTTP_PROXY/HTTPS_PROXY/ALL_PROXY均未设置，NO_PROXY存在；系统代理发现仅有no键。只保存存在性，不保存代理地址或认证。

trust_env对TLS证书环境仍可能生效：当前SSL_CERT_FILE和SSL_CERT_DIR均存在。两种入口使用相同的默认TLS处理，未改证书或关闭验证。历史环境快照缺失，不能将当前状态倒填到旧请求。这里排除的是本地HTTPX自动环境代理路由差异，不能排除VPN、透明代理、DNS和供应商内部中转，未进行网络抓包或实际链路追踪。

## 已准备的单因素候选

专用replay脚本新增user_agent_variant=httpx/agent，默认httpx；agent仅设置User-Agent=Python-urllib/3.13。Accept仍为*/*，不添加x-stainless头、不改代理或生产配置；实际发出时只记录受控UA值。计划额外绑定src/agent/aiops_llm.py源码hash。

runtime/rightapi-agent-ua-20261028-a/plan.json已用私有profile免费生成，无attempt.json。其JSON正文与上次失败的hypothesis_only请求完全一致，实际wire body指纹仍为2ab11bd0423fd8f8e0ad60b27edefd6a039aad25a407f8ada579cb2e66bc7daf。保留最小schema、120秒、256输出Token、同模型及强制选择，仅改变UA。transport-audit.json保存当前脱敏捕获、环境存在性及旧结果hash。

若后续明确授权一次付费对照，可运行：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py -- scripts/replay_model_request.py --execute --plan runtime/rightapi-agent-ua-20261028-a/plan.json
```

一次HTTP尝试，不重试/重定向、不执行工具，不启动服务/故障。该候选尚未执行，不是继续调用授权，也不保证找到原因。成功只提供头部影响线索；失败仍不能直接认定GLM本身故障。历史估算不包括新增调用，未知费率和usage不回填。

## 验证与限制

最终6文件108项通过，runtime/transport-audit-tests-20261028.xml，保留1条既有PyMilvus弃用警告。新增UA测试在实现前2项失败，完成后通过；覆盖仅改UA且正文/Accept/一次请求不变、未知变体拒绝、虚构代理选路对照，以及原有隐私/绑定/结构化输出/重试回归。未把此前105项累计为213项。

本轮改动仅专用replay及测试、说明与AGENTS；未改生产Agent、全局模型/超时/代理、原账本或历史失败产物。本轮无模型/embedding/重排、无新现场/服务操作，未运行全仓、前端或浏览器；测试现有conftest可能检查本地Milvus/MinIO并降级，不代表供应商或实际网络验收。

## 单次UA对照执行结果

本节为首次UA对照，后续同条件再试见末节；分别留痕，不覆盖。

准备后用户明确确认执行一次。上述--execute命令退出1；attempt.json记录started_at=2026-10-28T06:16:38.497764+00:00、ended_at=2026-10-28T06:18:32.500570+00:00、elapsed_ms=114002.8193、http_status=502、status=returned。响应头累计约114002.35ms，正文读完累计约114002.81ms，failure_stage/error_type均为null：网络层已返回HTTP错误，不能将其重写成ReadTimeout，也不能把returned当模型调用成功。

实际记录UA为Python-urllib/3.13，wire_body_sha256为2ab11bd0423fd8f8e0ad60b27edefd6a039aad25a407f8ada579cb2e66bc7daf，与上一轮最小schema失败输入完全一致。502通常表示网关或代理未从上游取得有效响应，但本记录没有可归属的请求ID或错误正文，不能识别哪个网关、RightAPI渠道还是模型服务出错。此次等待较长与网关上游错误相容，不足以确定上游超时阈值或宣称所有历史超时都出于同一原因。

本次无finish_reason、usage或有效模型结果；错误响应正文按既有隐私口径未保留，不能事后编造错误详情。时段和供应商路由等未控制，单次由超时变为502并不证明UA有因果作用；原Agent此前已使用该UA仍失败。当前没有依据直接修改正式schema或诊断算法来解决502。

outcome.json绑定plan及attempt的hash，并核对旧账本、前轮结果和当前绑定源码未变。本计划已消耗；不追加请求、不执行工具、不启动服务或新故障。原$0.104769估算之后共四条独立诊断尝试，新增费用均未知，502不等于免费，不把费用回填成零。

本轮仅执行并记录结果，没有生产代码变化，未重复108项离线测试、全仓或浏览器；前轮通过数不作为本轮新增结果。下一步优先依据该时段核对RightAPI失败日志/渠道状态，或免费准备更短提示词对照；不自动继续付费探测，不声称已定位模型故障。

## 用户要求的同条件再试

用户随后明确要求“再尝试”，按相同参数仅追加一次请求；创建独立目录runtime/rightapi-agent-ua-20261028-b，不重复消费a目录计划。新旧plan内容逐项相同、request.json字节相同；repeat-context.json绑定前轮plan/attempt/outcome/transport-audit的hash。无代码或生产配置变化。

北京时间2026-10-28 14:21:52.706至14:23:52.925，耗时120218.1247ms，ReadTimeout/wait_response_headers；没有收到HTTP状态、响应ID、finish_reason或usage。本次并非502；之前一轮约114秒返回502，不能把两轮结果合并为同一错误。实际UA仍为Python-urllib/3.13，wire_body_sha256仍为2ab11bd0423fd8f8e0ad60b27edefd6a039aad25a407f8ada579cb2e66bc7daf。

独立attempt.json与outcome.json保存本次失败，新计划已经消耗；绑定源和前轮结果hash核对通过。仅一次发送，无自动重试、工具执行、服务启动或新现场。本次只做实际执行及结果核对，没有重复离线回归；原$0.104769历史估算之后共五次独立诊断尝试，新增费用均未知，不修改旧账本或推断超时免费。

相同请求两次分别为502与等待响应头超时，没有成功模型结果；仍无法区分提示词/特定请求处理、供应商渠道及网络链路原因。继续原样重试的信息增量有限，停止追加；后续优先核对平台该时段错误记录，或免费准备仅缩短提示词、其余条件不变的候选。未经新授权不自动发送候选，不将这些排障尝试计为自主诊断或四组效果。
