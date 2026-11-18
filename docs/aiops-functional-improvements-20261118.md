# AIOps 功能连续性改进记录

日期：2026-11-18。目标：完成 50 项有独立根因、影响功能流程或操作连续性的改进后停止。

**代码完成 44/50**。实际验收：后端定向回归 150 passed；直接执行纯 JavaScript 9 passed。Vue 页面和浏览器操作均为「代码已修改，待运行验收」，不算端到端通过。剩余差额 6 项，继续按代码与反例核查。

承接 `project-workflow-fixes-20261117.md`、`continuous-monitor.md`、`frontend-aiops-workspace-20261113.md`。已有未提交修改是基线，不计作本轮成果，不改写历史模型失败。全程未运行构建或编译命令；Python 使用 `-B --assert=plain`，不写字节码或转换断言；JavaScript 由 Node 直接执行。无真实模型调用、无生产数据修改、无提交推送。

## 范围与验收

从 `/aiops`、`/aiops/history` 入口追踪到请求、SSE、运行/审批/证据/步骤/工具账本/经验 API、持久化、重新读取及持续监察。反例包括空输入、损坏历史、重复提交、异步乱序、断流、读取失败、刷新、身份变化和旧样本。

以下按独立状态或数据合同的根因计数。同一根因的多个现象合并；仅发现、补测试或补文档不计数。表中的“页面待验”完整含义是 **代码已修改，待运行验收**。

## 已完成项

代码路径均相对工作区根目录。

