# 阿里云 DeepSeek 通道切换

2026-11-03 起，真实 Agent 测试固定使用阿里云兼容接口的 `deepseek-v4.1-flash-1017`。旧 GLM 配置已从默认设置、前端备用模型和测试 profile 中移除；历史账本和历史运行材料保留，不回写。

阿里云接口为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型调用关闭思考参数。模型目录与脱敏快照见 `runtime/aliyun-model-catalog-20261103/`。本模型按官方北京忙时输入 2 元、输出 8 元/百万 token 做预算预留，供应商最终账单仍未核对。

官方 DeepSeek 兜底使用本机 `.env` 中单独配置的 `LLM_FALLBACK_API_KEY`，指向 `https://api.deepseek.com`；`.env.deepseek-agent-test` 仍是独立的官方通道 profile。默认运行链路先使用阿里云；Agent 和普通 RAG 生成入口仅在连接、超时、限流或 5xx 瞬态错误时自动切换到官方 DeepSeek，鉴权和参数错误直接暴露。单次测试成功走阿里云时不会混入官方模型结果。

本轮授权从旧 428 条账本、14.453038 元峰值预留继承，累计上限 24.453038 元，单场上限 5 元，不设请求数上限。正常场新增 7 次请求均 HTTP 200 且 usage 完整，配置错误场首轮审计失败材料保留，修复审计后真实重测新增 9 次请求均 HTTP 200 且 usage 完整，新增峰值 0.254538 元；下游不可达场新增 10 次、峰值 0.328278 元。至此账本544条、17.363292元峰值预留，按累计授权上限估算余量7.089746元，历史61条未知价格记录保留。

2026-11-03 后续配置错误场复测继承544条账本，新增6次请求，全部由阿里云 `deepseek-v4.1-flash-1017` 处理，HTTP 200 且 usage 完整；官方 DeepSeek 兜底未触发。新增峰值预留0.121332元，账本更新为550条、17.484624元，累计授权余量6.968414元。Agent结果为 `localized_fault`：入口503、下游200、独立配置快照为 `max_attempts=invalid`，配置来源SHA-256与应用ValueError日志一致。workflow、结果层、机械审查、机制行为审计及恢复清理通过；`capability_passed=false`，语义审核pending。报告指出模型未提出下一检查，系统未独立验证检查覆盖。

事后只读检查测试生成器 `scripts/verify_windows_local_faults.py` 确认：`application_config_error` 场景由控制器将 `max_attempts` 写为字符串 `invalid`；应用处理器将其转成整数时抛出 `ValueError`，捕获后返回503。回到有效整数配置的现场恢复场通过；定向 `tests/test_windows_local_faults.py` 为116 passed。此控制器/代码核验确认了本次测试注入故障的直接技术原因，但不是Agent当场证据，不回填原报告、评分或人工审核。配置变更者超出这次“故障由测试控制器注入”的已知测试事实，不能据当前主机日志归因。无需修改Windows审计策略来解释本次构造故障；只有未来测试若要验证外部配置作者，才需要故障前配置审计。

完整产物位于 `runtime/windows-local-faults-526b7c5e651b4bc899b1bf4f0d8e5518/model-4564e0f9b9f548f18f88dfed7ce979a2/`。本次新增后仍须继承550条账本，不回退或清零。

运行后的只读复核精确覆盖本场本地时间13:11:30–13:14:30：Security仅4条登录/凭据类事件，没有4688/4689进程或4656/4663/4660/4657文件事件；Application与PowerShell无事件，Sysmon Operational不存在。Process Creation、Process Termination、File System当前策略均为`No Auditing`。该复核不是Agent现场证据，未回填报告。此历史记录无法补救；若要归因后续配置变更，必须在故障产生前启用并核验可用审计来源。

正常场报告为 `healthy_within_scope`，入口与下游均 HTTP 200；配置错误场和下游不可达场均完成工作流并报告 `localized_fault`。配置错误场取得 `max_attempts=invalid`、入口 503、下游 200、进程和端口正常；下游场取得入口 503、下游 TCP 拒绝、指定端口无监听和配置进程未发现。配置错误场第一轮审计失败原件保留；审计修复后的新真实场通过工作流、结果层、机械、行为及清理检查，独立配置快照与错误日志的来源哈希一致。三场人工语义审核仍为 pending，不能据此确认完整根因或四组机制效果。官方 DeepSeek 兜底未触发，本轮真实结果只来自阿里云 `deepseek-v4.1-flash-1017`。

工程修复包括：正常夹具使用合法 JSON 配置；后续检查的缺失参数、未配置事件通道和伪造工具名会反馈模型纠正一次；候选预期值变更保持原子拒绝；机制审计校验所有具体计划查询。相关回归已通过，后端全量曾通过 1694 项（99 integration deselected，保留既有 PyMilvus 警告）。

真实结果仍有限：`localized_fault` 只表示故障层已定位，不能确认配置修改者、启动/退出历史或完整因果；三场均需人工语义审核，未放行正式四组实验。机制审计已修复独立配置/依赖补查优先时的误报，回归覆盖该策略抢占反证改向的情形。GLM 不在当前默认配置、前端模型列表或阿里云测试 profile 中；只有阿里云瞬态连接、超时、限流或 5xx 故障时才允许官方 DeepSeek `deepseek-v4-flash` 兜底，鉴权和参数错误直接失败。
