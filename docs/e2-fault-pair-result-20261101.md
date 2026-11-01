# E2 两故障四组预实验执行结果（2026-11-01）

## 结论

本批已启动，但未完成。仅执行到随机顺序的 `downstream_unreachable/G01` 一场；其余 7 场没有运行。首场子报告和逐场机械检查通过，外层四组控制器因无法核对症状输入 profile 而以 `ValueError` 停止，避免将不完整或不一致实验记作成功。原控制器状态 `failed` 保留；不自动重跑或续跑。

## 真实调用与账本

- 模型：隔离 profile 下的 DeepSeek `deepseek-v4-flash`，served model 为 `deepseek-flash`；GLM 未使用。
- 实际场次：`downstream_unreachable/G01`，症状 profile 为 `candidate-opportunity`。
- 新增请求：8 次，8 次均 HTTP 200 且 usage 完整；输入 101,204、输出 9,806 Token。峰值费率估算新增 0.280856 CNY，供应商实际账单未核实。
- 账本从 202 条延续到 210 条，峰值预留从 5.250858 增至 5.531714 CNY。原 202 条逐条前缀相同；旧的 52 条未知费用仍保持未知。新账本 SHA-256：`7f3752a2e6682193a5a3884866bd86816190ef602240d839abde157ec5a85c71`。
- 子场报告为 `localized_fault`，引用支持 downstream TCP `ConnectionRefusedError` 与端口 3199 无监听；下游启动/退出的深层原因未确认。保护机会和矛盾机会均为 0，实际机制改向为 0；诊断语义尚未人工审核。
- 控制器状态 `failed`，恢复状态 `normal_restored`。入口与下游已回到 HTTP 200，临时所属进程停止，测试端口释放，清理错误为空。
- 控制器汇总 `ok=false`；只读 `summarize_evaluations` 也返回 `passed=false`，原因是四组不完整、缺少每故障场四组齐全材料。不能进行 G00 对照或报告 E2 效果。

## 停止原因与修复

外层控制器把 `symptom_profile` 当作需要逐项比对的配置，但子场 `evaluation-record.json` 没有保存症状输入。首场的请求预算、计费模式、source signature、子场完整性和机制审计均通过，失败具体发生在 profile/config 一致性门槛。

免费修复把实际症状文件 SHA-256 纳入子场记录及四组控制器记录，并要求汇总重算 profile hash、逐场核对相同 hash；原有严格审计不放宽。相关 264 项定向回归通过。此修复只用于后续批次；原场结果、控制器状态和账本均未回填。

首次用反斜杠脚本路径调用 profile 启动器时，命令在模型进程启动前被白名单精确匹配拒绝，0 模型请求；改为正斜杠后才开始本次唯一真实场次。该启动器路径格式不影响后续模型结果。

## 复核材料

- 原始控制器与完整运行目录：`runtime/windows-local-faults-c67edf3b7ec245b5b8dbd88779f6a7f8/`
- 本次账本：`runtime/windows-local-faults-c67edf3b7ec245b5b8dbd88779f6a7f8/model-03716ed562ab46afa6de9d65d91c012f/cost.json`
- 独立只读汇总：`runtime/four-group-e2-20261101-a/summary/summary.json`
- 独立授权和限制：`runtime/four-group-e2-20261101-a/human-smoke-review.json`
- 新套件与免费现场预检：`docs/e2-fault-pair-preflight-20261101.md`、`runtime/windows-local-faults-f1af7b7deeb24dc7b5be15c65603da71/four-group-scenario-preflight.json`

本次 5 CNY 授权没有被整体消耗；按账本峰值估算，本次新增 0.280856 CNY，余下授权上限为 4.719144 CNY，不自动转为后续调用。由于整批已按失败停止约定结束，剩余 7 场需要用户重新明确授权后才可执行。不得把已有 G01 结果回填成通过，不得更改本次失败状态。
