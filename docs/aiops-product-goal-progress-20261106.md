# 真实前端诊断链路验收（2026-11-06）

当前目标已由用户暂停：022 endpoint、033 stopped 产品链路通过，034 normal 未通过；endpoint 尚未在最终代码上再次验证。只有模型形成有证据的直接原因、系统完整报告保存并在前端展示，刷新及后端重启读取不增加调用，才算对应故障场景通过。环境 ready 或流程 completed 不代表根因通过。

暂停前用户授权持续按轮修复与真实测试；每轮最多5元，历史累计不占新轮额度。同一轮重启固定原历史基线、续用账本，不重置额度。历史710未知用量及61条未知价保留，累计实际费用未知。暂停期间仅整理和合入当前结果，不新增真实模型调用。

## 当前结果分批合入本地 main

按用户“先把当前结果，分批合入main”整理三批：调查证据、直接原因报告及历史审计（117d931）；持久测试环境、真实请求日志与每轮计费（abf6f2f）；运行结果和使用文档。调查运行版本与历史审计共用契约，因此放在同一批。本次不修改生产诊断逻辑、不恢复目标、不推送远端。

合入检查覆盖24个相关测试文件：897 passed、1 failed、1条既有PyMilvus弃用警告。环境与计费相关197项全部通过。唯一失败为 `tests/test_live_probe_mechanisms.py::test_live_harness_offline_contract_and_rejects_wrong_observation[ok]`，断在 `scripts/verify_probe_mechanisms.py:197` 的诊断终态断言；独立导出合入前 main（751c5fc）源码运行同一用例，复现相同失败，确认是已有问题。未放宽断言，也未把本次检查记为全通过。

检查材料为 `runtime/aiops-main-integration-20261106.{xml,log}` 和 `runtime/aiops-main-baseline-751c5fc.{xml,log}`。账号、密钥、数据库、费用账本及原始运行材料继续留在被忽略的本地目录；无关动画文件保留未提交。原始文件指纹保存在 `runtime/aiops-main-original-files-20261106.json`。

本次新增真实模型调用0次、费用0元；最新诊断账本仍为034的1191条记录，累计预留46.821550元、已定价返回估算46.728634元，累计实际费用未知。normal未通过，endpoint尚未在最终代码上再次验收，不将合入视为完整目标通过。

以下保留各轮历史记录。

## 011：endpoint 未通过

运行目录 `runtime/aiops-goal-011/`，正式前端发起。17次请求912—928均200且有usage，本轮峰值估算1.236878元，累计预留34.427352元。最终输出截断，状态failed、unlocated。

最早断点：完整端点错配证据链已在第6步齐备，模型终态意图缺原因码和主引用时，校验生成的兜底检查使一次原因核对被跳过。后续提议重复膨胀，最终截断。原失败保留。恢复三业务200、所属进程停止和端口释放通过。

修复：原因核对提前，允许完整证据链及模型终态意图先获得一次字段反馈；标记进入原调查记忆跨节点保留。同一调查最多一次；不自动填写根因或成功状态。相关9文件381项通过，材料 `runtime/aiops-goal-regression-cause-feedback.xml`。

## 012：endpoint 未通过

运行目录 `runtime/aiops-goal-012/`。免费Probe/MCP预检、浏览器登录及预览403通过；正式前端唯一一次诊断19次请求929—947，全部200且usage完整。本轮峰值估算0.982248元，累计预留35.409600元，其中已定价且已返回的估算35.316684元，历史710继续保留0.092916元预留，61未知价仍未知。

流程completed，根因仍未通过、结论localized_fault。完整同请求证据链第12步齐备，第13步核对已实际触发，模型补齐正确原因码及主引用；较早两个端口证据只有ID、没有原文片段，且把自然语言因果解释直接声明已排除，严格校验拒绝确认。没有修改原结果。

修复：一次原因核对提供原校验后的替代解释，并对原因必需、模型已引用或关联复查的当前有效证据补可选原文片段；说明单一有限故障条件与因果解释的表达区别。模型仍必须自己填写原因、选择引用和处理关键未知。相关9文件381项通过，材料 `runtime/aiops-goal-regression-cause-citations-final.xml`。

原结果 `runtime/aiops-goal-012/{run-details,result-summary,decision-audit}.json`。环境最终三业务200、所属进程停止、端口释放、cleanup_errors为空。

