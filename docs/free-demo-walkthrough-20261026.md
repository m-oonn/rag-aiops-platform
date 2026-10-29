# 免费演示与案例讲述

适用于本科毕设的工程演示。此入口重新采集专用业务现场，但调查中的模型决策为固定替代；报告链路一段使用另行标注的历史工具原文。展示者开场需说明这一边界，不能称为完整自主诊断效果演示。

## 从哪里运行

在项目根目录使用已有venv：

```powershell
& ./.venv/Scripts/python.exe scripts/verify_free_demo.py --output runtime/free-demo-my-run
```

输出目录必须尚不存在；每次使用新名称，失败目录保留。命令按顺序保存源码快照、启动独立临时业务/Probe/MCP、真实制造故障和恢复、核验第三轮reset受控失败，再运行24次历史正式API/图/SSE及SQLite重开刷新检查。全过程不进入真实模型入口，不使用在线embedding或重排，不启动主页面。通常需要数分钟，以运行结果为准，不承诺固定时长。

执行后只读核验：

```powershell
& ./.venv/Scripts/python.exe scripts/verify_free_demo.py --verify runtime/free-demo-my-run
```

只读模式核对材料hash和源码副本，不启动服务、不重采故障。通过表示文件一致及本次工程检查完成，不代表诊断正确或机制有效。manifest本身不是数字签名；长期存档需另行备份和记录其hash。

## 8—10分钟怎样展示

1. 用1分钟说明目标：本机专用入口和下游业务，Agent最终目标是读现场、定位故障层并给人工建议。本次展示免费工程核验，模型决策和历史输入均明确标注。
2. 用1分钟打开 `manifest.json` 与 `before/source.json`：展示基点、选定源码副本、开始时间和三个步骤的退出码。未提交代码以源码hash为准，不能只报main或一个提交号。
3. 用2分钟打开 `controller/observation-boundary/report.json`：按normal、downstream_unreachable、application_error顺序展示三种现场；入口分别200、503、500，下游分别200、TCP失败、200。每轮的controller_state是独立核验依据，不作为Agent证据。
4. 用2分钟按下面案例A查看相同503下的工具原文、对象、采集时间和hash，解释检查下游及日志的必要性。
5. 用1分钟按案例B查看旧日志拒绝与第三轮reset失败。解释停止调查和保存失败为何比继续输出成功重要。
6. 用2分钟打开 `api-tests/**/output-audit.json` 中一份evidence_count=3材料，依次查看events中的report/complete、refreshed、raw_returns。说明它是2026-10-24原始现场的固定决策重放；可展示报告与刷新一致、人工建议尚未执行，以及普通用户原文权限/跨用户访问限制已由测试核对。
7. 最后1分钟说明未完成：自主模型四组、人工语义审核、真实Windows事件日志和LocalService权限。不要把固定触发事件讲成提高准确率。

## 案例A：入口同为503，需要继续区分现场

先看 `controller/matching-503-observations.json` 的两类记录，再用其中evidence_ids去 `controller/evidence.json` 查原始记录。该文件的entry/downstream/logs是便于查看的摘录，正式证据以evidence.json中的raw为准。

| 观察 | downstream_unreachable | application_config_error | 能说明什么 |
| --- | --- | --- | --- |
| 入口HTTP与正文 | 503 / temporarily unavailable | 503 / temporarily unavailable | 仅凭入口不能区分 |
| 下游TCP/HTTP | TCP failed / 无HTTP状态 | TCP ok / HTTP 200 | 下游不可达和下游正常是不同事实 |
| 入口进程日志 | upstream connection failed | invalid max_attempts configuration / ValueError | 是本次进程记录的现象，仍需解释范围 |

可以说：第一类观察到下游连接失败，第二类观察到下游正常且入口有配置解析异常。不能说：Agent自主证明了下游为何退出、自动确认了任意因果文本或执行了修复。正式报告仍由共享裁决限制为可核验故障层与未确认部分。

**报告查看是另一批材料。** `api-tests/**/output-audit.json` 对应历史夹具 `tests/fixtures/matching503-probe-20261024.json`，不是本轮controller采集原文；不能拿本轮新证据ID去解释历史报告ID，也不能把24次重放计作24次独立故障。测试固定历史校验时钟，原始采集时间/hash不改；刷新不重新运行工具。

