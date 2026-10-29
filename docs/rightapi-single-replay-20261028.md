# 单次历史模型请求复验准备（2026-10-28）

## 当前阶段与交付

**执行结果更新：用户明确回复“执行”后，已消费该计划一次。北京时间2026-10-28 11:41:45至11:42:46，唯一请求约60.46秒后ReadTimeout，实际trace阶段wait_response_headers；没有收到HTTP状态、响应ID、finish_reason或usage。未自动重试、未执行工具、未采集新现场。** 以下“尚未执行”描述保留为准备时状态，以本段及末尾执行记录为准。

处于本科路线阶段E之前置排障：首次真实Agent调查未完成，先检查当时失败的重规划请求，再开展单场G11闭环。免费准备已完成，尚未发送本次模型请求。不是四组实验，也不是故障诊断结果。

新增 scripts/replay_model_request.py，复用现有read_cost_ledger的只读结构核验及record_model_response记录函数，经with_agent_test_env.py专用profile运行。没有修改正常调查续跑的未知用量门槛；用户认可的$0.104769历史估算以独立补充绑定，不回填旧usage、价格或供应商结算。

## 固定条件

- 历史源：windows-local-faults-79d30e0d36034514b8f579c8961ea39a/model-b3cbe816bde0409f8f54bfe9cbcaf5b7/cost.json第5条请求及model-inputs/5.json。
- 专用profile：RightAPI https://www.rightapi.ai/v1，glm-5.3-flash，凭据仅在进程内使用。
- 最多一次HTTP尝试，传输自动重试为0、不跟随重定向、60秒HTTPX超时、max_tokens=256、非流式。HTTPX的60秒为各网络操作超时，不是整次调用的严格墙钟期限。
- 保留历史JSON参数及原评测transport的序列化方式，不更改提示词、工具schema、temperature、上下文或输出上限。历史输入为当时保存的脱敏JSON，不能声称是原始未脱敏请求的字节副本；HTTP客户端请求头也不保证与旧SDK完全一致。
- 不启动服务/测试业务、不注入新故障、不执行返回工具、不运行Agent循环、不评估定位效果。历史工具名/路径不能视为本次实际可用对象。
- 当前供应商单价仍未核实：一次请求限制不能当作人民币硬封顶，也不能根据上次归集费用承诺本次价格。

## 准备产物与执行命令

已用实际私有profile运行默认准备模式，得到model_calls=0、max_attempts=1。计划在 runtime/rightapi-single-replay-20261028-a/plan.json，计划hash在plan.sha256。绑定旧账本、历史输入、费用补充、执行脚本、诊断脚本、launcher与账本读取代码的hash；任一变化必须重新准备。计划不含凭据。