## 013：endpoint 未通过

正式前端唯一一次诊断15次请求948—962，全部200且usage完整；本轮峰值估算0.772182元，累计预留36.181782元，其中已定价返回估算36.088866元。历史710预留0.092916元及61未知价保留，累计实际费用未知。

流程completed、localized_fault，根因仍未通过。原因码和完整主引用已由模型填出；但两个自然语言替代解释仍为关键未决，模型还将应用0.5秒TimeoutError与Probe的3秒ConnectionRefusedError列为矛盾。系统没有将该提议升级为成功。

环境日志没有记录连接阶段和已收到上游响应，因此新增真实HTTP请求阶段观测：连接是否建立、超时配置、连接/发送/收头/读体阶段及实际响应状态。保留真实异常名，不统一或伪造错误。字段经既有Probe日志、证据原文片段和决策说明进入模型；比较错误时必须核对端点、时间和阶段。判因及关键未决守卫保持。

原结果在 `runtime/aiops-goal-013/`；恢复三业务200、所属进程停止、端口释放、cleanup_errors为空。下一轮继承该轮962条账本，不回退。

后续轮次继续继承实际最新账本，不从旧账本回退；未通过的场景不记为通过，不跳过endpoint。

## 014：endpoint 未通过

正式前端唯一一次诊断19次请求963—981，全部200且usage完整。本轮峰值估算1.023982元，累计预留37.205764元；已定价返回估算37.112848元，历史710预留0.092916元和61条未知价保留。

流程completed、localized_fault。模型消费了真实传输阶段日志，矛盾列表为空，正确原因码和主引用齐全；但将“localapp内部错误”“edge自身内部错误”直接声明excluded，没有可验证条件与引用。严格守卫保留关键未知，未确认根因。环境恢复三业务200、所属进程停止、端口释放及清理通过。

修复扩展现有有限条件：text_logs/允许服务#实际request_id 可核验该请求的连接是否建立、响应码和传输阶段。只接受当前有效、未截断、同服务同请求的类型正确且一致日志；自由文字因果仍不能直接按有限条件排除，不自动填根因。模型需自行用已核验事实修订解释或继续保留未知。相关10文件537项通过，1既有PyMilvus警告；材料 `runtime/aiops-goal-request-condition-final2.xml`。早期两份失败回归保留，错误测试构造分别修正范围登记和正文变更后证据哈希。

下一轮015继承014的981条账本。原014失败不回写，修复后的真实效果待验。

## 015：endpoint 未通过

12次真实请求982—993全部返回且usage完整；本轮峰值估算0.650782元，累计预留37.856546元、已定价返回估算37.763630元。历史未知保持。

模型完整原因及主引用正确，仍有替代解释不满足门槛：沿用全主机端口快照代替允许端口定向查询；引用片段不匹配；自然语言因果标题与有限条件不绑定。系统保留localized_fault，原失败不改。恢复三业务200、所属进程停止、端口释放和清理通过。

新增只读alternative_review投影，逐项给出原说明、严格条件公式、当前业务范围内的实际值及原文引用、具体引用失败原因。模型仍自行选择条件、处理独立竞争解释或继续检查；程序不转换原因果说明、不自动确认根因。提示主原因支持事实进入主引用，替代解释仅保留独立竞争项。

015后续免费回归8文件406 passed，1既有警告；`runtime/aiops-goal-alternative-review-final.xml`。保存轨迹只读回放 `runtime/aiops-goal-015-alternative-review-replay.json`，原文件hash不变。

## 016：endpoint 未通过

15次请求994—1008全部返回且usage完整，本轮峰值估算0.696184元，累计预留38.552730元、已定价返回估算38.459814元；历史710未知usage/0.092916元预留及61未知价保留。流程completed、localized_fault，未通过根因验收。

完整主原因链已取得，模型补齐原因码及主引用；替代解释仍缺合法引用、有限条件或语义绑定，且结论核对反馈把本次临时分配但尚未保存的新候选ID交给模型，模型照抄后被身份守卫拒绝。另发现反馈按原始提议生成alternative_review，遗漏旧ID恢复的condition，未能显示实际值和可用引用。原失败保留。

