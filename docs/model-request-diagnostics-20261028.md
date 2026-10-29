# 模型请求诊断记录与受限复验方案（2026-10-28）

## 本轮结论

两个评测入口已共用 scripts/model_request_diagnostics.py，记录非流式HTTP尝试的响应元信息与实际可观察阶段。只用本地Mock和内存网络后端验证，没有访问供应商、启动服务或采集新现场。首次真实超时仍未定因，旧记录未保存的finish_reason无法补回。

## 调用链与字段

evaluate_windows_probe.py / evaluate_autonomous_investigation.py → 原有预算reserve → record_model_response → 原HTTPX transport → 原预算save。共享模块纳入选定源码快照，新增diagnostic_version=1，不重写继承账本或旧报告。

| 字段 | 含义与缺失口径 |
| --- | --- |
| response_metadata.request_id | 仅取x-request-id或request-id；缺失/不符合受限标识格式为null，不复制全部响应头 |
| response_metadata.completion_id | 响应JSON的id，经相同受限标识校验；未知为null |
| served_model | 实际返回model，经标识校验；不是请求模型的推测值 |
| response_metadata.choices | 每个有效choice的index、finish_reason、tool_call_count；没有choices为null；空数组保留为空 |
| finish_reason | 保留stop/length/tool_calls/function_call/content_filter，缺失或未识别值为null；不根据Token数猜测 |
| tool_call_count | tool_calls为数组时计数；message存在且未提供tool_calls时为0，结构无效为null；不复制名称、参数或结果 |
| usage | 仅保留非负整数Token字段及已知细分项；缺失/无效保持缺失，不填0；不复制任意供应商扩展字段 |
| response_headers_ms / response_body_ms | 从本次transport尝试起累计到收到响应头、读完正文的毫秒值；未完成部分为null，不是两个独立阶段的耗时 |
| started_at / ended_at / elapsed_ms | 带时区起止与本次尝试总耗时；取消和异常也记录 |
| error_type / failure_stage | 异常类名及最后实际观察阶段，不保存异常正文 |

阶段来自HTTPX/httpcore trace事件：connect、tls、send_request、wait_response_headers、read_response_body等；没有底层事件时用transport_unknown。正文已读完但JSON无效或顶层非对象时为response_parse，仍保留HTTP状态与已收到的请求ID。非200表示HTTP返回，status仍为returned；不意味着模型推理或整场诊断成功。日志不保存trace info，因为其中可能含请求头。

finish_reason=length说明供应商以长度限制结束，不能据此断言一定是哪个max_tokens参数或业务结论可用；Token数等于上限而结束原因未知时仍不能认定截断。阶段只定位到本机观察位置，不能区分供应商排队、内部推理与中间链路延迟。

## 费用缺失计数修正

原cost_summary对pricing_verified=false提前continue，导致此类请求缺usage时未计入usage_unknown_requests。现在分别计算用量未知与计价未知：未知模型超时同时计入两项，费用仍为null；不套用DeepSeek费率，不修改历史账本。此修正仅影响新计算的汇总，旧汇总产物保留原样。

## 验证

最终8文件301项通过，记录runtime/request-diagnostics-tests-20261028-c.xml，保留1条既有PyMilvus弃用警告；前轮168/179项属于重叠定向检查，不相加。本轮未跑全量后端、前端测试或浏览器，因为没有页面/API契约变更；此前1171项全量属于前一轮结果，不当本轮全量。

- stop/length/tool_calls及缺字段；同为256输出Token但finish_reason不同仍忠实记录，不按Token数推断。
- 非白名单响应头、回答正文、工具名称/参数、任意usage扩展和异常正文不进入新增诊断字段。
- 连接、TLS、写入、响应头读取、响应体读取、解析、取消及非200；异常只传播不自动重试。
- 实际HTTPX/httpcore协议代码配内存backend，分别超时于响应头/正文，不建立网络连接；阶段来自库真实trace。
- 实际ChatOpenAI/OpenAI SDK配MockTransport，工具调用响应可解析；SDK超时仍只有一次HTTP尝试，失败记录不升级为完成。
- Windows入口落盘、继承账本不变、失败报告与评分、记录审核和四组控制器回归通过；旧隔离评测入口共用该函数，其完整Docker/现场流程本轮未运行。

## 后续真实复验方案（尚未执行）

2026-10-28后续进展：用户接受将账户累计$0.104769归集为此前测试估算，不再追索逐请求账单；原费用与usage未知仍保留。已完成[单次历史请求复验准备](rightapi-single-replay-20261028.md)，以独立诊断尝试绑定旧记录，不取消正常调查续跑门槛；以下原始方案的账单追索要求据用户决定调整。本次单次复验仍未付费执行。

1. 先核对已发生超时请求的usage/供应商账单及计价，保留原累计记录；费用未知拦截不取消、不用新账本掩盖旧消耗。现有未知账本仍不能按正常续跑入口放行。
2. 确认一次有限请求的授权、请求数/输出上限和停止条件后再执行；新记录能力本身不授权调用，不自动重开故障或四组实验。
3. 首次复验固定模型、请求条件和60秒设置，先看可观察结果，不同时改变超时、上下文和提示词。若返回length，再单独讨论输出上限；若响应头阶段超时，保留输入指纹、阶段和耗时核对供应商，不能直接归因为上下文大。
4. 参数改变后的请求另记一行，不覆盖原失败；失败立即保留材料并停止，不通过自动重试积累费用。

用户本轮无需额外操作。下一入口为核对现有真实失败样本的记录缺口与复验条件，而非扩大毕设功能；AI完成工程记录不等于用户已掌握全部调用代码。
