# 阶段二修复与剩余额度复验

结论：三个程序与配置问题已修复，免费回归通过；真实模型故障定位仍未达标，阶段二尚未通过。

## 本次修改

- Probe 完整原文仍按 raw_hash 校验。另用诊断内容比较检测更新与重复：仅 dependency_probe 排除顶层 elapsed_ms，TCP、HTTP、响应内容及截断变化仍保留。耗时仍存入证据，可供分析，不能仅因耗时变化就制造冲突。
- 有效后续检查中，执行器只绑定 next_tools 和当前运行 read_run_evidence；其他工具仍由原守卫拒绝，不扩大权限。
- 本地服务配置新增 kind，默认 windows_service；显式 process 对象不查询 SCM，返回 not_applicable，inventory 公布类型。进程和日志仍沿用白名单。临时故障应用改用 process，常驻 Probe 未部署更新。
- 澄清 localized_fault 与深层原因未知可以并存；未自动升级模型结果，也未降低 confirmed_cause 门槛。

## 免费验证

新增反例先复现 4 项失败、1 项通过，修改后相关测试 167 passed；全量后端 589 passed、99 deselected，1 个既有 PyMilvus 弃用警告。

独立预检目录：`runtime/windows-local-faults-a9ac1e8c53074b3c9b5f2d2c59caff7a`。24 项检查通过、44 条现场证据、0 次模型调用；包含六类故障控制器预检、固定决策调查图、checkpoint 重开、证据拒绝、重连和持久快照。固定决策结果不能证明真实模型自主性。自建进程全部退出、端口释放。

前端、Compose 本次未重新运行：本次没有改动其代码或协议；此前通过记录见原 smoke 报告，不能算本轮新验收。

## 真实模型复验

运行目录：`runtime/windows-local-faults-d3ae4aeb3f8349d8b7662591844f2a1f`。随机顺序先下游不可达，再正常。

| 场景 | 实际结果 | 判定 |
| --- | --- | --- |
| 下游不可达 | 10 份有效现场返回；查到入口 HTTP 503/upstream connection failed、入口进程与监听、下游 ConnectionRefusedError、日志和下游端口。最终 unlocated，contradictions 为空 | 证据机械门通过；未达到 localized_fault，能力未通过 |
| 正常 | 模型规划请求完成后，后续请求被累计预算保护拒绝；仅 inventory 为有效现场返回，无最终报告 | 未完成，不能判断健康场景是否修复 |

下游运行：`model-8dc6a8572d884aea925369dc19def623`。本场没有服务查询 unavailable 干扰，也没有 outside_investigation_check 拒绝；模型明确识别 process 类型。不过仍把更深下游进程/日志不可读作为停止理由，没有形成故障层结论。还发现语义问题：将支持“下游不可达”的证据列在同名解释的 excluded 状态；机械引用检查无法发现这种含义矛盾，不能据引用通过认定推理正确。独立人工因果裁决仍待完成。

正常运行：`model-dee7c4076f2742eab1a3fdc8242940bc`。budget_stopped=true，has_final_report=false；整套脚本 ok=false，原因是正常场景因预算未完成。故障恢复 normal_restored，自建进程已退出，无剩余监听。

两场知识 MCP 调用均为 0；没有知识关闭对照，不能宣称知识改善。未进行其余四类真实模型场景或真实业务验收。

## 费用核对

继承原账本 26 次请求、预留 3.253464 元；本次新增 14 次，累计 40 次，累计预留 **4.9807032 元**，剩余预留空间 0.0192968 元。账本前缀逐项核对一致，不能将累计账本相加。40 次请求均 HTTP 200 且有 usage；预算拦截发生在下一请求外发前。按 usage 和当前价格估算累计约 1.0531008 元，最终结算以供应商账单为准；保守预算不按估算返还，没有重置或提高额度。

核对产物：运行目录下 `retest-audit.json`、`blind-controller.json`、`summary.json`，及各场 cost/summary/mechanical-review。原始运行结果未改写。

## 尚需完成

下一轮应先免费检查分级结论选择与替代解释状态语义，保留事实与因果门槛；不能把模型 unlocated 强行改为成功。再用新授权复验正常与故障层定位，通过后才扩展知识开关对照和其余场景。本轮不再调用模型，不部署常驻服务，也不对真实业务制造故障。