免费修复只调整反馈：新候选ID留空，与现有健康核对一致；alternative_review使用经过原守卫恢复条件的替代解释副本，不改变原提议或保存状态，不放宽引用/原因/关键未知门槛。新增回归修前确实失败；修后结果见后续登记。环境恢复三业务200、进程停止、端口释放及cleanup_errors=[]通过。

016后续：8文件352 passed、1既有警告，材料`runtime/aiops-goal-cause-feedback-final.xml`。实际016保存轨迹只读重建的新反馈具备继承条件、实际值和可用引用，新候选ID为空；原016文件hash不变，结果未升级成功，材料`runtime/aiops-goal-016-cause-feedback-replay.json`。

## 017：endpoint 未通过

13次请求1009—1021全部返回且usage完整，本轮峰值估算0.652294元，累计预留39.205024元、已定价返回估算39.112108元；历史710未知usage/0.092916元预留及61未知价保留。流程completed、localized_fault，未通过根因验收。恢复三业务200、进程停止、端口释放及cleanup_errors=[]通过。

016候选ID冲突已消失，模型主原因及主引用正确，但原始输出仍省略替代解释的condition、evidence等字段，只有ID和状态；默认空值被严格校验拒绝。结论核对输入约8.7万字符，重复完整调查历史与反馈。

免费修复仅精简一次结论核对的输入：保留目标/权限/工具契约、已执行检查、保存候选ID及条件、原提议与逐项反馈、完整原因证据片段；移除重复整包记忆和证据。明确要求完整填写替代解释字段，不改变原因、关键未知或引用门槛。只读017轨迹回放输入31422字符，原文件hash不变、0模型，原提议没有自动升级成功；`runtime/aiops-goal-017-focused-cause-replay.json`。

相关8文件352 passed、1既有PyMilvus警告，`runtime/aiops-goal-focused-cause-final2.xml`；此前唯一失败为测试读取方仍要求旧冗余输入，已更新为同时核对初始调查和精简反馈中的证据可达性，失败JUnit保留。真实效果待018验证。

## 018：endpoint 未通过

正式前端一次诊断14次请求1022—1035全部返回且usage完整，本轮峰值估算0.615550元，累计预留39.820574元、已定价返回估算39.727658元；历史710未知usage/0.092916元预留及61未知价保留。流程completed、localized_fault，未通过根因验收。模型在原因核对中给出正确根因码和主引用，但多个alternatives原始输出缺condition、evidence、critical、limitation、claim_type等，Pydantic默认值掩盖遗漏后被现有门槛拒绝。报告已在前端展示并通过正式runs接口保存；报告内容仍未达到完整诊断结论。恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]通过。

修复：新增仅供模型响应使用的ModelAlternative schema，要求模型显式返回evidence、limitation、critical、noncritical_reason、condition（可为null）及claim_type；历史持久化继续使用兼容的Alternative模型。未放宽判因或引用守卫。相关9文件372 passed、1既有警告，`runtime/aiops-goal-alternative-required-final2.xml`；原始018模型输出的缺字段回归拒绝覆盖。018刷新/后端重启后读取未验收，原因验收仍失败。

下一轮019继承018的1035条账本，不能跳过endpoint。

## 019：endpoint 未通过

正式前端一次诊断6次请求1036—1041，全部返回且usage完整，本轮峰值估算0.165886元，累计预留39.986460元、已定价返回估算39.893544元。流程completed、unlocated。首要证据尚未齐：模型检查了localapp配置和日志，却把临时配置端口7482作为未登记端口直接查询；合法登记依赖`localapp_upstream`未被模型选中。edge/localapp/downstream当前请求证据链未完成。保存轨迹显示alternatives.check另有缺字段和伪工具名参数映射；系统仅因顶层检查无效触发一次格式纠正，未覆盖alternative自身的不可调度检查。恢复三业务200、进程/端口清理通过。

免费修复：一次纠正现可由声明的有效工具触发，即使参数映射键是伪工具名；同时将alternative内有执行意图但未过调度守卫纳入纠正触发。修正结果仍经过完整的现有工具、范围、身份和参数守卫，未使伪工具可执行。相关9文件373 passed、1既有警告，`runtime/aiops-goal-correction-eligibility-final2.xml`，含伪名纠正及未知工具仍拒绝/不纠正边界。真实效果待020验证。

下一轮020继承019的1041条账本，继续endpoint。

