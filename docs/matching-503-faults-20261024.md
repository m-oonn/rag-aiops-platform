# 相同入口503、不同现场原因的故障验收

日期：2026-10-24。免费故障场景与采集验收，未运行真实模型。

## 实现

复用 scripts/verify_windows_local_faults.py 的专用入口和下游进程，保留原 application_error=500 场景，新增 application_config_error=503。控制器向测试应用的独立配置文件写入无效 max_attempts；处理请求时实际执行整数解析并产生 ValueError，异常处理返回503，应用日志记录配置字段及异常类型。下游保持正常。有效整数配置可重新走正常处理路径。

下游不可达仍由控制器停止本轮下游进程制造，入口捕获连接失败。两个场景都返回503和同一正文 temporarily unavailable；连接失败细节移到日志，避免仅凭响应文案区分。日志继续由真实请求产生，不预写诊断答案或机制事件。

verify_case_state 增加新场景，核对入口/下游HTTP、进程和监听归属、统一正文、入口当前监听PID对应的日志及ValueError。使用实际监听PID兼容Windows虚拟环境启动器的子进程。免费 --evaluation-preflight 中新增场景，正式Probe/MCP采集入口、下游和白名单日志，保存 matching-503-observations.json 与 ev 引用，再恢复正常并独立核对。原真实模型 smoke/extended 样本列表未自动新增该场景，不改变尚未授权的实验范围。

## 实际结果

成功输出：runtime/windows-local-faults-87750cb6d3f34bc6b55ff26319f19e9e/。summary.json：ok=true，27个检查条目，48条控制器现场证据；十二次机制调查的36条证据另计。model_calls=0，errors=[]，owned_processes_stopped=true，ports_released=true，remaining_listeners=[]。

| 现场观察 | 下游不可达 | 应用配置解析失败 |
| --- | --- | --- |
| 入口HTTP | 503 | 503 |
| 入口正文 | temporarily unavailable | temporarily unavailable |
| 下游TCP | failed | ok |
| 下游HTTP | 无可用响应 | 200 |
| 入口日志 | upstream connection failed | invalid max_attempts configuration，ValueError |

matching-503-audit.json 已将两场共六个ev ID逐条匹配到 evidence.json 的原始Probe返回，并核对日志PID属于各场入口监听者。controller-observations.jsonl 最后一条为独立验证通过的normal恢复。知识28份前后审计均通过，没有cost.json。自有库14/本地BM25仍与主PDF库15分开，不据此证明主库消费或远程索引版本一致。

运行前后未发现8103/8104/8105/8106/8200/5273常驻监听，不将此前日期的PID沿用为本轮在线状态；本轮没有启动或停止这些演示服务。隔离测试的5388/5389/5390/5391端口已释放。

## 检查、失败与限制

定向 tests/test_windows_local_faults.py 首轮81项通过，含真实子进程两类相同响应及有效配置恢复。反例覆盖原因泄露到正文、错误日志、外来PID、错误异常类型；后续增加缺响应正文时仍保存失败记录。最终六个相关文件205项通过，1条既有PyMilvus弃用提醒，记录runtime/matching503-20261024-final.xml。此前扩大回归204项通过，保留runtime/matching503-20261023-final.xml。

首次申请正常权限环境运行时，自动审批服务503导致审批检查未完成，命令没有执行。2026-10-24按同一权限流程重试通过；未绕过ACL或审批。现场成功日志为runtime/matching503-controller-20261024-a.log。缺响应留痕补强发生在现场成功之后，仅重新运行相关回归，不重复正常场景注入。

本次新增的配置故障是简化测试业务中的真实运行异常，证明可独立制造和采集，不代表生产业务覆盖度。入口503本身只说明接口失败；下游TCP失败只支持连接层异常，不能解释进程为何退出。配置日志和下游正常能区分本次两个受控场景，但字符匹配不等于已证明全部因果链。没有运行自主模型或检验机制效果，不统计准确率。

未改.env、主数据库、前端或生产Agent机制，未提交推送；既有工作树修改保留。没有重复全仓、前端构建或浏览器验收。此前planner新逻辑没有经本轮重启加载到主API。

## 下一步与学习入口

下一步免费核对正式结论边界：让这两类已保存的真实现场证据经过现有调查裁决，核查只有入口503时不能归因下游、下游正常不能认定不可达、缺关键日志时保留未查清原因。先查已有覆盖再补最小回归；不预写机制事件，不用固定决策冒充自主能力。

2026-10-24 后续已完成该步骤并修复共享裁决的自由文本因果误确认漏洞，见[结论边界修复与免费重放](matching-503-conclusion-boundaries-20261024.md)。当前不能自动确认自由文本根因，72项历史规则检查及413项相关回归通过，仍未运行自主模型。

需要理解的具体流程是：配置解析或依赖请求产生真实异常 → 应用对外返回同一503 → Agent工具分别读取下游与日志 → 结论须受这些证据约束。系统完成场景验收，没有本轮用户复述或亲手操作记录，不更新独立掌握程度。
