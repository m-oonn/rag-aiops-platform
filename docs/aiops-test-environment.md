# 诊断测试环境：启动与验证

当前诊断目标已暂停（2026-11-06）；本次只整理并合入已有结果。以下启动步骤供后续明确恢复测试时使用，当前结果见 [产品链路进度](aiops-product-goal-progress-20261106.md)。

现在可以持续运行真实的 edge → localapp → downstream 业务链路，经 Probe/Gateway/MCP 接入正式诊断后端和现有前端。默认只启动免费环境和页面；显式开启真实模型后，才允许从页面发起一次诊断。

验收目标是：页面发起 → 模型主动检查 → 原因与引用证据齐全 → 系统生成报告 → 保存 → 页面展示 → 刷新、后端重开后仍可读取。环境 ready 只代表可以测试，不能等同于这个目标已通过。

## 启动免费环境

在项目根目录打开 PowerShell。使用项目现有 .venv；首次使用且 frontend/dist 不存在时，先执行 `npm --prefix frontend run build`。前端源码变化后也要重新构建。

终端 A：

```powershell
Set-Location 'D:/ragPdfSystem++agent'
./.venv/Scripts/python.exe scripts/aiops_test_environment.py start --output runtime/aiops-manual-01 --scenario endpoint --duration-seconds 3600
```

输出目录必须是新目录。看到 `status: ready` 再启动后端；端口自动选择，实际业务地址打印在终端，也保存在 environment.json。默认运行一小时，最长十二小时，不安装系统服务。

| scenario | 实际场景 | 用途 |
|---|---|---|
| endpoint | 应用启动加载错误下游端口，下游本身正常，入口 503 | 检验配置与实际请求链归因 |
| stopped | 下游收到停止请求后退出，入口同样 503 | 检验相同表象下能否找到不同原因 |
| normal | 三层业务正常，入口 200 | 检查是否误报故障 |

每次启动和切换场景都先产生实际业务请求，再开放调查。edge、localapp 日志有相同请求编号、时间、进程实例及加载配置哈希；不是只访问 /health 后让模型面对空日志。

终端 B：

```powershell
Set-Location 'D:/ragPdfSystem++agent'
./.venv/Scripts/python.exe scripts/aiops_test_environment.py backend --output runtime/aiops-manual-01 --port 8200
```

打开 http://127.0.0.1:8200/login 。账号密码在运行目录的 login.json，仅在本机查看。登录后打开 http://127.0.0.1:8200/aiops 。任务文本取同目录 symptom.txt。登录默认跳到工作台，此环境只开放诊断相关接口，直接转到 /aiops 即可。

此模式可验证登录、页面和已有报告读取。点击“开始诊断”会返回明确的 403，不会偷偷调用模型。后端仅监听本机，复用正式认证、诊断图、保存和报告接口；测试数据库、checkpoint、原始证据、向量及上传目录均独立。Gateway 与产品后端共用该环境的 runs.sqlite，使页面状态与实际 Probe 注册一致。其他产品接口未开放。

## 操作环境与退出

在第三个 PowerShell 窗口创建标记文件，环境会处理并删除标记：

```powershell
# 再产生一次当前场景的业务请求
New-Item -ItemType File runtime/aiops-manual-01/request -Force | Out-Null

# 恢复正常
New-Item -ItemType File runtime/aiops-manual-01/restore -Force | Out-Null

# 再注入启动时选择的故障
New-Item -ItemType File runtime/aiops-manual-01/inject -Force | Out-Null

# 查看状态、当前轮次、请求结果及退出检查
Get-Content runtime/aiops-manual-01/environment.json
```

**切换前先结束诊断并停止后端，切换完成、状态重新 ready 后重启后端。** 切换会重启相应业务进程、更新连接目标登记并重新连接 Probe；旧轮次日志和配置先保存在 rounds/<轮次>/。后端绑定启动轮次，旧后端不会继续在新轮次发送模型请求。不要在诊断途中修改业务文件或切换故障。

推荐退出方式：

```powershell
# 先停止页面后端；终端 B 返回命令提示符后，再停止业务环境
New-Item -ItemType File runtime/aiops-manual-01/stop-backend -Force | Out-Null
New-Item -ItemType File runtime/aiops-manual-01/stop -Force | Out-Null
```

正常退出先归档故障材料、恢复三业务接口 200，再清理所属进程和端口。检查 environment.json 中 status=stopped、recovery=three_business_endpoints_200、ports_released=true、owned_processes_stopped=true、cleanup_errors=[]。Ctrl+C 也会清理，但异常中断不冒充已验证恢复；强制结束控制器进程不能保证 finally 执行。

## 启用真实模型诊断

真实调用需要用户授权。当前完整链路目标已授权按轮测试和修复；每轮使用新环境目录，先完成免费检查，再关闭默认后端、保持环境 ready，执行：

