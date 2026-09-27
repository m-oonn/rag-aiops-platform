"""真实后端连通性探测(Prometheus / Elasticsearch)。

配置完 .env 后先跑这个脚本,确认"地址 / 凭据 / 字段映射"真的通,再把 *_BACKEND
从 mock 切到真实值。本脚本直接复用生产客户端(PrometheusClient / ClsClient),
探的就是 Agent 实跑的那条链路 —— 而不是另写一套 HTTP 逻辑,避免"探测通过、实跑失败"。

特点:
  - URL 已配但开关还是 mock 时**照样探测**,让你能先验证凭据再切开关。
  - 逐层定位:探活 → 真实取数(CPU / 索引 / 日志),失败时给出最可能的排查方向。

运行(必须在项目根目录,否则读不到 .env):
    python scripts/probe_real_backends.py

退出码: 0 = 已配置的后端全部可达;1 = 有后端配置了却不可达。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_servers.cls_client import ClsClient, use_es_backend
from mcp_servers.prometheus_client import PrometheusClient, use_prometheus_backend
from mcp_servers.service_map import load_aliases, resolve_service
from src.settings import settings

# 用来做真实取数验证的样本服务名(改 SERVICE_ALIASES 后这两个应能命中真实索引/实例)
SAMPLE_SERVICES = ("data-sync-service", "order-service")

OK, BAD, SKIP = "[ OK ]", "[FAIL]", "[SKIP]"


def _auth_desc(header_secret: str, username: str) -> str:
    """描述当前鉴权方式(不打印任何凭据内容)。"""
    if header_secret:
        return "Token/ApiKey"
    if username:
        return f"Basic(用户 {username})"
    return "匿名"


def _probe_prometheus() -> bool:
    url = settings.PROMETHEUS_URL.strip()
    if not url:
        print(f"{SKIP} Prometheus: PROMETHEUS_URL 未配置,保持 mock 剧本")
        return True

    print(f"\n── Prometheus ──  {url}")
    print(f"   鉴权: {_auth_desc(settings.PROMETHEUS_BEARER_TOKEN, settings.PROMETHEUS_USERNAME)}"
          f"   TLS 校验: {settings.PROMETHEUS_VERIFY_SSL}"
          f"   超时: {settings.PROMETHEUS_TIMEOUT_SECONDS}s")

    client = PrometheusClient()
    if not client.available:
        print(f"{BAD} 探活失败: GET /api/v1/query?query=up")
        print("       排查: ① URL 是否误带 /api/v1(应只到根)② 端口/网络/防火墙"
              " ③ 凭据是否被拒(401/403) ④ 自签证书需 PROMETHEUS_VERIFY_SSL=False")
        return False
    print(f"{OK} 探活通过: GET /api/v1/query?query=up")

    end = datetime.now()
    start = end - timedelta(minutes=30)
    all_ok = True
    for svc in SAMPLE_SERVICES:
        result = client.query_cpu(svc, start, end, 1)
        points = result.get("data_points") or []
        if points:
            stat = result["statistics"]
            print(f"{OK} CPU 取数 {svc}: {len(points)} 点, 均值 {stat['mean']}%, "
                  f"峰值 {stat['max']}% (告警阈值 {result['alert_info']['threshold']}%)")
        else:
            all_ok = False
            print(f"{BAD} CPU 取数 {svc}: 0 点 {result.get('error', '')}")
            print("       排查: PROMETHEUS_CPU_PROMQL 里的指标名/instance 标签是否与真实环境一致"
                  "(默认模板按 node_exporter 写的)")
            print("       捷径: python scripts/discover_prometheus_metrics.py "
                  f"{svc}   # 自动发现真实指标名与服务名所在标签")
    return all_ok


def _probe_es() -> bool:
    url = settings.CLS_ES_URL.strip()
    if not url:
        print(f"{SKIP} Elasticsearch: CLS_ES_URL 未配置,保持 mock 剧本")
        return True

    print(f"\n── Elasticsearch ──  {url}")
    print(f"   鉴权: {_auth_desc(settings.CLS_ES_API_KEY, settings.CLS_ES_USERNAME)}"
          f"   TLS 校验: {settings.CLS_ES_VERIFY_SSL}"
          f"   超时: {settings.CLS_TIMEOUT_SECONDS}s")
    print(f"   字段映射: 时间={settings.CLS_LOG_TIMESTAMP_FIELD} "
          f"级别={settings.CLS_LOG_LEVEL_FIELD} 内容={settings.CLS_LOG_MESSAGE_FIELD}")

    client = ClsClient()
    if not client.available:
        print(f"{BAD} 探活失败: GET /_cluster/health")
        print("       排查: ① 端口/网络 ② 凭据(401/403,启用安全功能的集群必须带鉴权)"
              " ③ 自签证书需 CLS_ES_VERIFY_SSL=False")
        return False
    print(f"{OK} 探活通过: GET /_cluster/health")

    try:
        indices = client._list_indices()
        preview = ", ".join(indices[:5]) + (" ..." if len(indices) > 5 else "")
        print(f"{OK} 索引可见: {len(indices)} 个" + (f"  例: {preview}" if indices else " (空)"))
    except Exception as e:
        print(f"{BAD} 索引列举失败: GET /_cat/indices → {e}")
        return False

    end_ms = int(datetime.now().timestamp() * 1000)
    start_ms = end_ms - 30 * 60 * 1000
    all_ok = True
    for svc in SAMPLE_SERVICES:
        topics = client.search_topics(svc, fuzzy=True)
        total = topics.get("total", 0)
        if not total:
            all_ok = False
            print(f"{BAD} 服务 {svc}: 未匹配到索引(当前模式 {settings.CLS_INDEX_PATTERN})")
            print("       排查: ① CLS_INDEX_PATTERN 与真实索引命名不符"
                  " ② 服务名对不上真实索引前缀 → 在 SERVICE_ALIASES 里配映射")
            continue
        topic_id = topics["topics"][0]["topic_id"]
        logs = client.search_logs(topic_id, start_ms, end_ms, query=None, limit=5)
        if logs.get("error"):
            all_ok = False
            print(f"{BAD} 服务 {svc}: 命中 {total} 个索引,但查询 {topic_id} 失败: {logs['error']}")
            print("       排查: 索引是否只读/权限不足;时间字段格式是否与 CLS_LOG_TIMESTAMP_FIELD 一致")
            continue
        print(f"{OK} 服务 {svc}: 命中 {total} 个索引,首个 {topic_id} 近 30 分钟取到 "
              f"{logs.get('total', 0)} 条日志")
    return all_ok


def _probe_aliases() -> None:
    table = load_aliases()
    print(f"\n── 服务名别名表 ──  共 {len(table)} 条")
    if not table:
        print(f"{SKIP} SERVICE_ALIASES 为空: 服务名原样透传(零配置可用,"
              "口头名与真实名不一致时才需要配)")
        return
    for spoken in list(table)[:5]:
        print(f"   {spoken}  →  monitor={resolve_service(spoken, 'monitor')}"
              f"  logs={resolve_service(spoken, 'logs')}")


def main() -> int:
    print("=" * 68)
    print("MCP 真实后端连通性探测")
    print("=" * 68)
    print(f"监控后端 MONITOR_BACKEND = {settings.MONITOR_BACKEND:<12} 真实后端已启用: {use_prometheus_backend()}")
    print(f"日志后端 CLS_BACKEND     = {settings.CLS_BACKEND:<12} 真实后端已启用: {use_es_backend()}")

    results = [("Prometheus", _probe_prometheus()), ("Elasticsearch", _probe_es())]
    _probe_aliases()

    configured_but_off = [
        name for name, url, on in (("Prometheus", settings.PROMETHEUS_URL, use_prometheus_backend()),
                                   ("Elasticsearch", settings.CLS_ES_URL, use_es_backend()))
        if url.strip() and not on
    ]

    print("\n" + "=" * 68)
    failed = [name for name, ok in results if not ok]
    if failed:
        print(f"结论: 不可达 → {', '.join(failed)}。修好后再跑一次本脚本。")
        return 1
    print("结论: 已配置的后端全部可达。")
    if configured_but_off:
        print(f"注意: {', '.join(configured_but_off)} 地址已配但开关仍是 mock,"
              "当前 MCP 仍走 mock 剧本;确认无误后把对应 *_BACKEND 改为真实值并重启 MCP 进程。")
    return 0


if __name__ == "__main__":
    sys.exit(main())