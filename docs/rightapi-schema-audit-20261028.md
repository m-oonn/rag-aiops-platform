# 超时请求schema核对与最小对照（2026-10-28）

## 结论

**后续执行更新：用户确认后，最小schema对照已单次发送；北京时间2026-10-28 13:52:44—13:54:44，120.16秒后仍ReadTimeout，阶段wait_response_headers。未取得HTTP状态、响应ID、finish_reason或usage，无自动重试。下面关于尚未发送的描述为准备时状态，以本段及末尾执行结果为准。**

免费核对没有发现本地schema格式或SDK转换错误，尚不能确定供应商是否完整兼容该请求。不能因为复杂请求超时，就声称GLM不支持工具调用或256输出Token必然不足。已准备只缩减工具参数schema的单次对照，尚未发送；正式Agent、结论门槛和主项目配置未改。

当前仍在阶段E前置排障，未进入四组效果实验。

## 实际调用链与证据

InvestigationStrategy.decide → ainvoke_structured → ChatOpenAI.with_structured_output(InvestigationDecision, method=function_calling) → OpenAI兼容chat/completions。超时不是格式异常，当前structured模块直接抛出，不触发普通JSON格式降级；格式错误与网络重试是两条不同路径。

- 历史第1条成功请求已强制选择Plan工具，parallel_tool_calls=false；第2至4条成功使用普通工具目录。供应商并非所有工具/强制选择请求都失败。
- 第5条强制选择InvestigationDecision、parallel_tool_calls=false、未声明strict。JSON传输内容35729字节，消息内容16357字符，仅一条system消息。这些是字符/字节统计，不是实际Token数，也不能证明超出上下文或单system消息无效。
- 原参数schema为3810字节、18个顶层字段，含嵌套对象/数组/anyOf/默认值；必填仅hypothesis。已安装jsonschema的Draft202012Validator本地检查通过，最小hypothesis对象可通过schema及Pydantic解析。
- 当前convert_to_openai_tool输出与历史第5条工具定义完全一致。实际LangChain/OpenAI SDK配MockTransport生成同形式的强制选择请求，并成功解析构造的合法InvestigationDecision调用。此项只证明本地链路，不证明供应商兼容。
- 256输出Token限制可能影响完整业务结果，但本地schema允许短对象；旧成功响应没有finish_reason，两次超时也没有usage/choices，不能认定截断或输出限制就是原因。
- 原Agent工厂使用User-Agent=Python-urllib/3.13，独立HTTPX重放使用HTTPX默认值；原SDK的其他协议头也不保证相同。60/120秒两次独立重放的JSON传输内容一致，但不等于与旧Agent的全部HTTP报文相同。User-Agent是否影响本供应商没有验证；不将旧工厂有关其他供应商的历史注释当作RightAPI故障结论。

机器核对结果：runtime/rightapi-minimal-schema-20261028-a/schema-audit.json。未复制提示词到文档，所有历史原件保留。

## 已准备的最小对照

复用专用replay入口，新增schema_variant=original/hypothesis_only，默认保持原样。仅hypothesis_only诊断变体把tools[0].function.parameters替换为一个必填hypothesis字符串；工具名、强制选择、完整历史提示词、模型、256输出上限、非流式、temperature、parallel_tool_calls、HTTPX请求头形式及120秒超时均保持与上次独立重放一致。schema从3810降为96字节，整体JSON传输内容从35729降为32015字节；本地逐字段恢复比较确认只改变该路径。

这不是正常调查可用的schema，也不是诊断修复。历史提示词仍要求完整调查字段，有意固定该提示词会造成业务要求与缩减schema不完全匹配，因此只能用于观察供应商是否返回，不能判断诊断语义正确。即使成功也只是与schema差异相关的线索，时间与供应商路由等非确定因素仍未控制。若仍超时，不能排除提示词、强制选择、协议头或服务链路问题；不自动接着改多项重试。

已用私有profile运行免费准备，产物plan.json、plan.sha256、request.json位于runtime/rightapi-minimal-schema-20261028-a；model_calls=0且无attempt.json。request.json仅派生自已保存的脱敏历史输入，仍含内部调查内容，应按原runtime范围本机保留。派生文件hash和内容必须与原输入按指定变换一致，否则执行前拒绝。

后续明确授权单次付费对照后可使用：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py -- scripts/replay_model_request.py --execute --plan runtime/rightapi-minimal-schema-20261028-a/plan.json
```

只允许一次HTTP尝试、无重试/重定向、不执行工具、不启动服务或故障。记录HTTP状态、finish_reason、工具数、usage及超时阶段，不保存回答正文。没有回答参数语义的完整验收，HTTP200不得当业务成功。价格未知，不能把历史$0.104769估算作为新调用费用。

## 验证与变更范围

最终6文件105项通过，记录runtime/schema-control-tests-20261028-b.xml，保留1条既有PyMilvus弃用警告；首轮90项包含在最终结果中，不相加。新增最小schema反例先有2项因缺参数失败，完成实现后通过。覆盖只改参数路径、输入/派生文件hash、未知变体拦截、一次请求、SDK生成/解析及原结构化降级/重试规则。

源码改动仅scripts/replay_model_request.py及其测试，未改生产LangGraph/Agent提示词/正式schema或全局超时；更新说明和AGENTS。原账本及两次独立失败记录hash已绑定并核对保留。本轮无新模型/embedding/重排/现场/服务操作，未运行全仓、前端或浏览器，不宣称供应商故障已经定位。

## 最小schema单次真实执行结果

准备与执行分轮进行：本节为用户后续明确确认后实际调用。执行上述--execute命令，子进程退出1；attempt.json记录started_at=2026-10-28T05:52:44.764027+00:00、ended_at=2026-10-28T05:54:44.925589+00:00、elapsed_ms=120161.5757、ReadTimeout/wait_response_headers。没有收到HTTP状态或响应元信息，usage未知、费用未知，不能按零填入。仅一次HTTP尝试，没有执行模型工具、启动服务或采集新现场。

此前原schema120秒轮次耗时120150.18ms；本次hypothesis_only为120161.58ms。两次均在读取响应头时失败。缩减schema没有在本次消除超时，但并不证明schema完全无关；时间、路由等未控制，不能从两次失败归因于GLM本身。仍保留原提示词、强制tool_choice和HTTPX协议头等未验证因素。

实际输入派生文件hash为d452fc3938cdedd8946c6c9831143329d6c05f33c79565dd3fe3c2381166cdc8，wire_body_sha256为2ab11bd0423fd8f8e0ad60b27edefd6a039aad25a407f8ada579cb2e66bc7daf。outcome.json绑定计划及请求结果hash，核对所有绑定源、旧账本和两轮原schema失败记录未变；该计划已经消耗，不能原地再次发送。

用户认可的$0.104769历史估算之后，已有三条独立诊断尝试（原schema60秒、原schema120秒、最小schema120秒），新增费用均未知、未合并入该历史金额。本轮未修改生产逻辑或重复离线测试，前轮105项不作为本轮新增结果。

停止追加模型调用。建议下一步免费核对原Agent与独立HTTPX的允许请求头及代理路径差异，再准备一个仅改变User-Agent的候选对照；不使用其他供应商的历史经验代替RightAPI实测，不把当前结果当自主诊断或创新效果。