## 020：endpoint 未通过

正式前端一次诊断15次请求1042—1056全部返回且usage完整，本轮峰值估算0.782354元，累计预留40.768814元、已定价返回估算40.675898元；历史710未知usage/0.092916元预留及61未知价保留。流程completed、localized_fault，未通过根因验收。模型通过纠正机制读到配置、localapp同请求失败日志、错误端口无监听、登记downstream健康及edge同请求转发日志；初次和原因核对均提出正确原因码与主引用。校验仍拒绝两个关键项：一个有限条件公式被模型加上因果说明导致语义绑定失败，且实测值反驳预期；另一个独立网络解释无法由当前有限条件证明，模型仍将其关键性未决。正式前端报告保存/展示，含19个引用控件；刷新及后端重启读取未验收。环境恢复及清理通过。

免费修复仅让原因核对反馈逐项给出字段选择提示：公式不一致时精确复制现场条件公式、把因果措辞放到限制说明；实际值反驳预期时，由模型决定是否排除该有限条件并引用观察；无可表达条件的因果主张保持未决，除非另有引用依据。提示生成不更改主张、状态或引用。相关9文件374 passed、1既有警告，`runtime/aiops-goal-alternative-guidance-final.xml`。真实效果待021验证。

下一轮021继承020的1056条账本，继续endpoint。

## 021：endpoint 未通过

正式前端一次诊断12次请求1057—1068全部返回且usage完整，本轮峰值估算0.528584元，累计预留41.297398元、已定价返回估算41.204482元。模型经一次原因核对给出正确原因码和主引用，但最终localized_fault。证据核对识别出edge自身故障解释被错误写成“edge收到了503”的有限观测，观测本身不能证明该因果解释；其余有限条件已通过。报告在正式页面展示、含20个引用控件；刷新/后端重启读取未验收。环境恢复三业务200、进程停止、端口释放、cleanup_errors=[]。

反馈修复进一步明确：有限公式即使观察成立，也只证明该观测，不支持或排除旁边的因果文字；模型需保留该因果项为关键未决，或引用证据说明为何它不可能解释当前请求。没有自动改状态或确认根因。9文件374 passed、1既有警告，`runtime/aiops-goal-alternative-causality-guidance-final2.xml`。真实效果待022验证。

下一轮022继承021的1068条账本，继续endpoint。

## 022：endpoint 产品链路通过

正式前端一次诊断，1069—1080共12次真实请求均返回且usage完整，本轮峰值估算0.538468元，累计预留41.835866元、已定价返回估算41.742950元。历史710未知usage/0.092916元预留及61未知价保留，累计实际费用未知。未放宽原因或引用校验，最终completed/confirmed_cause，原因码configured_downstream_endpoint_mismatch。

模型取得配置快照、同哈希加载及失败日志、错误端点失败与登记下游200、同request_id入口503链；报告解释配置3581与实际3580错配，保留未知历史，包含影响范围、修配置及重启建议与复测步骤。五个主引用API读取成功且页面点击均定位到证据。普通账号按现有权限仅读取脱敏元数据，不开放原始证据。刷新、同轮后端停止重启后报告/diagnosis/证据元数据完全一致，账本hash不变，新增模型调用0。材料：本轮persistence-acceptance.json及三份page-*.json。

恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]通过。先前失败不回写。下一轮023继承本轮1080条账本，首次验证stopped。

## 023：stopped 未通过

1081—1090共10次真实请求均返回且usage完整，本轮峰值估算0.439708元，累计预留42.275574元、已定价返回估算42.182658元。停止请求、同实例退出、当前进程/监听缺失、配置同哈希与同请求失败链已齐，模型两次提出downstream_stopped_after_request及主引用；但三条自然语言因果替代解释无有限条件却标excluded，原守卫按契约恢复unresolved，completed/localized_fault，不能称通过。

最早断点是结论反馈未明确给出每项状态的硬契约：自然语言因果项即使引用原文匹配，也不能标supported/excluded。新增逐项admissible_statuses与status_contract，要求保留因果未知或由模型用引用解释为何不影响本次请求，有限条件只能单独核验，不替换原因果主张。不改变状态、根因、引用、critical或sufficient守卫。新增断言修前失败，9文件374 passed/1既有警告，runtime/aiops-goal-causal-status-final.xml。实际023保存反馈只读回放4项，14份原JSON文件hash不变，原localized_fault未升级、0模型。恢复三业务200、进程与端口清理通过。024继承1090条账本继续stopped。

