# 持续监察与接管

## 2026-11-17 逐项修复后的状态

未登记 Probe 检查的服务继续读 Prometheus up；显式登记的服务可读白名单业务 HTTP 状态/总耗时、白名单桌面 JSON 快照。连续 3 个不同的新鲜故障样本开事故，连续 2 个不同的新鲜正常样本关闭事故；重复、过期、缺失或模拟样本不累计恢复。

事故保存原始 Probe 证据。诊断收到受限数值摘要（HTTP 状态、总耗时和阈值，或错误数、窗口完整性、事件循环延迟和阈值），原始实例标签不进入模型输入。业务耗时包含 DNS、TCP、HTTP 读取，不能解释成应用内部耗时。桌面适配器消费已存在的运行时快照，本轮尚未提供常驻 DSH profiler。

监察运行已关联同一事故，允许安全回读本轮证据；管理员可以复查步骤、证据和工具账本。报告待审保存为 pending_review，同一 thread_id 恢复并同步事故结果。配置、免费预检和经验审核发布见[逐项修复记录](project-workflow-fixes-20261117.md)。

以下为早期状态原文，保留取证过程。后续已保存 teamMembersOf 的 DSH 现场栈及数组防护修改，见[DSH 调查参考](dsh-autonomous-investigation-reference-20261117.md)；完整成员功能恢复和卡顿根因仍未确认。不得将下文“未找到现场栈”视为最终状态，也不得把历史栈改写成当前新鲜信号。

## 早期状态原文

## 当前能力

FastAPI 启动时可选运行一个后台监察 worker。它从 Prometheus 查询配置服务的 `up` 样本，持久化每次观察；连续 3 个新鲜故障样本打开事件，连续 2 个新鲜正常样本关闭事件。过期、缺失或后端不可用的样本记为 `unknown`，不触发故障或恢复。

多 worker 部署使用文件锁保证只有一个进程采样。未取得锁的 worker 会按监察间隔重试；取得锁后持续持有，直到应用关闭或任务取消。事件可选交给 AIOps 只读诊断，不会执行修复操作。

诊断启动时会把同一事件中保存的触发采样时间和 `up` 值交给 Agent，作为调查时间窗线索；原始实例标签不会放进模型输入。单轮采样的意外异常只记录异常类型并在下一周期重试，worker 不会因一次瞬态错误退出。

## 配置

在 `.env` 中按实际 Prometheus 标签与服务名设置：

```dotenv
MONITOR_BACKEND=prometheus
PROMETHEUS_URL=http://127.0.0.1:19090
OPS_WATCH_ENABLED=true
OPS_WATCH_SERVICES=mall-api
OPS_WATCH_INTERVAL_SECONDS=30
OPS_WATCH_STALE_AFTER_SECONDS=120
OPS_WATCH_AUTO_DIAGNOSE=false
```

`OPS_WATCH_SERVICES` 需要匹配当前 `up` 查询的服务名/instance 规则。先用 `OPS_WATCH_AUTO_DIAGNOSE=false` 确认样本、事件和恢复过程；改为 `true` 后，事件打开时会调用诊断 Agent，模型请求可能产生费用。

## 管理接口

以下接口均要求管理员身份，只读，不会启动监察任务：

- `GET /api/v1/monitor/watch/services`：开关、最新观察、数据源、错误和当前事件。
- `GET /api/v1/monitor/watch/incidents`：最近事件列表。
- `GET /api/v1/monitor/watch/incidents/{incident_id}`：事件证据与诊断结果。

## 能力边界

当前只持续查询 Prometheus `up`，用于发现服务不可达；它不检测响应延迟、错误率、进程卡死、桌面应用 UI 卡顿或 JavaScript 插件异常，也没有 DSH 的事件循环与插件日志采集器。单靠 `up=1` 不能证明业务请求正常，`up=0` 也不能定位根因。

要覆盖 DSH 一类问题，还需接入可审计的运行时信号，例如插件异常栈、宿主/插件 API 版本、事件循环延迟和对应时间窗日志，再让诊断报告把结论绑定到原始证据。此前窗口的历史对话文字曾出现 `Cannot read properties of undefined (reading 'map')`，但本次读取窗口时该错误不在当前页面；最新可读插件运行日志记录在 2026-11-07，早于本次 2026-11-17 检查，未提供可关联的调用栈。安装的 `dsh-better-sidebar@0.28.2` 声明 `getTabs()` 返回数组，调用端直接执行数组过滤、排序和映射；这是一个需要宿主满足的 API 前置条件。独立 JavaScript 模拟能够复现“若 `getTabs()` 返回 `undefined`，数组映射会抛错”的异常形态，但没有证明 DSH 现场返回过 `undefined`，也没有证明该调用就是页面报错来源。页面历史文字提及的 FPS 下降、壁纸插件与 GPU/renderer 占用关系尚无 profiler 采样佐证。故本次没有据此修改 DSH 插件；现场根因仍未确认。
