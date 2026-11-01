# 四组请求预算入口与有限预实验方案

日期：2026-10-30。最新状态：用户已确认本批新增预算最高5元；官方价格及旧模型名映射已核实，按已核价模式启动，首场后停止。实际新增6次、累计58、峰值估算0.15209元，其余11场未执行。详见[实测及修复结果](four-group-5cny-result-20261030.md)。下文未知价方案和52条命令为授权前历史准备，不能作为自动续跑入口。

## 本次解决的问题

此前未知价格模式只能执行 smoke，四组要求人民币预留额，不能用于当前未核价的 DeepSeek 通道。现复用既有 PaidRequestBudget，增加每场新增请求上限，并将两类上限贯通 CLI、实际 HTTP 发送前门槛、账本、运行记录、控制器和只读汇总。

- `--max-model-requests`：累计上限，包含全部继承请求；每场固定相同值。
- `--run-max-model-requests`：本场新增上限，每场重新计算起点；四组各场额度相同。
- 未核价四组必须显式给出两个正整数上限。启动前检查累计剩余容量足以覆盖12场各自上限，缺额先拒绝，再启动调查。
- `request_limits` 在 cost.json 和 summary.json 保存累计上限、单场上限、继承条数；evaluation-record.json 保存配置。审核重算实际条数及账本前缀，并检查三处一致。
- 超限请求记 `sent=false`，不加入已发送账本。若调用者吞掉失败，下一次实际发送仍检查先前请求的 HTTP 状态和 usage；失败或缺 usage 后不能继续发送。
- 单场额度用尽保留已有证据和失败报告；控制器停止整批、恢复正常现场，不能把未完成报告计作完成。
- 未核价保持 estimated_cny_peak=null。预留0不是费用0；原人民币模式继续兼容。
- 控制器保存版本3记录；汇总沿执行顺序检查 previous_cost 与完整账本前缀，拒绝跳过、重用、修改额度及场景/组次序不符。旧版记录继续只读兼容。

## 原拟执行范围（授权前历史记录）

| 项目 | 范围 |
| --- | --- |
| 模型 | 既有私有 DeepSeek 官方 profile，deepseek-v4-flash；本次不更换模型或全局配置 |
| 场景 | mechanism-v1：正常、下游不可达、入口配置解析错误 |
| 组别 | G00/G10/G01/G11，各场景各一次，共12场，随机次序，独立状态与线程 |
| 历史累计 | 继承52条，原文件只读，不能从43条或GLM旧链重启 |
| 单场新增 | 最多12条，包括结构输出格式回退等每次实际HTTP尝试 |
| 整批新增 | 最多144条，累计硬上限196；实际失败提前停止，不自动补跑 |
| 单请求 | 最多4096输出Token，HTTP操作超时60秒，SDK和Agent自动重试关闭 |
| 费用 | 未知；次数和输出上限不是人民币价格上限，保留全部历史消费 |
| 故障处理 | 任一场失败、缺usage、配置/来源变化或恢复失败即停止；保留失败材料 |
| 成功含义 | 工程流程和记录通过，不代表诊断正确或机制有效；无保护机会就如实记无机会 |

12次/场是预实验资源上限，参考上一成功G11实际9次留出3次余量；不保证所有组都能完成。每场景每组仅一次，无统计显著性结论，不能当正式效果实验。若上限导致未完成，先分析已保存记录，不自动增额。

最新账本：

`runtime/windows-local-faults-2920366e12a6491796771cd7bc46168a/model-65882ad684a34c289a365f5d09ee8d9b/cost.json`

本轮只读：52条，HTTP200且usage完整，reserved_cny=0、limit_cny=5；SHA256 `f8933a83bc7b197bb9595bd4aeea2f37a23bc1d0c291ec91c04df12a7cb4c292`。5元字段保留旧兼容语义，不能解释为本次未知模型人民币封顶。

## 原准备入口（历史命令，不作续跑授权）

人审已由本会话用户实际完成并登记：[上一真实G11逐项审核](g11-semantic-review-20261030.md)、[人审及修复结果](g11-review-followup-fixes-20261030.md)。三个维度分别接受有限定位、主要引用支持、建议有条件适用；调查不充分、说明文字问题与重复建议一并记录。后续免费修复367项回归通过，原报告和成绩保留，未自动放行本批。

上一真实G11的人工语义审核（诊断、引用支持、建议适用性）已完成，仍需据其限定结果明确决定是否放行预实验，不能自动推导 smoke_passed。既有审核包在 `runtime/concrete-g11-preparation-20261030-a/human-review/`。现有 `--smoke-review` 仍要求真实放行依据，不因CLI支持就自动放行。以下路径中的 `human-smoke-review.json` 尚未创建。后续可将阶段放行和以下整批付费范围在一次明确确认中处理，避免重复询问。

明确本批范围和未知费用并获授权后，才可在项目根目录执行：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py --profile .env.deepseek-agent-test -- scripts/verify_windows_local_faults.py --run-model --model-stage four-groups --four-group-suite mechanism-v1 --allow-unpriced-model --max-model-requests 196 --run-max-model-requests 12 --max-output-tokens 4096 --previous-cost runtime/windows-local-faults-2920366e12a6491796771cd7bc46168a/model-65882ad684a34c289a365f5d09ee8d9b/cost.json --smoke-review runtime/human-smoke-review.json
```

若执行前又产生了合法的新账本，本方案的52/196及来源绑定失效，需按最新账本和授权重定范围，不能直接执行旧命令。

执行后消费本次控制器目录，用 `python -m scripts.summarize_evaluations --source <本次目录> --output <新的汇总目录>` 生成工程汇总，再逐场人审。保留完整失败、未知费用、机会数与实际改查数；不按事件标签推断有效性。

## 免费验证与限制

回归使用 MockTransport 和替代子进程，不访问供应商、不启动常驻服务或新现场。覆盖继承52条、两类上限分别拦截、上游吞错后的发送门槛、CLI人审门槛、12场独立状态与账本接续、额度篡改及旧人民币模式。最终六文件361项通过，保留一条既有PyMilvus警告；早期新增测试因未设置私有模型端点的替代夹具导致1项失败，已在测试中明确固定端点，定向6项和最终范围通过，不修改生产端点或全局环境。

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/test_four_group_controller.py tests/test_evaluation_record_consumption.py tests/test_windows_probe_evaluation.py tests/test_evaluation_record.py tests/test_investigation_failure_flow.py tests/test_windows_local_faults.py -q -m 'not integration'
```

以上是免费准备阶段的结果。随后实际放行五元预算并执行首场，结果及最新58条账本见[实测报告](four-group-5cny-result-20261030.md)。阶段E仍未完成，失败即停授权已结束；不得从本页历史命令自动重跑。未重跑全量、前端/浏览器，未提交推送。
