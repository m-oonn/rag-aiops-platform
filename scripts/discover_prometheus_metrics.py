"""发现生产集群里真实的指标名与"服务名标签",据此给出可用的 PromQL 模板。

为什么需要它: 指标名与标签体系随监控栈而变 —— node_exporter 用 node_*、K8s 用
container_* 且服务名挂在 pod/service 标签上、JVM 用 jvm_*/process_*。把默认模板照抄到
生产集群,常见结果是 instance=~"{service}.*" 一个序列都匹配不上、返回 0 点。
与其猜,不如直接问 Prometheus 要答案。

三步:
  1) 列出所有含 cpu / memory 的指标名(候选);
  2) 拿你给的样本服务名,去各标签的值里匹配,找出"服务名挂在哪个标签键上";
  3) 按识别出的指标族,打印可直接粘进 .env 的 PROMETHEUS_*_PROMQL 模板。

运行(先在 .env 配好 PROMETHEUS_URL 与凭据):
    python scripts/discover_prometheus_metrics.py
    python scripts/discover_prometheus_metrics.py order-service      # 指定样本服务名
"""

import sys
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_servers.prometheus_client import _request_kwargs
from src.settings import settings

DEFAULT_SAMPLE = "data-sync-service"
MAX_LISTED = 20


def _get(base: str, path: str) -> list:
    """调 Prometheus HTTP API,返回 data 字段(非 success 直接抛错)。"""
    resp = requests.get(f"{base}{path}", timeout=settings.PROMETHEUS_TIMEOUT_SECONDS,
                        **_request_kwargs())
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success":
        raise RuntimeError(body.get("error") or "Prometheus 返回非 success")
    return body.get("data") or []


def _print_candidates(title: str, names: list) -> None:
    print(f"\n{title}({len(names)} 个)")
    for name in names[:MAX_LISTED]:
        print(f"    {name}")
    if len(names) > MAX_LISTED:
        print(f"    ... 另有 {len(names) - MAX_LISTED} 个")


def _find_service_labels(base: str, sample: str) -> list:
    """在标签值里搜样本服务名,返回 [(标签键, 命中值列表, 该标签值总数)]。"""
    hits = []
    for key in _get(base, "/api/v1/labels"):
        if key == "__name__":
            continue
        try:
            values = _get(base, f"/api/v1/label/{key}/values")
        except Exception:
            continue
        matched = [str(v) for v in values if sample.lower() in str(v).lower()]
        if matched:
            hits.append((key, matched, len(values)))
    return hits


def _suggest_templates(cpu_names: set, mem_names: set, label_key: str) -> list:
    """按识别出的指标族给模板(只给有把握的公式,识别不出就如实说明)。"""
    sel = f'{label_key}=~"{{service}}.*"'
    suggestions = []

    if "container_cpu_usage_seconds_total" in cpu_names:
        suggestions.append(
            'PROMETHEUS_CPU_PROMQL=100 * sum(rate(container_cpu_usage_seconds_total'
            f'{{{sel},container!="",container!="POD"}}[5m])) / sum(container_spec_cpu_quota'
            f'{{{sel},container!=""}} / container_spec_cpu_period{{{sel},container!=""}})')
    elif "process_cpu_usage" in cpu_names:
        suggestions.append(f'PROMETHEUS_CPU_PROMQL=100 * avg(process_cpu_usage{{{sel}}})')
    elif "node_cpu_seconds_total" in cpu_names:
        suggestions.append(
            f'PROMETHEUS_CPU_PROMQL=100 - avg(rate(node_cpu_seconds_total{{mode="idle",'
            f' {sel}}}[5m])) * 100')
    else:
        suggestions.append("# CPU: 未能识别指标族,请从上面的 CPU 候选中挑一个,"
                           "计数器用 100 * sum(rate(<指标>{...}[5m]))")

    if {"container_memory_working_set_bytes", "container_spec_memory_limit_bytes"} <= mem_names:
        suggestions.append(
            f'PROMETHEUS_MEMORY_PROMQL=100 * sum(container_memory_working_set_bytes'
            f'{{{sel},container!=""}}) / sum(container_spec_memory_limit_bytes'
            f'{{{sel},container!=""}})')
    elif {"jvm_memory_used_bytes", "jvm_memory_max_bytes"} <= mem_names:
        suggestions.append(
            f'PROMETHEUS_MEMORY_PROMQL=100 * sum(jvm_memory_used_bytes{{{sel},area="heap"}})'
            f' / sum(jvm_memory_max_bytes{{{sel},area="heap"}})')
    elif {"node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes"} <= mem_names:
        suggestions.append(
            f'PROMETHEUS_MEMORY_PROMQL=100 * (1 - node_memory_MemAvailable_bytes{{{sel}}}'
            f' / node_memory_MemTotal_bytes{{{sel}}})')
    else:
        suggestions.append("# 内存: 未能识别指标族,请从上面的内存候选中挑一对"
                           "(已用量 / 总量 相除再乘 100)")

    return suggestions


def main() -> int:
    base = settings.PROMETHEUS_URL.strip().rstrip("/")
    if not base:
        print("PROMETHEUS_URL 未配置,请先在 .env 填写")
        return 1
    sample = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SAMPLE

    try:
        all_names = [str(n) for n in _get(base, "/api/v1/label/__name__/values")]
    except Exception as e:
        print(f"无法连接 Prometheus({base}): {e}")
        return 1

    print(f"已连接 {base}   指标总数 {len(all_names)}")
    cpu_names = {n for n in all_names if "cpu" in n.lower()}
    mem_names = {n for n in all_names if "memory" in n.lower() or "mem" in n.lower()}
    _print_candidates("CPU 候选指标", sorted(cpu_names))
    _print_candidates("内存候选指标", sorted(mem_names))

    print(f"\n用样本服务名 '{sample}' 匹配各标签的值:")
    hits = _find_service_labels(base, sample)
    if hits:
        for key, matched, total in hits:
            print(f"    [命中] {key} = {matched[:5]}   (该标签共 {total} 个值)")
        label_key = hits[0][0]
        print(f"\n→ 服务名最可能挂在标签键: {label_key}")
        if len(hits) > 1:
            print(f"  (另有 {', '.join(k for k, _, _ in hits[1:])} 也命中,按集群实际选更贴切的那个)")
    else:
        label_key = "instance"
        print(f"    [未命中] 没有任何标签的值包含 '{sample}'")
        print("    说明服务名不在指标标签里 —— 可能用 IP:端口 作 instance,或服务名只在日志侧。")
        print("    对策: ① 换一个真实存在的服务名再跑 ② 用 IP/实例名作 {service} 的取值")
        print("          ③ 日志侧的映射交给 SERVICE_ALIASES,指标侧改用 IP 或 pod 名")

    print("\n" + "=" * 68)
    print("建议写入 .env 的模板(确认后替换对应行):")
    print("=" * 68)
    for line in _suggest_templates(cpu_names, mem_names, label_key):
        print(line)
    print("\n提示: {service} 会被 service_map 展开成候选正则,值里不要手写 |")
    print("改完 .env 后: python scripts/probe_real_backends.py 验证取数是否有点")
    return 0


if __name__ == "__main__":
    sys.exit(main())