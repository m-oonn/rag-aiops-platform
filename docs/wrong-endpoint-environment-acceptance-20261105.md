# 错误下游地址：环境搭建与免费验收

环境已搭建并自验通过。证明现场原因证据真实产生、现有工具可取、关键内容进入决策输入、修正配置后业务恢复；不证明真实模型已自主查明原因。新增模型调用和费用均为0。

## 场景与预设答案

沿用 edge → localapp → downstream 三个独立进程，真实HTTP转发。业务接口 `/api/availability` 正常返回商品可用JSON；`/live` 仅表示本进程存活。

预先固定的隔离答案：localapp启动时加载了过时的downstream端口，实际下游在登记的正确端口正常服务。本次旧端口4972、正确端口4971，每轮动态分配。故障由真实连接失败产生，没有控制器直接返回错误的分支。错误端口用不监听socket保留，避免被无关程序占用后偶然变健康；Windows本次为TimeoutError、errno=null，如实记录，不写成连接拒绝。

因果链：启动配置加载旧端口 → 实际连接超时 → localapp业务503 → edge业务503。谁改配置、为何部署旧值没有历史来源，仍未知。

答案在进程启动前写入controller-only.json，前后哈希一致；工具读取该文件被白名单以ProbeConfigError拒绝。普通runbook只描述拓扑、存活与业务区别、启动加载及处理方式，没有故障答案。实际配置和错误日志中的连接端口属于可见现场事实。

## 实现范围

- scripts/verify_windows_local_faults.py：测试服务新增可选启动连接配置，旧模式不启用；记录实际连接目标、加载配置哈希、PID/进程实例、请求ID、耗时和实际错误、启动及正常退出事件。请求ID经真实HTTP转发。
- scripts/competing_hypothesis_fixture.py：新增错误地址场景和只修地址/按需重启动作，保留其他配置；仅重启应用，下游不动，修复不覆盖故障日志。
- scripts/verify_competing_hypothesis_scenario.py：新增endpoint免费验收模式，复用Probe、网关、MCP、执行器、证据保存与实际决策输入构造。固定检查核对现有参数/范围契约；不是模型自主选择或完整自主调查。
- 本地runbook经现有检索器检索、进入既有知识输入，沿用材料及检索实现基线的前后核验。

未改调查策略、因果裁决、报告规则、公开API、工具权限；无新服务、工具或依赖。

## 正式验收

材料：runtime/wrong-endpoint-environment-20261105-b/，report.json状态passed；a目录为开发验收版本，保留。

| 核验 | 结果 |
|---|---|
| 真实业务故障 | edge业务503；downstream独立业务200且JSON正确 |
| 存活区别 | 应用与下游身份进程/监听存在，监听PID匹配；直连/live均200 |
| 实际加载配置 | 独立快照端口4972；启动及错误请求日志使用相同目标和配置哈希 |
| 错误目标 | 正式依赖工具TCP失败；端口工具未见监听 |
| 请求关联 | edge与localapp业务日志有相同request_id |
| 取证与输入 | 19条有效观测保存证据ID；原因/症状阶段实际决策输入含关键日志、目标、配置哈希及ID |
| 时间与隔离 | 本轮日志通过；新边界拒绝旧观测；答案白名单拒绝、输入无答案标记、答案hash不变 |
| 只修改文件 | 快照已是4971，原进程仍用旧哈希，入口仍503 |
| 重启应用 | 原进程正常退出、新实例加载新hash；下游进程不变，三个业务入口200且JSON正确 |
| 证据保存 | 处理前另存日志/配置，处理后日志保留故障前缀，证据文件独立保存 |
| 知识材料 | 实际检索成功；before/after基线均passed |
| 恢复清理 | 另3次独立Probe业务复测200；所属进程停止、端口释放、清理错误0 |

结构化模型调用前截获输入，0真实模型请求。19条观测含故障调查及程序处理复测，另3次恢复Probe列在report.recovery_probe。程序修复属于环境自验，不是人工依据Agent报告处理的验收。

## 回归及失败保留

最小新回归修前因不支持场景失败。开发中最初要求错误errno非空，Windows实际超时无errno，已改为核对实际错误类型，允许null。

首次六文件175 passed/1 failed：旧边界测试以object.__new__绕过构造器，缺新增startup_configuration；只补测试桩False值，未改时间守卫。失败JUnit保留runtime/wrong-endpoint-environment-regression-20261105.xml。

最终六文件176 passed、1条既有PyMilvus弃用警告，JUnit为runtime/wrong-endpoint-environment-final-regression-20261105.xml。覆盖新场景、旧夹具、网关预检读取、原控制器、配置快照及四点修复回归。新反例验证相同503可区分：错地址时下游独立正常；下游停止时配置正确且有停止记录。

此前全机制预检的工具顺序断言失败仍单列，未重跑、未放宽或回填。未增加延迟故障和四组；git diff --check通过。

## 复现与限制

免费复现（output须为新目录）：

```powershell
.\.venv\Scripts\python.exe scripts/verify_competing_hypothesis_scenario.py --output runtime/endpoint-acceptance-NEW --stop-mode request --fault-pair endpoint
```

验收自动恢复并清理，不常驻故障进程；产物保留。未改已安装Probe、业务配置或Windows审计策略。这是单机loopback实验，未模拟跨主机DNS、防火墙、TLS、并发或完整生产变更历史。

当前confirmed_cause与规则报告仍有既有因果能力限制；环境通过不消除该限制，不把故障层定位冒充根因确认。真实模型复测需另有明确授权，本次不续跑。

最新732条账本未变化，SHA256仍为0b4fe9d18e74b7f01669ce3ef9b4ecd1d662332b5d81748054c246b9f4af504f；无新增费用、历史结果不回填。
