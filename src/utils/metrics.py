"""Prometheus 业务指标定义。

集中管理 AIOps 项目的自定义业务指标，避免在 router/service 里到处散落定义。
参考: https://prometheus.io/docs/concepts/metric_types/
"""
from prometheus_client import Counter, Histogram, Gauge

# 1) AIOps 诊断总次数(按结果切片: success/failed/timeout)
AIOPS_DIAGNOSIS_TOTAL = Counter(
    "aiops_diagnosis_total",
    "AIOps 故障诊断总次数",
    labelnames=["result"],
)

# 2) AIOps 诊断耗时(秒)
AIOPS_DIAGNOSIS_DURATION = Histogram(
    "aiops_diagnosis_duration_seconds",
    "AIOps 故障诊断耗时(秒)",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# 3) MCP 工具调用总次数(按 tool_name + result 切片)
AIOPS_TOOL_CALLS_TOTAL = Counter(
    "aiops_tool_calls_total",
    "AIOps Agent 调用 MCP 工具的次数",
    labelnames=["tool_name", "result"],
)

# 4) 当前在跑的诊断任务数
AIOPS_ACTIVE_DIAGNOSES = Gauge(
    "aiops_active_diagnoses",
    "当前正在执行的 AIOps 诊断任务数",
)