## 024：stopped 未通过；停止证据门槛修复

1091—1100共10次真实请求均返回且usage完整，本轮峰值估算0.480116元，累计预留42.755690元、已定价返回估算42.662774元。completed/localized_fault。此次主链完整性被系统误拒：定向端口快照有TIME_WAIT连接但无LISTEN，停止根因门槛却要求ports=[]及matched_count=0，未进入一次原因核对。原模型最终省略主原因码/引用，仍失败，不能将离线修复当成真实成功。

复用已有_condition_value的listening有限观察判断，允许完整定向快照中仅有非监听连接；仍有LISTEN、截断、错误、时间/目标/同请求等不符继续拒绝。TIME_WAIT/ESTABLISHED回归修前2失败、LISTEN拒绝通过；修后9文件377 passed/1既有警告，runtime/aiops-goal-stop-listener-final.xml。实际024固定checkpoint时间只读重放得到8份完整主链证据，14份原JSON文件hash不变，原localized_fault不回写，0模型。恢复三业务200与进程/端口清理通过。025继承1100条账本继续stopped。

## 025：stopped 未通过；主引用缺项反馈修复

1101—1113共13次真实请求全部返回且usage完整，本轮峰值估算0.666768元，累计预留43.422458元、已定价返回估算43.329542元。监听修复已使完整停止链通过，但最终completed/localized_fault：原因核对提议漏了inventory和配置快照两项必需主引用，且两个解释仍为关键未决。模型在limitation已说明配置一致及edge同请求转发503，却未把不影响当前原因的判断填写到noncritical_reason；程序不代做判断。历史710未知usage及61未知价保留，累计实际费用未知。环境恢复三业务200、进程停止、端口释放、cleanup_errors=[]。

新增只读supporting_evidence_review逐项列出既有门槛所需证据的操作、对象、有效引用状态、原文片段及缺失ID；模型仍须自行选原因和填写全部主引用。明确非关键理由的字段契约，不自动补引用、改critical或放宽验收。新增回归修前失败，修后9文件378 passed/1既有警告；补充反馈接线断言后本文件38 passed。实际025固定checkpoint时间回放识别出同样两项缺引用，17份原JSON hash不变、0模型、原失败保留。材料runtime/aiops-goal-citation-review-{before,final,integration}.xml及本轮citation-review-replay.json。026继承1113条账本继续stopped。

## 026：stopped 未通过；不完整根因提议补查反馈

1114—1121共8次真实请求全部返回且usage完整，本轮峰值估算0.319162元，累计预留43.741620元、已定价返回估算43.648704元。模型已取得downstream停止生命周期、进程/端口缺失、localapp配置及失败日志，但在读取edge同请求日志前提出停止根因并结束。完整链未齐，未触发原先仅限完整链的一次原因核对；最终completed/localized_fault，025主引用反馈真实路径本场未触发，不能称已验证有效。环境恢复三业务200及进程/端口清理通过。

最小修复把同一次核对扩展到模型明确提出已有原因码、但尚未完整的终态：反馈列出已采集类别/缺项与原文，明确类别齐全不代表内容成立，由模型选择下一项合法检查。仍不自动采证、补原因/引用或放宽守卫。缺edge的最小回归修前失败；9文件379 passed/1既有警告。实际026固定checkpoint时间回放唯一缺类别为edge日志，12份原JSON hash不变，原失败保留、0模型。材料runtime/aiops-goal-incomplete-cause-{before,final,integration}.xml及本轮collection-gap-replay.json。027继承1121条账本继续stopped。

## 027：stopped 未通过；终态竞争项反馈修复

1122—1134共13次真实请求全部返回且usage完整，本轮峰值估算0.632500元，累计预留44.374120元、已定价返回估算44.281204元。完整停止主链和8项主引用已齐，但模型将下游无监听、localapp未连上下游、edge已连上localapp这3个主因支持事实仍留作supported/critical竞争项；最终completed/localized_fault。原失败不改，不能称停止根因通过。环境已恢复三业务200、所属进程停止、端口释放，cleanup_errors=[]。