| # | 问题与复现条件 | 代码依据、根因 | 修改 | 验证结果 |
|---|---|---|---|---|
| 01 | 服务端合法的点号运行编号打不开，过长/带路径的 session 生成不可读编号 | `frontend/src/lib/history.js:validRunId` 与 `src/api/routers/aiops.py:AIOpsRequest` 的入口合同不一致 | 统一运行编号 1–64 字符；session 约束与 graph 截取前缀兼容 | Python 输入用例、JS 编号边界通过；页面待验 |
| 02 | 本机历史夹一条 null 后所有记录消失，重复行出现 | `history.js:getHistory` 对损坏行直接取字段 | 按行验证并按运行编号去重，保留完整行 | JS 损坏历史用例通过 |
| 03 | 只读历史刷新也改变“最近更新” | `history.js:rememberRun` 每次写当前时间 | 优先服务端时间，缺失时保留已有时间 | JS 服务端时间用例通过 |
| 04 | 启用终端时连续提交可弹多次确认并启动多场 | `Diagnosis.vue:start` 在 await 确认前未上锁 | 确认前设置 startBusy，确认返回核对当前页面版本 | 页面待验 |
| 05 | 恢复运行/等待审批后轮询停止，暂时断网后不再获取最终结果 | `Diagnosis.vue:scheduleRefresh/refreshRunDetails` 缺少未终结状态及失败后的调度 | 统一未终结状态，finally 调度；明确权限/不存在错误停止 | 已补轮询反例；页面待验 |
| 06 | 初次读取运行失败后重试按钮仍指向空或旧编号 | `Diagnosis.vue:restore` 成功后才保存当前目标 | 读取前固定 threadId/loading，失败保留可重试目标 | 已补读取失败重试用例；页面待验 |
| 07 | 服务端清空报告或结构化结论后，页面仍显示旧草稿 | `Diagnosis.vue` 多处用 truthy 合并结果 | 复用 applyRun，空字符串/null 成为权威结果 | 已补空结果反例；页面待验 |
| 08 | 运行进入/离开终端待审批时，页面与重新读取保留旧审批 | `Diagnosis.vue:applyRun` 及 `run_store.py:_update_run` 的审批投影未随状态同步 | 轮询载入审批及安全入口，离开 pending_terminal 清除旧审批；API 仅该状态返回审批 | 后端清审批用例通过；页面待验 |
| 09 | 断流被当作失败/取消后台，用户容易重复发起 | `Diagnosis.vue:start/stopReading` 混淆订阅与运行生命周期 | 有编号的断流进入 disconnected 并重新读取；停止读取说明后台可继续 | 已补连接行为用例；页面待验 |
| 10 | 重复收到同一 SSE 证据造成台账重复 | `Diagnosis.vue:onEvent` 无条件 push | 按 evidence_id 合并，避免重复记录 | 页面待验 |
| 11 | 完成后尾随 usage 事件把本机历史写回 running | `Diagnosis.vue:onEvent` 收到编号即写 running | 按当前真实状态保存 | 已补完成后 usage 用例；页面待验 |
| 12 | 同一运行较早的审计请求覆盖较新台账 | `Diagnosis.vue:loadEvidence` 仅核对运行，未核对请求代次 | auditVersion 加运行版本共同校验 | 已补乱序反例；页面待验 |
| 13 | 原文弹窗关掉重开后旧响应回填，关闭后仍缓存原文 | `Diagnosis.vue:viewEvidence` 的异步响应生命周期不完整 | evidenceVersion、运行与角色校验；关闭清原文和详情 | 页面待验 |
| 14 | 离开再返回丢失尚未提交的故障描述和终端选择 | `Diagnosis.vue` 仅组件内状态 | 按用户保存 sessionStorage 草稿，存储不可用保持表单可用 | JS 草稿隔离/存储异常通过；页面待验 |
| 15 | 新浏览器读取运行只剩结论，原始输入为空 | `aiops.py:get_run_status` 没返回 query，页面仅依赖本机索引 | API 返回 query，页面优先恢复原始输入 | Python 重新读取通过；页面待验 |
| 16 | 刷新历史/切换账号后晚到响应写入新列表 | `DiagnosisHistory.vue:load` 缺少读取代次和身份绑定 | 使用 version 与 userId 绑定读取，卸载失效 | 页面待验 |
| 17 | 历史读取中移除某行后，其他结果按旧数组下标串行 | `DiagnosisHistory.vue:load` 把数组位置当运行身份 | 按 thread_id 定位仍存在的行后合并 | 页面待验 |
| 18 | 历史详情读取失败仍显示本机缓存为最新状态 | `DiagnosisHistory.vue` 隐藏逐行错误 | 明示“状态未核实”；成功写回服务端结果 | 页面待验 |
| 19 | 浏览器禁止写存储时，移除看似成功但刷新又出现 | `DiagnosisHistory.vue:remove` 未等待本机保存成功 | 持久化成功再移除行，失败保留并提示重试 | JS 正常移除通过；失败页面待验 |
| 20 | 经验读取重试或发布失败丢失审核意见/库选择 | `ExperienceCandidate.vue:load` 把重试和切换目标都当初始化 | 仅切换运行/身份清表单；重试和操作失败保留 | 页面待验 |
| 21 | 经验库读取失败被显示成没有可用库，流程无出口 | `ExperienceCandidate.vue` 没有独立的库错误状态 | 单列库错误、重试与打开知识库入口 | 页面待验 |
| 22 | 每次轮询产生等值引用数组都会关掉知识原文弹窗 | `KnowledgeReferences.vue` 监听数组引用 | 按序列化内容变化处理切换 | 页面待验 |
| 23 | 知识原文读取一次失败后只能关闭重开 | `KnowledgeReferences.vue` 错误状态缺下一步 | 提供同条原文重试入口 | 页面待验 |
| 24 | 点击不存在的证据引用却展示第一条无关证据 | `DiagnosisWorkspace.vue:selectedRecord` 无条件回退首条 | 有指定 ID 时保留缺失状态并明确提示 | 页面待验 |
| 25 | 只有草稿/失败报告、无结构化结论时标成已完成 | `DiagnosisWorkspace.vue:conclusionLabel` 默认文案错误 | 依据运行状态展示草稿、失败、断流与等待 | 页面待验 |
| 26 | 空白或超长请求仍能启动诊断 | `aiops.py:AIOpsRequest` 缺边界验证 | 去首尾空白，拒绝全空白及超过 12000 字符 | Python 输入反例通过 |
| 27 | 关闭各开关的普通诊断完成后刷新404 | `aiops.py:diagnose_stream` 未强制运行持久化 | 正式入口显式 persist_run=True | Python 假流调用合同通过；无真实模型 |
| 28 | 数据库不可用被当作运行/审计不存在，诱导重发 | `run_store.py:get_run` 吞异常返回 None | 抛 RunReadError，API 对运行/审计/证据读取故障返回503 | Python 数据库断开反例通过 |
| 29 | checkpoint 读取失败使已经持久化的报告也读不到 | `aiops.py:get_run_status` 把可选详情和持久结果绑死 | 返回持久状态/报告，details_status 明确 unavailable | Python checkpoint 异常通过；页面待验 |
| 30 | 关键状态写库失败仍继续宣称待审/完成 | `run_store.py` 关键标记调用 best-effort 更新 | 审批/完成/失败关键转换 required=True，写失败传播 | Python 写故障反例通过 |
| 31 | 未来采集时间的证据被当作新鲜结果 | `run_store.py` 仅检查 fresh_until | 列表与详情共用采集时间上界及有效期判断 | Python 未来证据反例通过 |
| 32 | UI 原文绕过工具的路径/完整性边界；统一后脱敏文件又被误拒 | `run_store.py:get_evidence` 直接读文件；脱敏内容与原始 raw_hash 不同 | 与模型共用安全读取；保留原始哈希，新增 nullable stored_hash 校验脱敏落盘对象；旧记录保持原校验 | 原文篡改/正常脱敏/API 与模型所有权回归通过；旧脱敏且无存储哈希记录不冒充通过 |
| 33 | SQLite naive 时间被浏览器按本地时间解释 | 运行、步骤及监察 API 直接 isoformat | 统一通过 UTC 归一化输出时区 | Python 运行/监察时间反例通过 |
| 34 | A→B→A 的旧样本再次计数，可能误开事故 | `continuous_monitor.py:record_observation` 只比紧邻签名 | 按 series 保存高水位，重复/回退采样不推进连续次数 | 修前失败，修后 Python 通过 |
| 35 | 同一 series 的矛盾重复值可参与健康判断 | `classify_up_samples` 没有 series 唯一性检查 | 同值同时间去重；矛盾记录标 unknown | 两个反例修前失败，修后通过，合计一项 |
| 36 | 排队自动诊断等到信号恢复后仍启动模型 | `_diagnose_incident` 获得 semaphore 后只看 pending | 再核对 incident=open；已恢复记 skipped | 假服务0调用用例修前失败、修后通过 |
| 37 | 自动诊断取消被标 failed，关联运行可能继续显示 running | `_diagnose_incident` 未处理 CancelledError | 明确 interrupted 并重新抛取消；同事务结束关联系统 running 记录 | 取消反例修前失败、修后通过 |
| 38 | 监察重启只改事故，关联运行仍一直轮询 | `_reset_after_restart` 未同步运行投影 | 在 leader 重置中仅同步事故关联的系统 running 记录；保留无关运行 | 关联/无关双运行反例修前失败、修后通过 |
| 39 | 一个服务的查询异常丢失全部服务当轮采样 | `run_continuous_watch` gather 整体抛错 | 各服务采集异常单独转 unknown，其他继续记录 | 双服务反例修前失败、修后通过 |
| 40 | 监察已停/样本过期，服务页仍显示持久 healthy | `monitor.py:get_watch_services` 直接暴露旧状态 | 根据启用、采样和观测时间投影 stale/unknown，保留活动事故 | 过期健康反例修前失败、修后通过 |
| 41 | 缺少日志时间却显示1970年时钟 | `diagnosisVisuals.js:clockTime` 把 null 交给 Date | 缺值显示“—” | JS 反例修前失败、修后通过 |
| 42 | JSON 日志只有 message 时正文空白 | `diagnosisVisuals.js:logEvents` 只拼固定诊断字段 | 保留 message/msg 与其他观测字段 | JS 反例修前失败、修后通过 |
| 43 | 历史台账夹 null 导致整份报告无法展示 | `diagnosisVisuals.js:evidenceRows` 直接取属性 | 忽略损坏条目，保留其余证据 | JS 反例修前失败、修后通过 |
| 44 | 相同建议合并后丢失安全条件，不同对象被混成一个操作，null建议崩溃 | `diagnosisVisuals.js:reportActions` 只按文案合证据 | 按文案与 scope 合并，并保留全部前提、风险和验证步骤，跳过空项 | JS 三个反例修前失败、修后通过，合计一项 |

