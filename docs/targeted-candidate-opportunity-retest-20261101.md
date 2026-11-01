# 候选机会提示定向复验（2026-11-01）

## 目的

在不重复运行四组的前提下，使用 `candidate-opportunity` 症状提示，对 `downstream_unreachable/G11` 做一次低请求上限的 DeepSeek 定向复验，观察模型是否形成可执行候选、保护机会或矛盾改向。

## 免费前提

- `mechanism-v1` 场景预检通过：12 次场景切换、48 条 Probe 观测、恢复和端口释放通过。
- 预检无模型调用、无费用，产物为 `runtime/windows-local-faults-4c971500efda44409980c9992deb6f94`。
- 候选机会提示契约及控制器/机制回归通过；本次使用的代码版本没有回写历史运行。

## 实际执行

- 模型：DeepSeek `deepseek-v4-flash`，通过 `.env.deepseek-agent-test` 专用 profile。
- 场景：`downstream_unreachable`。
- 机制组：`G11`。
- 输入：`--symptom-profile candidate-opportunity`，单请求输出上限 1024。
- 继承账本：四组运行的 179 条请求；累计请求上限 183，因此本场最多新增 4 条。
- 运行目录：`runtime/windows-local-faults-de4bc14f990f4e54bea159ead6bac1b2`。

首次直接调用控制器时没有通过 profile wrapper，子进程继承日常模型环境并以 `APIConnectionError` 退出；该次账本仍为179条，新增请求和费用均为0。随后确认专用 profile 解析为 `deepseek-v4-flash` 后才执行上列正式尝试。

## 结果

- 新增 4 条请求（180—183），均 HTTP 200 且 usage 完整，served model 为 `deepseek-flash`。
- 累计请求 183，峰值预留从 4.660508 元变为 4.709822 元，仍低于 5 元上限。
- 第 4 次后达到累计请求上限，调查未完成；没有最终机制轨迹，`mechanism_audit.behavior.status=not_assessed`。
- 这次不产生保护机会、矛盾机会或机制效果结论；不能把未完成当作模型没有机会。
- 控制器恢复 `normal_restored`，临时进程停止、端口释放、清理错误为空。

## 结论与下一步

本次只验证了新提示能进入 DeepSeek 正式入口并受累计请求上限约束，未取得足够请求完成调查。剩余余额约 0.29 元，但请求上限已到 183；按失败即停规则不自动追加调用。下一步回到阶段 C：开发并免费验证一个能自然产生候选反证的机制适用场景，再决定是否需要新的、单独授权的模型预算。
