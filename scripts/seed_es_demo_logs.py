"""向 Elasticsearch 灌入演示日志,让真实日志链路(索引匹配 + 字段映射)可验证。

为什么需要它: ES 刚起来时是空的,而 cls_server 的真实路径只在**不可达**时回退 mock;
索引存在但查不到数据属于"正常返回空",不会回退 —— 所以必须先把数据灌进去,
search_topic_by_service_name → search_log 两层链路才跑得出东西。

样本日志与 mock 剧本语义对齐:
  - data-sync-service: 全 INFO(指标异常但日志正常 → 逼 Agent 重新规划)
  - order-service:     OOM 堆栈(应用根因,鉴别证据在日志)

运行(先在 .env 里把 CLS_ES_URL 指向目标 ES):
    python scripts/seed_es_demo_logs.py

幂等: 每次先删索引再重建,重复运行不会累积重复文档。
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_servers.cls_client import ClsClient
from src.settings import settings

SAMPLE_LOGS = {
    "data-sync-service": [
        ("INFO", "数据同步任务已启动, 批大小 500"),
        ("INFO", "同步批次 #1024 完成, 耗时 1.2s"),
        ("INFO", "增量位点已提交, offset=884213"),
    ],
    "order-service": [
        ("WARN", "GC overhead limit exceeded, 单次 GC 停顿 3.2s"),
        ("ERROR", "java.lang.OutOfMemoryError: Java heap space"),
        ("ERROR", "at com.example.order.OrderIndex.rebuild(OrderIndex.java:88)"),
    ],
}


def _index_name(service: str) -> str:
    """按 CLS_INDEX_PATTERN 生成具体索引名(通配符 * 用当天日期替换)。"""
    pattern = settings.CLS_INDEX_PATTERN.format(service=service)
    return pattern.replace("*", datetime.now(timezone.utc).strftime("%Y.%m.%d"))


def main() -> int:
    if not settings.CLS_ES_URL.strip():
        print("CLS_ES_URL 未配置,请先在 .env 填写目标 ES 地址")
        return 1

    # 复用生产客户端的探活与鉴权/TLS 参数,保证灌数据与查询走同一套凭据
    client = ClsClient()
    if not client.available:
        print(f"ES 不可达: {settings.CLS_ES_URL}")
        print("  先启动: docker compose -f docker/docker-compose.observability.yml up -d")
        return 1

    common = client._request_kwargs()
    auth_headers = common.pop("headers", {})
    base = client.base_url
    ts_field = settings.CLS_LOG_TIMESTAMP_FIELD
    level_field = settings.CLS_LOG_LEVEL_FIELD
    msg_field = settings.CLS_LOG_MESSAGE_FIELD

    # 必须用 UTC: 下面 strftime 打的是 "Z" 后缀,若取本地时间会变成"未来 8 小时",
    # 探测脚本按真实 UTC 取"近 30 分钟"就一条都查不到
    now = datetime.now(timezone.utc)
    for service, lines in SAMPLE_LOGS.items():
        index = _index_name(service)
        requests.delete(f"{base}/{index}", timeout=10, **common)
        created = requests.put(f"{base}/{index}", timeout=10, **common)
        if created.status_code >= 400:
            print(f"建索引失败 {index}: HTTP {created.status_code} {created.text[:200]}")
            return 1

        body = ""
        for i, (level, message) in enumerate(lines):
            ts = (now - timedelta(minutes=len(lines) - i)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            body += json.dumps({"index": {"_index": index}}) + "\n"
            body += json.dumps({ts_field: ts, level_field: level, msg_field: message},
                               ensure_ascii=False) + "\n"

        resp = requests.post(f"{base}/_bulk", params={"refresh": "true"},
                             data=body.encode("utf-8"),
                             headers={"Content-Type": "application/x-ndjson", **auth_headers},
                             timeout=15, **common)
        if resp.status_code >= 400:
            print(f"写入失败 {index}: HTTP {resp.status_code} {resp.text[:200]}")
            return 1
        errors = resp.json().get("errors")
        if errors:
            print(f"写入 {index} 存在失败项,请检查字段映射({ts_field}/{level_field}/{msg_field})")
            return 1
        print(f"[ OK ] {index}: 写入 {len(lines)} 条日志")

    print("\n完成。验证: python scripts/probe_real_backends.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())