## 案例B：旧证据被拒绝，reset失败停止后续

打开 `controller/observation-boundary/round-1/tool_trace.json`：第一条是重置前重新读取的旧日志，status=failed、validated_live_evidence=false；它的采集时间可能是新的，但行内at早于本轮boundary，因此不能作为当前现场。随后三条为本轮入口、下游、日志，分别通过窗口校验；pre-reset.log保留旧内容。

再看 `failure/observation-boundary/report.json`：前两轮passed，第三轮failed/RuntimeError。这里是核验脚本主动让reset回调失败，并非声称业务自然出现该异常。`failure/summary.json` 必须ok=false，没有后续controller_preflight场景，owned_processes_stopped和ports_released为true，cleanup_errors为空。

可以说：系统没有把未成功重置后的环境当作新场次继续采集，已完成轮次与失败轮次分别保留。不能说：控制器失败是诊断成功、故障自动修复或通用崩溃恢复。

## 一小时亲手复现

2026-10-26用户已在项目根目录亲手执行 `--verify runtime/free-demo-20261026-a`，并贴回终端输出：passed=true、source_files=274、artifacts=340、model_calls=0、autonomous_effectiveness_verified=false。此项记为既有材料完整性只读核验完成；不是用户重新采集现场、运行完整控制器或完成自主调查效果验证。证据解释与完整演示仍待用户实践，不代填掌握程度。

在带读现场中，用户根据“入口503、下游TCP/HTTP正常”提出继续检查入口代理日志、健康检查、监控、系统应用日志和配置。项目工具核对后的可执行映射是：入口允许的 `probe_text_log`、进程/端口/资源快照；Windows 事件日志仅在目标配置通道存在时调用；没有任意配置文件读取工具，需依据允许日志、inventory 和现场记录间接核对。此回答记为能根据证据把检查方向从下游转向入口，尚不等于已独立掌握工具参数或结论裁决。

用户随后解释 `invalid max_attempts configuration / ValueError` 为重试配置不规则，并指出不能确定是哪个库。准确边界是：日志证明入口进程在解析 `max_attempts` 时发生配置值错误；不能由此确定配置来源、具体错误值、负责解析的模块或修改者，也不能证明下游故障。该回答记为能区分日志事实与未验证归因。

用户进一步指出，错误类型还可能与健康检查失败、过载熔断、维护或 CDN/网关拦截有关。该回答记录为候选扩展意识；在本场 `127.0.0.1` 专用业务中，CDN 或外部网关目前没有现场依据，不能直接纳入有效候选。健康检查、资源过载和进程/监听异常需要分别用对应 Probe 观测验证，不能由同一条 ValueError 日志代替。

用户回答先查入口进程和端口是为了确认入口服务或调度能力是否完好。需要区分：进程存在和端口监听只能证明入口具备接收请求的基础条件，不能证明应用逻辑、重试调度、健康检查决策或过载保护正常；后几项仍需应用日志、请求结果及允许的配置/资源观测支持。

用户在进程和端口正常、下游探测正常的前提下，选择继续查入口组件内部的上游健康检查、节点状态快照及入口错误日志中的 upstream 调度记录。该顺序用于区分“依赖实际正常但入口内部把节点判为不可用”与“入口配置解析/调度逻辑错误”。当前专用测试业务没有通用上游节点列表工具；若没有允许的节点状态接口，只能以入口文本日志、依赖 Probe 和已有配置范围核对，不能假设节点快照存在。

10分钟核对入口与本次manifest；20分钟运行并读真实现场；20分钟对照一个503案例和一个失败案例；10分钟用自己的话记录：一条证据属于哪次采集、它支持什么、不能证明什么。无需通读大型执行器。AI完成材料不等于用户已独立复现；亲手运行和理解程度另记。

源码入口：[免费演示脚本](../scripts/verify_free_demo.py)、[控制器](../scripts/verify_windows_local_faults.py)、[边界检查](../scripts/verify_probe_observation_boundary.py)、[正式输出核验](../tests/test_matching503_output_flow.py)。运行产物可能包含本机路径和原文，仅在本机保存，分享前另做脱敏审查，不提交token、数据库或runtime整目录。