## 实际验收结果

证据目录：`runtime/aiops-improvements-20261118/`。

- `backend-red.log`：首批14个反例在修改前失败；随后调整了参数化标识和 session 129字符边界，保留原失败。
- `backend-check-01.log`：45 passed / 1 failed。失败是本轮统一读取后暴露的脱敏哈希不匹配，新增独立 stored_hash 后修复。
- `watch-red.log`：初次8 failed，其中3例夹具遗漏 opened_at，不能当产品证据；补夹具后 `watch-red-corrected.log` 8 failed，均为预期业务断言。
- `backend-check-02.log`：11个定向文件，150 passed / 4条既有 PyMilvus 弃用警告。不和其他批次相加。
- `js-red.log`：3 passed / 6 failed；`js-check-01.log`：9 passed。通过 `D:\Node\node.exe scripts\verify_aiops_continuity.mjs` 直接执行。
- Vue 组件测试已补用例但未运行；用户禁止编译，因此未运行 Vite、Vue SFC 转换、前端 build 或浏览器现场验收。

## 已核查范围与未完成

已读最新 Markdown 记录，追踪诊断页面、历史、本机索引、工作空间、证据原文、知识引用、工具账本、经验候选、API、run_store、evidence_reader、监察及其采样适配。继续核对工作空间刷新/返回、知识片段定位、异常状态恢复；当前差额6项。

此前真实模型 normal 场次和 DSH 新鲜现场验收仍未完成。本轮不续用历史模型授权，不声称诊断正确率、机制收益或现场端到端已通过。新增 stored_hash 通过项目既有启动迁移补列；本轮未对生产库运行迁移，旧脱敏且没有可验证存储哈希的原文保留完整性失败。
