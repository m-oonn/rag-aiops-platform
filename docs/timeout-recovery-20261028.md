# 模型瞬态失败收束（2026-10-28）

后续免费请求诊断记录已补齐，见 [模型请求诊断记录与受限复验方案](model-request-diagnostics-20261028.md)。该项不解决首次超时定因，也未恢复真实调用。

## 触发问题

2026-10-28 的 RightAPI `glm-5.3-flash` 单场冒烟中，控制器核对了入口503和下游不可达；Agent实际调用inventory、历史列表、service、process和text_log，没有自主调用入口或下游dependency_probe。随后调查策略在重规划阶段连续遇到 `APITimeoutError`。原实现让异常直接冒泡到图层，只产生 `error` 事件，`report.txt` 为空，已有证据不能形成可审核的“未定位”报告。

## 修复边界

`src/agent/aiops/strategies/investigation.py` 现在在调查决策节点收束瞬态模型错误：超时、连接错误以及明确的 429/5xx 由策略返回 `plan=[]`、`diagnosis.kind=unlocated` 和诚实的未完成报告；报告保留已通过校验的现场证据，并说明需要重新发起调查。不会填写根因、不会把模型错误当作现场事实，也不会把参数错误、鉴权错误或其他编程异常吞掉。

## 验证

- 策略、评测记录和相关 Probe/事件流程：243 项通过。
- 全量离线后端：1156 项通过，99 项 integration 按默认配置排除。
- 仅保留既有 PyMilvus 弃用警告。
- 未启动服务、未调用模型、未修改既有费用账本。

## 限制

本修复只保证模型瞬态失败时系统能留下可解释的未定位结果，不降低成功诊断的证据门槛，也不证明 RightAPI 的延迟、稳定性或价格。下一次真实调用前，仍需评估请求上下文增长和 60 秒超时设置。

## 后续原因核对与最小修正

用户要求先明确现象、梳理原因。重新读取原始产物后，将三个问题分开记录：

1. **首次超时原因未定。** 第5次请求在等待HTTP响应头时触发约60秒的读取超时，不是本地JSON解析超时。请求体保存文件约35KB，包含一条system消息及InvestigationDecision工具schema；这不能证明超出上下文窗口，也不能证明大小导致超时。供应商排队、网络、请求格式/强制工具调用等仍未区分。`input_token_upper` 是预留算法用的UTF-8字节数加8192，不是供应商实际输入Token。
2. **重复发送原因已确认。** 第5、6、7条输入hash相同。修改`llm.max_retries=0`不会更新已经创建的OpenAI SDK client，原`root_async_client.max_retries`仍为2。用已安装ChatOpenAI/OpenAI SDK和本地MockTransport对照，旧配置产生3次尝试（重试头0/1/2），同步底层配置后仅1次。两轮均无外部模型请求。两个评测入口已同步设置底层异步/同步client的max_retries为0，未调整常规模型工厂或超时时长。
3. **空报告原因已确认，但完整修复未验。** 旧策略超时冒泡到graph，生成error事件而无complete报告。前述策略补丁仅有策略级反例与相关回归支持；尚未专项验证超时经正式graph/SSE/刷新、运行状态与评分后仍保持“调查未完成”。不能仅凭unlocated报告存在就算流程完成，该状态边界仍待处理。

同时纠正现场口径：Agent trace只有inventory、历史列表、service、process和text_log，未主动调用入口或下游dependency_probe；控制器探测不能算作Agent自主选查。第4次输出usage恰为256Token，但未保存finish_reason，不能确定是否截断。原失败样本不回写。

最终相关评测三文件146项通过（含真实SDK单次超时回归），1条既有PyMilvus警告；不与前轮168项或全量1156项相加。本轮未重新运行全量、未调用真实模型、未操作服务。一次新增测试缩进错误已修正；另修正位于return之后、原本未执行的单次请求断言。

## 失败状态完整接线与离线验收

后续已补齐上述第3项缺口，范围为 InvestigationStrategy 决策阶段的瞬态请求错误及结构化输出失败：

- state 新增可选 investigation_failure，与诊断 kind 分离；正常调查后的 unlocated 仍可完成，模型失败提前停止不能完成。错误标记只包含受控原因、代码及异常类名，不包含供应商异常正文。
- graph 的 execute/resume 共用失败收尾，保存 failed 和已有证据报告，发 report 后发 investigation_failed 错误事件，不发 complete；人工审批开启也直接失败结束，不把失败报告送审。
- SQLite checkpoint 重开、拥有者刷新、证据账本保持一致。页面实时及重挂载后展示失败说明和报告，保存 thread_id；普通用户证据响应继续剔除原文，跨用户读取仍404。
- Windows 评测保留失败 report.txt、diagnosis 和失败标记，分别记录 has_final_report、workflow_completed；EvaluationRecord 保持 incomplete。机械评分及记录审核拒绝失败标记，即使错误材料同时带 complete。旧自主评测入口同步为失败即停，避免预设 completed。

先新增反例确认4个失败分支原本被完成/送审，再修复。新正式API/SSE测试覆盖首次执行失败和人工驳回后resume失败，真实执行器消费构造工具结果，全部为本地Mock，未调用模型或采集新现场。权限测试最初错将脱敏单条证据接口预期为403，核实路由后改验200且不含原文，生产权限规则未改。

最终后端默认离线全量1171项通过、99项integration排除、1条既有PyMilvus弃用警告，记录 runtime/failure-contract-full-20261028.xml；前端18文件110项通过，独立目录 runtime/failure-contract-build-20261028 构建通过。此前155项定向及20项前端定向已包含在全量中，不相加。

本轮未验真实浏览器、未启动或重启服务、未新增付费调用、未重写历史报告/费用账本、不提交推送。原首次超时仍未定因；没有调整60秒超时、上下文或提示词，也不以离线通过声明自主效果。planner/executor其他异常仍沿用既有通用错误路径，不宣称所有阶段都已具备此报告收束。下一入口为免费补齐真实请求/响应finish_reason等脱敏记录，支持后续定位首次超时和输出是否截断；不自动重跑真实模型。
