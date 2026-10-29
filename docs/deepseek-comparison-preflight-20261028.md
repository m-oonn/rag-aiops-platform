# DeepSeek对照凭据核对（2026-10-28）

用户明确要求尝试之前的DeepSeek，授权一次受限对照，不是把日常模型切回DeepSeek或启动四组实验。已有记录的旧供应商为https://api.deepseek.com，模型为deepseek-v4-flash。拟沿用单次请求、120秒、256输出Token与上一轮最小schema/UA，另记供应商要求的参数；模型和供应商同时变化，不能据结果单独归因GLM本身。

只检查当前.env、进程环境、项目根目录配置候选及2026-10-23归档local-config-backups两份.env备份的必要字段存在性，未发现可用DeepSeek官方凭据。没有输出、复制或归档密钥，也没有使用RightAPI密钥尝试DeepSeek。当前实际模型请求数为0；preflight记录在runtime/deepseek-comparison-preflight-20261028-a/preflight.json。

需要用户将旧DeepSeek密钥保存到本机根目录.env.deepseek-test，字段为DEEPSEEK_API_KEY。已用git check-ignore确认该文件名被忽略，不要将密钥贴入对话。先前commentary建议写入.env.agent-test已及时更正：该启动器字段白名单不接受DEEPSEEK_API_KEY，因此不能污染现有GLM profile。未创建空凭据文件或修改现有配置。

收到补齐通知后先验证专用profile、单次请求限制与供应商参数，再按已有一次对照授权执行；不要求重复费用授权。若旧凭据无法找回，不能冒用现有密钥、创建新账号或将RightAPI上同名模型假称为旧官方通道。当前是缺少运行必需配置，未执行真实对照，既有超时/502根因仍未定。

## 凭据补齐后的实际单次对照

用户随后提供凭据，已仅保存到Git忽略的本机`.env.deepseek-test`，未改日常`.env`或GLM实验profile。上文缺凭据是当时的历史状态，现已解除；旧preflight不回写。

本次产物为`runtime/deepseek-single-comparison-20261028-a/`中的`run.py`、`plan.json`、`request.json`、`attempt.json`与`outcome.json`。脚本复用`scripts/model_request_diagnostics.py`，只对`https://api.deepseek.com/chat/completions`发送一次；120秒HTTP操作超时、256输出Token、禁用重试和重定向，不执行返回工具。独占创建attempt防重复发送。密钥不写入计划、请求JSON、响应记录或报告；不保存响应正文。运行脚本及产物留本机runtime，不新增生产框架或更改生产代码。

输入沿用`runtime/rightapi-agent-ua-20261028-b/request.json`，消息、最小hypothesis schema、强制工具选择、并行工具参数、temperature、非流式设置及输出上限均保留。UA保持`Python-urllib/3.13`。仅改变供应商端点、model为`deepseek-v4-flash`，并按旧工厂配置添加`thinking.type=disabled`，所以不是只改变模型的单因素实验。此前GLM输入属于历史现场请求，不能当成新现场调查。

北京时间2026-10-28 14:41:53.928—14:41:54.839，单次实际请求结果：

| 项目 | 实际记录 |
| --- | --- |
| HTTP状态 | 200 |
| 请求总耗时 | 910.42ms |
| 收到响应头 | 147.77ms |
| 请求模型 / 响应自报模型 | deepseek-v4-flash / deepseek-flash |
| finish_reason | tool_calls |
| 工具数量 | 1 |
| 最小参数核对 | InvestigationDecision、参数JSON对象、hypothesis为字符串，通过 |
| 输入 / 输出 / 合计Token | 6402 / 96 / 6498 |
| 可见缓存Token | 0 |
| 费用 | 未取得实际金额、未核实当前费率，保持未知 |

最小参数核对不等于原始18字段schema、Pydantic完整决策或诊断语义正确性验收。响应自报模型与请求模型不同，尚未核实供应商别名映射，不能据此确认内部实际版本。未运行Agent闭环、工具、专用故障业务、浏览器或四组实验，未启动或重启任何服务。

离线自检覆盖成功、超时、HTTP401和无效JSON四类返回；每类检查实际只调用一次、已消耗目录拒绝重复发送、秘密与错误正文不落盘，全部通过，网络调用0。真实对照另计1次。共享诊断器与原RightAPI重放入口两文件回归50项通过，保留一条既有PyMilvus弃用警告，记录为同目录regression.xml；未重复全量或前端测试。来源hash检查通过：前次GLM请求/结果/计划、历史账本、费用归集补充、运行脚本和共享诊断器保持不变。专用凭据在新产物和本报告中的泄露检查通过。旧费用账本未重置；此前$0.104769历史估算不包含后续五次RightAPI诊断或本次DeepSeek诊断，本次新增费用未知。

结论：本次较长历史输入在DeepSeek官方通道能快速获得可解析的最小工具返回，说明当前客户端和这份消息可以在另一模型/供应商组合下完成请求；结合此前RightAPI长等待超时和一次502，排查重点应转向RightAPI/GLM组合的上游处理、工具兼容或转发链路。不能单独区分GLM模型服务、RightAPI转发、供应商参数兼容、不同目的地网络或时段变化，也不能认定原完整schema必然可用。日常GLM配置保持原样。下一步先免费把完整schema与SDK解析接到Mock响应，若需要再用DeepSeek进行完整schema单请求或真实单场G11，须限定下一次范围，不把本次成功扩成无限调用授权。