```powershell
./.venv/Scripts/python.exe scripts/aiops_test_environment.py backend --output runtime/aiops-manual-01 --port 8200 --run-model --profile .env.agent-test --previous-cost <实际最新的cost.json路径>
```

命令只启用后端，不自动诊断。登录 /aiops，复制 symptom.txt，保持“常规诊断”，点击一次“开始诊断”。完整结果应通过正式 SSE、runs 接口和页面读取，不能用脚本猜出的答案替代模型报告。

执行前核对实际最新账本。每轮新增模型请求最多 5 元，包含所有角色、重试和备用模型；历史累计保留展示，不占新轮的 5 元额度，也不再用旧累计上限阻止新轮。底层累计发送上限按本轮起点历史预留加 5 元设置，同时独立检查本轮新增费用。

本轮起点由 `product-model/run-budget.json` 固定历史账本哈希、继承条数、继承预留和本轮限额。后端重启必须传入该轮启动时相同的 `--previous-cost`，续用本轮账本，不能把新增费用重新归为历史或重置额度。历史第 710 条 ReadTimeout 及未知价格记录继续保留，累计实际费用仍未知；本轮新增未知用量会阻断后续发送，重启不能绕过。

当前目标已明确允许保留历史未知项并继续逐轮测试，因此无须重复提供历史超时例外文件。旧单场授权流程仍支持可选 `--timeout-authorization`，用于严格绑定历史记录，格式如下；其限额和哈希必须按对应历史流程核验，不要将该示例作为本轮默认启动要求：

```json
{
  "version": 1,
  "kind": "single_historical_read_timeout",
  "user_authorization": "填写本次用户实际授权原文",
  "previous_sha256": "最新cost.json文件字节的SHA256",
  "output_dir": "D:/ragPdfSystem++agent/runtime/aiops-manual-01/product-model",
  "limit_cny": 33.058792,
  "run_limit_cny": 5,
  "request_number": 710,
  "request_sha256": "第710条按json.dumps(row,ensure_ascii=False,sort_keys=True).encode('utf-8')的SHA256",
  "reserved_cny": 0.092916
}
```

模型运行材料保存到 product-model/。首次启动建立账本；同轮后端重启会核验并续用原账本，报告与引用从原数据库读取，读取不会调用模型。每次后端启动只接受一次已认证的诊断 POST；不得通过重启另发诊断来重置本轮预算。先免费预览，再开启真实模型，不会消耗此次诊断机会。

## 材料及判断标准

| 文件 | 内容 |
|---|---|
| environment.json | 就绪、当前轮次、业务请求、恢复与清理状态；environment_model_calls 仅表示夹具本身调用数 |
| preflight.json | 初次真实请求及 Probe/MCP 日志可达、控制器答案不可读检查 |
| business/ | 当前业务进程产生的日志和加载配置 |
| rounds/ | 切换或退出前归档的旧轮次日志、配置和状态 |
| product/runs.sqlite、checkpoints.sqlite、evidence/ | 正式诊断保存、恢复与引用材料 |
| product/tool_trace.json、knowledge_trace.json | 实际工具调用和隔离手册检索记录 |
| product-model/cost.json、model-inputs/ | 实际模型请求计量和脱敏输入，判断付费调用次数以此为准 |
| controller-only.json | 控制器核验用真值，禁止作为模型证据，不经网页静态目录暴露 |

完整验收还应检查：报告明确指出直接原因和受影响链路，有可打开的支持引用、处理与复测步骤、未知限制；关闭重开后报告和引用一致，刷新不发新模型请求。目标未齐就保留失败，不能仅以 workflow complete 或 localized_fault 算根因通过。

当前场景能证明“加载了哪个端点、请求如何失败”或“发生了停止请求”；没有提供真实变更者的历史审计记录，所以谁修改、为什么部署仍可能未知。不能要求模型凭空补出更深历史。

## 初版验证结果（2026-11-06，历史记录）

相关五个测试文件 63 项通过，1 个既有 PyMilvus 弃用警告；材料 `runtime/aiops-environment-final.xml`。免费完整 endpoint 预检 19 观测、恢复与清理通过，`runtime/aiops-environment-preflight-20261106-a/report.json`。

持久环境 `runtime/aiops-test-environment-free-20261106-c/` 已验证真实浏览器登录、诊断页加载和刷新、免费诊断 403、私有文件不经网页暴露、目标在线状态、恢复与重注入后同请求日志经 MCP 可取且旧日志排除。控制验证首次读取方把 tcp 字符串当对象，修正验证读取后通过，未改环境结果。

本轮真实模型调用 0、费用 0。付费传输通过 MockTransport 检查预留参数与实际请求一致、主备和各模型调用角色共用计量、未知 usage 后不续发、输出目录不可重用；尚未新跑真实模型，未证明自主根因或最终完整报告到页面已经通过。