最小修复扩充只读alternative_review：呈现实际status、critical及是否满足原终态门槛；逐项说明supported并非excluded，由模型决定把主因支持事实放入supporting_evidence并从竞争解释移出，独立竞争原因仍须按原门槛处理。系统不自动分类、补引用或放宽根因/关键未知。定向回归修前失败，修后9文件451 passed/1既有警告，材料runtime/aiops-goal-terminal-alternative-regression-final.xml。实际027固定checkpoint时间只读回放确认3个阻塞项，17份原JSON hash保持、0模型；terminal-review-replay.json保存新反馈。028继承1134条账本继续stopped。

## 028：stopped 未通过；移除反馈中的因果/有限条件冲突

1135—1144共10次真实请求全部返回且usage完整，本轮峰值估算0.397226元，累计预留44.771346元、已定价返回估算44.678430元。模型在核对中补齐停止原因码与13项主引用，最终completed/localized_fault。主原因链完整，但配置错配解释仍critical/unresolved，edge因果解释按照反馈被改写成“端口正常监听”的supported/critical有限事实。不能称根因通过。环境恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]。

最早明确反馈冲突：causal_explanation即使附带condition，不能由有限事实核验因果文字；旧text_binding却无差别要求改写成exact_condition_text。现只对observed_condition给该指令；因果项保持独立，同时向所有未满足终态要求的条目呈现原门槛（有效排除或引用支持的不影响本次直接原因说明）。不自动变更状态、critical、原因或引用。定向断言修前失败、修后9文件452 passed/1既有警告。保存实际1144输入只读回放识别1处冲突，14份原JSON hash不变、0模型、原失败保留。材料runtime/aiops-goal-causal-review-{before,final}.xml及本轮causal-review-replay.json。029继承1144条账本继续stopped。


## 029：stopped 根因与持久读取通过；报告旧限制需修正

1145—1152共8次真实请求全部返回且usage完整，本轮峰值估算0.361544元，累计预留45.132890元、已定价返回估算45.039974元；历史710未知usage/0.092916预留及61未知价保留，累计实际费用未知。正式前端诊断completed/confirmed_cause/downstream_stopped_after_request，生命周期、配置同哈希、当前进程/监听缺失、TCP拒绝与同请求两端503链形成8项主引用。普通账号脱敏证据读取及全部引用定位通过。

刷新和同轮后端重启，报告/诊断/引用原文元数据与哈希保持，账本hash不变、新增模型0。最初比较失败仅因fresh按当前时间计算从true到false；核对run_store的fresh_until计算后，验收改为所有保存字段严格相等、fresh只允许随时间过期，不改产品行为、不把过期证据重新标新鲜。persistence-acceptance.json记录8项过期。

报告仍含“尚未独立验证停止或启动失败”的旧依赖缺口，故完整报告内容暂不判通过。最小修复仅在已通过原根因门槛的diagnosis_result中移除已由有效主引用覆盖的依赖缺口，保留其他缺口与更深历史未知；候选检查拒绝提示明确不属于已确认主因依据。不改根因门槛、模型主张、候选历史、旧运行结果。相关9文件382 passed/1既有PyMilvus警告，runtime/aiops-goal-final-gap-final3.xml；此前路径错误和测试桩失败材料保留。029原轨迹只读回放保留全部主引用，12份原JSON hash不变、0模型，final-gap-replay.json。

恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]。030因启动前误建输出目录被入口拒绝，后端也未启动，0模型；保留启动失败日志。下一实际轮031继承029的1152条账本验证stopped报告，normal仍未测。


## 031：stopped 未通过；检查纠正顺序修复

1153—1162共10次真实请求全部返回且usage完整，本轮峰值估算0.436140元，累计预留45.569030元、已定价返回估算45.476114元。completed/localized_fault。模型取得停止生命周期、配置同哈希、进程/监听缺失及同请求两端失败日志，但没有依赖探测。最终明确提出probe_dependency_probe却漏next_arguments，系统先进入原因核对，后续格式纠正被跳过；原因核对清空检查，缺项未执行。原失败保留，未做该失败场刷新/重启验收。环境恢复三业务200、所属进程停止、端口释放，cleanup_errors=[]。

