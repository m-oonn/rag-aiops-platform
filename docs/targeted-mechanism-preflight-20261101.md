# 定向机制免费验收（2026-11-01）

本轮针对“没有机制机会就不继续花真实模型额度”的要求，先执行免费定向夹具。夹具复用正式图、调查策略、证据写入和 `mechanism_behavior` 审计，只固定模型决策与工具返回，不调用真实模型，不产生费用账本。

## 验收命令

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_live_probe_mechanisms.py
& .\.venv\Scripts\python.exe -m pytest -q tests/test_mechanism_behavior.py tests/test_investigation_mechanisms.py
```

结果：`2 passed`；机制相关回归 `130 passed`。仅有既有 PyMilvus 弃用警告，没有失败。

## 定向结果

- 保护场景四组均有保护机会；只有 G10/G11 产生 `protection_check_selected`，并各执行 1 次保护改向，G00/G01 为 0。
- 矛盾场景四组均有矛盾机会；只有 G01/G11 产生 `contradiction_triggered`，并各执行 1 次改向，G00/G10 为 0。
- 无现场反证对照中，四组均没有 `contradiction_triggered`，矛盾实际改向为 0。
- 每个机制事件都通过了 `from_check`、`next_check`、工具参数、证据 ID 和成功执行记录的链路审计；G00 没有机制选择事件。
- 运行产物保存在 `runtime/targeted-mechanism-preflight-20261101-152408/test_live_harness_offline_cont0/`，没有生成 `cost.json`。

## 结论边界

这证明机制开关和审计链在明确机会下能产生可区分的实际检查选择。它仍是固定决策/离线工具夹具，不是自主真实模型效果，也不证明真实模型会在当前 `mechanism-v1` 故障场景中产生机会。此前 5 元四组真实运行机会为 0，因此本轮不继续消耗剩余额度；下一次真实模型测试必须先证明输入场景能让模型形成可执行候选和反证链。
