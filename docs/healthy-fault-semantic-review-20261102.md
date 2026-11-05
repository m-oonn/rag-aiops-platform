# 最终三场语义审核（2026-11-02）

当前状态 pending。本文件提供可核对的问题与证据，不替用户作判断，不生成 smoke_passed。工程回归与机械检查通过不能代替此审核。

原报告、summary 和现场证据的核对副本位于 `runtime/healthy-fault-closeout-20261102/human-review/`；review-package.json 保存每份原件与副本的 SHA-256。没有复制控制器真值或答案文件，原材料不回写。

## 三场诊断判断

| 场景 | 待判断的有限结论 | 关键现场证据 | 需要考虑的限制 |
|---|---|---|---|
| normal | 当前检查范围内未发现故障，候选 correct_healthy_within_scope | ev-d44d4b7b62b84bf292bdaa85a9ab07c8：入口 TCP/HTTP200；ev-ee71677cb31e4618ac0cc7f223e1da5a：下游 TCP/HTTP200；ev-245c1c8ecc8f4044bb4132a7730ee912 与 ev-6ab8547937ff40df8007d2e7c02490be：两个配置身份进程 | 仅本窗口与所列对象；日志样本很少，报告尾部仍保留历史/功能层未决问题，不承诺一直正常 |
| application_config_error | 入口503，应用日志出现配置解析异常，下游200；候选 correct_localization | ev-6d40ff381bbe44719a429699a685778a：入口503；ev-5c9b937c3b844467a6a3359baa75598b：下游200；ev-7b15a4f52c6a4dc59221d96af9987645：invalid max_attempts configuration / ValueError | 报告主结论仍是HTTP失败层；展示配置异常不等于确认其完整因果链。配置值、来源和变更历史未读到，不能称最终根因已查清 |
| downstream_unreachable | 下游连接拒绝、无监听、未匹配配置进程；候选 correct_localization | ev-a70ef4d6d38340579f6c2eff2044eafa：下游TCP失败；ev-0938c510875640debe82dca7bd818b61：8994无监听；ev-a46ff7547e3b484d9d37967fda05e2a9：配置进程匹配0；ev-37dc1aae55d4456e972c906ed61d4302：shutdown_requested / controlled_stop | 日志只证明记录了受控停止请求，不证明触发者。事件通道未配置，报告未确认谁或为何停止 |

诊断可分别接受上述候选，或选择 incomplete / wrong_cause_or_false_positive，并说明具体场景与证据。接受有限定位不等于接受调查已经充分。

## 引用支持判断

请判断三场主要结论的引用是 supported / insufficient / unsupported。机械检查只确认ID、原文和范围，未证明因果解释。尤其不能用 controlled_stop 的日志原文推导控制器身份或停止动机；也不能用一小段正常日志推导历史无故障。若不同场景判断不同，请分别指出。

## 建议适用性判断

normal 没有操作建议，可记 not_applicable。配置错误场给出有前提的日志/变更核查与人工修正建议；下游场给出有前提的进程、监听、配置核查与人工恢复建议，关联对象已归并。两场均提示重新确认故障、业务权限、影响和回退，尚未执行任何修复。请判断 appropriate / insufficient / inappropriate，特别考虑建议是否过于泛化、是否适合当前进程型应用。

## 为什么现在需要用户判断

项目 AGENTS.md 的实验纪律明确要求：“字符引用匹配不等于因果正确，关键结论需要人工语义审核。”四组与扩展入口 `scripts/verify_windows_local_faults.py` 还要求真实审核文件含 smoke_passed=true。当前为 pending，AI 不能代填。已有10元总额、单场5元的预算授权继续有效；这里缺的是实际语义判断，而非再次请求预算授权。原始范围的三类单场真实结果已有，正式四组对比及其效果验收仍未完成。
