# 四组续测准备（2026-11-02）

状态为 prepared_pending_human_review，未执行。已有总新增10 CNY、单场不超过5 CNY的授权继续有效，不要求重复预算授权。

当前继承395条账本、累计峰值预留13.022834 CNY，累计上限19.969390 CNY，估算余量6.946556 CNY；历史61条未知价格不回填。账本sha256为d4912ff82bfc82d86f0b4d8b003557e7d14940abfd56ba68ad1f7e5a82bb2b97。

准备范围为 e2-fault-pair-v1：downstream_unreachable 与 application_config_error 各G00/G10/G01/G11，共8场，实际顺序由既有控制器随机化。症状统一candidate-opportunity，同一实现、模型、知识和工具权限，仅切换两项机制；各场独立状态。沿用DeepSeek可计价通道，4096输出Token，自动重试关闭。

计划每场等额0.80 CNY，8场最多6.40 CNY，余0.546556 CNY留作未分配额度；不设置请求数上限。0.80是本批可分配预算，不保证每次调查都能完成；若预算或其他失败，保留原失败与最新账本，先查原因、免费修复与回归再决定续测，不清零、不重复发送未经修复的失败场。最近下游场0.662606 CNY，因此本批费用可能不足，不能预先宣称完整成功。

机器可读准备记录见 runtime/healthy-fault-closeout-20261102/four-group-preparation.json，executed=false，model_calls_in_preparation=0。它不是审核文件，也不包含smoke_passed。执行前必须重新核对当前源码、最新账本、余量及实际用户审核结果，不能仅据本文件发送请求。

当前唯一进入四组的前置缺口是用户真实语义审核。项目AGENTS.md要求关键结论人工语义审核，scripts/verify_windows_local_faults.py的extended/four-groups入口要求审核文件smoke_passed=true；三场审核包仍human_decision=null、smoke_passed=false。详见 docs/healthy-fault-semantic-review-20261102.md，已在会话提出诊断、引用支持、建议适用性三个问题，未重复提问、未代填答案。

本次准备没有新增模型请求、没有新故障注入、没有改生产代码，也没有将原目标标记complete或paused。上一轮为实质进展：最终相关回归388项通过并准备38份审核证据；本轮完成当前审核状态、最新账本hash和8场预算容量核对及可执行范围准备。
