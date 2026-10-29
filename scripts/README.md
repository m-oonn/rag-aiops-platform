# 脚本分类导航

日常入口保留在顶层；模型与后端探针集中在 probes/。从项目根目录按下列路径调用。旧评测脚本不等于当前毕设四组主实验协议。

## 日常启动与本机运维

- `tools/faulty_demo_site.py`、`tools/win_node_exporter.py`：演示靶站与 Windows 指标导出器，完整路径为 scripts/tools/。

- `launch_demo.py`：演示环境状态、启动与停止；从项目根目录执行。
- `create_tables.py`：创建数据库表；`run_full_pipeline.py`：既有完整链路工具，会启动服务并调用模型。
- `windows_probe.py`：Windows Probe 命令入口。
- `demo.sh`、`start_milvus.sh`、`docker/`：现有辅助启动入口。
- `diag_net.py`、`discover_prometheus_metrics.py`、`_check_procs.py`、`_watch_proc.py`、`_measure_resources.py`：网络、指标与进程排查。

## 现场验证与离线重放

- `verify_free_demo.py --output runtime/<新目录>`：免费工程演示，保存前后选定源码、运行真实专用故障与受控失败，再核对历史正式API/SSE/刷新；`--verify runtime/<已有目录>`只读复核hash。不代表自主效果，不进入模型入口，详见docs/free-demo-walkthrough-20261026.md。

- `verify_windows_local_faults.py`：专用本机测试业务与故障控制器。
- 其 `four-groups` 模式复用同一环境，要求已审核smoke、累计账本、显式付费模式与单场额度；参数不代表用户授权。免费离线验收及限制见 docs/four-group-orchestration-20261025.md。
- `verify_windows_probe_*.py`、`verify_installed_windows_probe.py`、`verify_probe_*.py`：Probe、权限、证据、图执行、浏览器及保留策略验证。
- `verify_diagnostic_boundary.py`、`verify_aiops_cross_process_resume.py`：诊断边界与跨进程恢复检查。
- `replay_aiops_decision.py`：历史决策重放。
- `verify_windows_runbook_retrieval.py`：手册检索验证。
- `verify_mcp_e2e.py`、`verify_deepseek.py`、`verify_human_output.py`、`_verify_fixes.py`：既有专项检查。

验证脚本可能启动独立进程、连接服务或使用真实模型；先读参数与前置条件。名称包含 verify 不代表免费或纯离线。

## 实验、评分与数据准备

- `summarize_evaluations.py`：只读核验自主运行完整性并比较条件一致的四组本场费用/时间；旧格式保留但不满足新门槛。用法见 docs/evaluation-record-consumption-20261025.md，不启动模型。

- `evaluation_record.py`：Windows自主实验的选定源码副本、配置指纹与生命周期记录；不独立启动模型。记录口径见 docs/evaluation-record-integrity-20261025.md。

- audit_thesis_materials.py：只读核对审核包、原始观测与机制现场材料的来源，按完整观测去重，不计算准确率。用法见 docs/thesis-material-lineage-20261025.md。
- `summarize_mechanism_runs.py`：免费汇总既有固定决策四组记录、工具次数、部分耗时与行为审计；失败/缺件不静默删除，待审不计正确。用法见 docs/mechanism-run-summary-20261025.md。
- `mechanism_behavior.py`：核对机制机会、候选、计划与实际工具执行；`verify_historical_mechanism_behavior.py` 从可信本地 checkpoint 只读还原已有轨迹，结果另存新目录。见 docs/mechanism-behavior-20261024.md，不证明自主效果。
- `diagnostic_review.py`：为已有运行生成离线人工审核包并校验意见记录；无模型调用，待审不计成功，使用新的输出目录。用法与口径见 docs/diagnostic-review-20261024.md。
- `evaluate_windows_probe.py`、`evaluate_autonomous_investigation.py`：现有真实模型评测入口。
- `run_ablation_eval.py`、`run_pi_opt_ab_eval.py`、`run_blind_eval.py`、`run_explainability.py`、`run_robustness.py`：历史实验工具，组别与当前两机制四组协议需要分别核对。
- `blind_fault_gen.py`、`compare_with_project_evaluator.py`、`eval_precision_recall.py`：故障样本与结果处理。
- `evaluate_rag.py`、`run_ragas_eval.py`、`index_runbooks.py`：RAG 评测及索引，真实模型调用和入库需遵守项目授权。
- `run_rag_eval.py`：手工回答与上下文的模型评分，输出写入 runtime/manual-rag-eval/，不能代表真实检索效果。
- `seed_es_change_events.py`、`seed_es_demo_logs.py`、`download_hf_datasets.py`、`download_kaggle_datasets.py`：数据准备，不作为日常启动步骤。

## 探索脚本与论文工具

- `probes/probe_*.py`：模型、接口、站点或真实后端探针。执行前检查网络、费用与目标，不批量运行；例如 `python scripts/probes/probe_site.py --help`。
- `try_aiops.py`、`try_mcp_client.py`、`mini_agent_pne.py`、`run_demo_diagnosis.py`：既有探索与示例入口。
- `_assemble_thesis.py`：读取 `docs/thesis/` 草稿；还需要原有论文分册目录。个人材料归档后需另行核对输出位置，不能直接视为可用的论文流水线。

## 产物位置

- 服务日志统一写入项目 `logs/`；原根目录日志保存在 `logs/legacy/`。
- 实验证据、失败与费用记录继续保留在 `runtime/`、`data/`，不要当缓存删除。
- 2026-10-23 的文档迁移清单与剩余脚本备份保存在 `runtime/cleanup-docs-20261023/`。
- 可再生缓存会随运行重新生成；不为维持目录外观删除运行数据。