收到单次付费执行确认后使用：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py -- scripts/replay_model_request.py --execute --plan runtime/rightapi-single-replay-20261028-a/plan.json
```

默认准备命令已经执行，不要再用相同输出目录重复准备。执行前独占创建attempt.json；一旦创建即消耗本计划，即使崩溃或取消也不原地重发。前置hash/profile核验失败时不会创建attempt或发送请求。计划hash用于检测本地误改，不是对恶意改写者的签名认证。

## 结果及停止条件

attempt.json记录独立新尝试、历史源引用、实际wire body指纹、usage与白名单响应元信息、耗时及失败阶段。保留旧账本，新的供应商费用继续未知。不保存回答正文、工具名称/参数、任意响应头、密钥或异常正文。

HTTP非200、超时、解析失败或取消均停止，不自动追加请求。HTTP200只说明取得JSON对象响应，不能证明结构化决策业务可用；退出码0也不作为诊断通过。核对finish_reason、工具调用数和usage：length时单独考虑输出上限；响应头阶段超时只定位本机等待位置，不能直接定因为模型或上下文。缺usage仍未知；本次结果不能补回旧请求的finish_reason或费用。

拿到响应后先分析：必要时免费核对原schema是否能解析该响应；由于当前仅保存元信息，业务解析深度有限，不宣称已完成结构化语义验收。然后再决定是否进行真实单场G11调查与其有限调用范围，不从本入口自动转入整场、扩展场景或四组。

## 验证

最终8文件234项通过，记录 runtime/replay-preparation-tests-20261028-b.xml；首轮78项包含在其中，不相加。新增入口15项覆盖单次发送、重复执行/准备拒绝、超时/429/重定向/坏JSON、取消、凭据缺失、源文件与条件变化拦截、隐私字段和未知用量续跑门槛。其余回归覆盖原Windows评测、四组控制器、失败状态、记录消费和profile配置。初始测试因实现文件尚未创建而收集失败，完成实现后通过。

仅1条既有PyMilvus弃用警告；测试启动时现有conftest会检查本地Milvus/MinIO并报告降级，不启动这些服务，不等于远程验收。没有真实模型调用、整仓全量、前端构建或浏览器检查；本次没有更改API/页面或LangGraph。

## 单次真实执行结果

本节为60秒轮次。用户随后明确要求延长至120秒再试一次，结果见末节；两轮分别记录，不覆盖原计划或结果。

执行命令为上述--execute命令，子进程退出码1。attempt.json记录started_at=2026-10-28T03:41:45.817951+00:00、ended_at=2026-10-28T03:42:46.275029+00:00、elapsed_ms=60457.0941；status/error_type均为ReadTimeout、failure_stage=wait_response_headers。response_headers_ms、response_body_ms和响应元信息均未知，usage未返回，不能填0或从旧结果推测。

输入保存文件hash为8729a7ff18eff3b7af6967a10411726fa12af433cf8e1b82dc6c3d25e988e912，与历史第5条一致；本次实际JSON传输内容另有wire_body_sha256，二者序列化不同，不能直接比较成同一个hash。

本次仅一次HTTP尝试，未收到有效HTTP响应。证明在已关闭自动重试的独立重放入口仍会发生等待响应头超时；旧SDK重复发送并不是该类首次超时的充分解释。仍不能确定供应商排队/处理、工具schema或上下文条件、中间网络中的哪一项是原因。不得根据约60秒等待直接断言模型推理过慢，也不能依据输出上限推断发生截断。

outcome.json绑定计划与attempt的hash，并核对计划绑定源及此前四份历史源文件未变。该计划已消耗，禁止再次原地执行。此前$0.104769是本次请求之前用户接受的历史估算，不包含此新增尝试；新增供应商费用未知，不因超时认定免费，也不刷新旧累计估算掩盖新增消耗。没有修改原cost.json。

本轮是实际模型请求失败，不是自主调查失败样本或机制实验；无新故障、Probe观测或服务启动。仅记录运行结果与文档，无生产逻辑变化，未重复234项离线回归或全量测试。下一步建议免费核对该请求强制结构化输出的schema和参数，再设计只改变一个因素的有限对照；不自动延长超时、增大输出上限或发送新请求。

## 用户授权的120秒单次对照

用户明确要求“延长时间，到120s试试”，本轮新增一次付费尝试，仍仅重放历史第5条输入。脚本prepare新增仅允许60/120的timeout_seconds，默认60；执行从hash绑定计划读取该值，禁止执行时临时覆盖。主项目全局超时、模型、256输出Token、消息、工具schema和JSON序列化不变。

新增回归验证120秒实际传入HTTPX各操作超时、输入字节不变、仅一次发送及非法超时拒绝；最终四文件88项通过，1条既有PyMilvus警告，记录runtime/replay-120s-tests-20261028.xml。没有重跑全仓或前端。

新目录runtime/rightapi-single-replay-120s-20261028-a保存plan.json、attempt.json和comparison.json。准备参数为--timeout-seconds 120，之后仅一次--execute。北京时间11:49:51.517至11:51:51.667，耗时120150.18ms，ReadTimeout，failure_stage=wait_response_headers。无HTTP状态、响应ID、finish_reason、usage；未重试、未执行工具、未启动服务或新故障。新计划已经消耗。

两轮wire_body_sha256均为b5409eeaf20694f8b1a8a534c05b4e64cc776d62df0faafae932a8d6a6b32e0d，确认请求JSON字节相同；运行时间和供应商内部路由不受本地控制，单次先后试验不能视为严格因果实验。comparison核对60秒轮次plan/attempt/outcome、历史账本及费用补充记录hash不变；本轮计划绑定源码与源文件核对通过。脚本因支持新超时有显式修改，不能要求旧计划的源码hash仍匹配当前代码。

结论：将网络操作超时从60秒延长至120秒，本轮仍未获得响应头，未解决问题。可能涉及供应商/模型处理、特定请求兼容性或中间链路；不能从客户端ReadTimeout证明GLM本身故障。停止追加调用，下一步免费核对请求条件，再决定是否设计简化schema/最小工具调用的单因素对照。不得未经授权继续放大超时或更换模型。

本次新增费用仍未知。用户此前认可的$0.104769历史估算不包含其后的60秒与120秒两次独立复验，不修改原账本或把未知usage填零。