最小修复让带有无效具体检查意图的提议先走既有一次格式纠正；候选复核即使清空无效字段，仍检查原始提议。沿用同一followup_check_error参数守卫并显式要求新提议的Probe参数，不自动补参数/取证/确认根因；没有显式检查的完整主链终态仍优先原因核对。初版回归383通过但实际031回放失败，补齐候选清字段边界后9文件384 passed/1既有PyMilvus警告，runtime/aiops-goal-check-before-cause-final3.xml。真实保存提议固定checkpoint时间只读回放从initial/cause_correction变为initial/check_correction，15份原材料hash不变、0模型/工具，check-order-replay.json；不代表模型真实补参或执行成功。032继承1162条账本继续stopped。


## 032：stopped 未通过；确认意图缺字段的反馈入口修复

1163—1172共10次真实请求全部返回且usage完整，本轮峰值估算0.416552元，累计预留45.985582元、已定价返回估算45.892666元。检查格式纠正实际执行，但最终模型选择confirmed_cause时省略root_cause_code、root_cause及supporting_evidence；入口edge日志未查，主链不完整，原因核对条件又依赖原因码，因此未触发反馈。最终completed/localized_fault，原失败保留；失败场未做刷新/重启验收。环境恢复三业务200、所属进程停止、端口释放，cleanup_errors=[]。

现沿既有一次原因核对接受显式confirmed_cause意图，即使缺原因字段也反馈；不影响只声称localized_fault的旧路径。缺原因码时只展示两类既有原因共同的采集类别，不推测原因码、不填引用、不自动取证。新增缺字段回归修前失败，初版触发范围过宽导致旧localized测试2失败，收窄后9文件385 passed/1既有警告，runtime/aiops-goal-missing-cause-final2.xml。032保存提议只读回放已触发cause_correction并指出edge日志缺失，重复原提议仍被拒绝；15份原材料hash不变、0模型/工具，missing-cause-replay.json。033继承1172条账本继续stopped。


## 033：stopped 产品链路通过

1173—1183共11次真实请求均返回且usage完整，本轮峰值估算0.528572元，累计预留46.514154元、已定价返回估算46.421238元。正式页面发起并展示completed/confirmed_cause/downstream_stopped_after_request：downstream同一PID/实例先启动、收到停止请求再退出；无监听/进程、TCP失败、localapp配置及同request_id两端503日志相互印证。报告含直接结论、8项主引用、影响范围、处理建议、复测方式和历史未知。普通账号8项引用均可定位；刷新和同轮后端重启后报告与引用元数据一致，账本hash不变、新增请求0。fresh按实际时间自然过期，非保存内容变化。环境恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]。

此前032失败记录保留。本轮历史710未知usage/0.092916预留及61未知价保留，累计实际费用仍未知。下一轮034验证normal，之后再以新轮确认endpoint在当前代码下仍通过。

## 034：normal 未通过；用户暂停目标

正式前端一次诊断1184—1191共8次真实请求全部返回且usage完整，本轮峰值估算0.307396元，累计预留46.821550元、已定价返回估算46.728634元；710未知usage/0.092916预留及61未知价保留，累计实际费用未知。completed/unlocated，未声称具体故障，但主引用为空，未形成合格的正常范围报告，不能判normal完整通过。失败场刷新及后端重启读取未验收。

实际工具已取得三服务配置身份进程、三端口监听、edge及downstream业务探测200、localapp配置和日志及downstream日志；没有执行localapp和localapp_upstream依赖探测。模型却在healthy提议中声称三段探测均200，遗漏主引用，且将自然语言因果替代解释直接标excluded，被原守卫拒绝。一次health_correction反馈仅列全部必需对象，未明确区分已取得但漏引与真正未采集；模型转而要求重复已有localapp进程查询，重复守卫拒绝后收尾。判断为正常结论路径的证据消费、缺项反馈及模型契约适配问题，非工具不可达或前端未发起；不能放宽原守卫或自动把200判全局正常。还需核对正常路径是否应复用已有逐项引用/替代解释反馈，尚未实施修复。

用户暂停后停止后端和环境，environment.json确认恢复三业务200、所属进程停止、端口释放、cleanup_errors=[]。未新增生产代码或付费复测。继续时先免费修复/回放034，下一轮使用035及034账本，不能复用034重置预算。endpoint当前代码再验尚未执行。保存材料：result-summary.json、decision-audit.json、latest-state.json和product/tool_trace.json。
