# Windows Probe 隔离故障验收清单

本清单区分本机专用测试应用和隔离 Windows 环境。当前电脑允许对本项目明确创建的回环测试应用及模拟下游验证进程退出、HTTP 错误、依赖不可达和专用端口冲突，只操作可核实归属的测试进程，并在结束后恢复、核对无残留监听。不得停止现有业务或系统服务，不做持续 CPU 压力、系统盘空间耗尽或扩大真实业务白名单。服务停止、整机资源故障等场景仍需隔离 Windows 虚拟机或测试主机。

本机采集脚本为 scripts/verify_windows_local_faults.py；默认由脚本选择场景与检查顺序，验证真实采集和固定模型流程，不是自主根因盲测。增加 --evaluation-preflight 可在正常和下游不可达时调用 evaluate_windows_probe.py 的免费预检，保存并校验现场证据。具体证据及失败历史见 docs/windows-local-fault-verification-20261017.md。evaluate_windows_probe.py 默认仅预检，支持 --probe-config、--symptom-file 和不覆盖已有目录的 --output-dir。verify_windows_local_faults.py 已接入显式 --run-model 的两场串行编排及累计5元费用账本，第二场继承第一场请求与预留，费用不明或执行失败时停止并清理；该参数不能代替用户授权。编排与账本边界仅经过离线测试，真实付费路径未运行。最新默认免费现场回归17个检查条目通过、model_calls=0，不能声称真实模型故障盲测通过。真实模型故障验收仍需新费用授权。

## 每个场景的统一流程

1. Probe 已连接，目标状态为 `online`，最近 baseline 未过期。
2. 只把用户侧症状交给 AIOps，不提供故障类型或答案。
3. 保存完整事件流、证据时间线和最终报告。
4. 核对每条结论是否包含真实 `target_id`、`collected_at`、`source` 和原始证据 hash。
5. 核对 Agent 是否检查了关键替代解释；没有证据时必须报告“未定位/证据不足”。
6. 确认没有调用 Probe 写操作、任意 Shell、服务重启或配置修改工具。

## 场景矩阵

| 场景 | 隔离环境动作 | 期望优先证据 | 不能接受的结论 |
|---|---|---|---|
| 服务停止 | 停止白名单 Windows Service | `probe_service_status` 显示 stopped，相关 Event Log | 只凭用户描述断言应用崩溃 |
| 进程退出 | 结束白名单进程，保持 Service 状态可见 | `probe_process_snapshot`、服务与进程对照 | 把 Service running 当作进程健康 |
| 端口冲突 | 由无关进程占用配置端口 | `probe_port_snapshot` 的 PID/进程名 | 没有端口证据就断定绑定失败 |
| 数据库不可达 | 仅阻断配置中的数据库地址或端口 | `probe_dependency_probe` 的 DNS/TCP/HTTP 结果 | 把网络探测失败直接当成数据库内部故障 |
| 应用日志报错 | 写入测试应用白名单日志的错误事件 | `probe_text_log` 或 `probe_event_log` | 把知识库示例当作现场证据 |
| CPU 持续升高 | 在隔离应用进程中制造可回收 CPU 负载 | resources/processes 前后 baseline | 只看到瞬时 CPU 就下结论 |
| 磁盘空间不足 | 使用隔离盘或可删除测试文件降低空间 | resources 磁盘 free/percent，时间对齐 | 对系统盘做不可逆删除 |
| HTTP 健康检查失败 | 让配置依赖的测试健康接口返回失败 | dependency probe 的 status/body_prefix | 使用未配置的新地址探测 |

## 通过条件

单个场景只有同时满足以下条件才算通过：

- Agent 选择了与症状相关的 Probe 数据源，并能根据新证据换方向；
- 根因由至少一条现场原始证据直接支持；
- 关键替代解释已检查，或报告明确说明无法检查；
- 证据时间、目标和来源可在 AIOps 证据时间线复核；
- 证据过期、目标不匹配或 Probe 离线时没有被当作当前事实；
- 没有执行未审批的修改、重启或任意命令。

正常场景和每种故障场景都要分别记录。真实模型结果与确定性流程测试分开报告，不能用规则测试结果代替未知答案调查。
