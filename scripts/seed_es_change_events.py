"""向 Elasticsearch 灌入演示变更事件,让真实变更链路(索引 + 字段映射 + 时间对齐)可验证。

为什么需要它: ES 刚起来时是空的,而 change_server 的真实路径只在**不可达**时返回
"不可用";索引存在但查不到数据属于"正常返回空",不会回退 —— 所以必须先把数据灌进去,
search_changes 才跑得出东西。

样本与现有日志剧本语义对齐(便于演示"指标异常 + 日志 OOM + 变更事件"三证据相撞):
  - order-service:  一条**近期**配置变更(索引重建/JVM 堆参数调整)—— 与 order-service
                    的 OOM 日志、内存飙升指标时间对齐,是根因链首的触发事件;
  - order-service:  一条**较早**发布(3 天前,落在查询窗口外)—— 用于验证时间窗过滤;
  - data-sync-service: 仅一条较早扩缩容(窗口外)—— 用于验证"窗口内无变更"分支。

运行(先在 .env 里把 CLS_ES_URL 指向目标 ES;CHANGE_ES_URL 留空即复用同集群):
    python scripts/seed_es_change_events.py

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

from mcp_servers.change_client import ChangeClient
from src.settings import settings

# (service, change_type, change_id, operator, version, status, description, minutes_ago)
SAMPLE_CHANGES = [
    ("order-service", "config", "chg-order-20261010-001", "release-bot", "v2.3.1", "success",
     "订单服务索引重建: 调整 JVM 堆参数(-Xmx 2g→1g)并触发 order 索引全量重建", 2),
    ("order-service", "deploy", "chg-order-20261007-014", "release-bot", "v2.2.9", "success",
     "订单服务常规版本发布: 无结构性变更", 3 * 24 * 60),
    ("data-sync-service", "scale", "chg-sync-20261008-003", "ops-admin", "-", "success",
     "数据同步服务扩容: 副本数 2→3", 2 * 24 * 60),
]

# 显式 mapping: service/change_type 等定义为 keyword,保证 match_phrase/term 检索稳定命中
_MAPPING = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "service": {"type": "keyword"},
            "change_id": {"type": "keyword"},
            "change_type": {"type": "keyword"},
            "operator": {"type": "keyword"},
            "version": {"type": "keyword"},
            "status": {"type": "keyword"},
            "description": {"type": "text"},
        }
    }
}


def _index_name() -> str:
    """按 CHANGE_INDEX_PATTERN 生成具体索引名(通配符 * 用当天日期替换)。"""
    pattern = settings.CHANGE_INDEX_PATTERN
    return pattern.replace("*", datetime.now(timezone.utc).strftime("%Y.%m.%d"))


def main() -> int:
    if not settings.RESOLVED_CHANGE_ES_URL.strip():
        print("CHANGE_ES_URL / CLS_ES_URL 均未配置,请先在 .env 填写目标 ES 地址")
        return 1

    # 复用生产客户端的探活与鉴权/TLS 参数,保证灌数据与查询走同一套凭据
    client = ChangeClient()
    if not client.available:
        print(f"ES 不可达: {settings.RESOLVED_CHANGE_ES_URL}")
        print("  先启动: docker compose -f docker/docker-compose.observability.yml up -d")
        return 1

    common = client._request_kwargs()
    auth_headers = common.pop("headers", {})
    base = client.base_url
    index = _index_name()

    requests.delete(f"{base}/{index}", timeout=10, **common)
    created = requests.put(f"{base}/{index}", json=_MAPPING, timeout=10, **common)
    if created.status_code >= 400:
        print(f"建索引失败 {index}: HTTP {created.status_code} {created.text[:200]}")
        return 1

    # 必须用 UTC: 下面 strftime 打的是 "Z" 后缀,若取本地时间会变成"未来 8 小时",
    # 查询按真实 UTC 取"近 30 分钟"就一条都查不到
    now = datetime.now(timezone.utc)
    body = ""
    for svc, ctype, cid, operator, version, status, desc, minutes_ago in SAMPLE_CHANGES:
        ts = (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body += json.dumps({"index": {"_index": index}}) + "\n"
        body += json.dumps({
            "@timestamp": ts, "service": svc, "change_id": cid, "change_type": ctype,
            "operator": operator, "version": version, "status": status, "description": desc,
        }, ensure_ascii=False) + "\n"

    resp = requests.post(f"{base}/_bulk", params={"refresh": "true"},
                         data=body.encode("utf-8"),
                         headers={"Content-Type": "application/x-ndjson", **auth_headers},
                         timeout=15, **common)
    if resp.status_code >= 400:
        print(f"写入失败 {index}: HTTP {resp.status_code} {resp.text[:200]}")
        return 1
    if resp.json().get("errors"):
        print(f"写入 {index} 存在失败项,请检查字段映射")
        return 1
    print(f"[ OK ] {index}: 写入 {len(SAMPLE_CHANGES)} 条变更事件")
    print("\n完成。验证: python scripts/seed_es_change_events.py 后可直接调 change_server 查询")
    return 0


if __name__ == "__main__":
    sys.exit(main())