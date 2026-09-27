"""服务名别名解析(口头名 ↔ 监控 instance 前缀 ↔ 日志索引前缀)。

背景(见 settings.SERVICE_ALIASES 注释):
  "用户说订单服务,监控叫 order-svc,索引叫 order-service-logs-*" ——
  双轨真实路径(Prometheus / Elasticsearch)若直接拿口头名去查,必然检索落空。
  本模块在真实查询前把服务名**归一化**并**展开候选**,让三个命名空间对齐。

别名表格式(settings.SERVICE_ALIASES,JSON 字符串):
  {"口头服务名": {"monitor": "监控instance前缀", "logs": "日志索引前缀"}}
其中每个后端的值可以是单个字符串,也可以是字符串数组(用于"一个口头名对应
多个真实名"的展开,如新旧实例并存):
  {"订单服务": {"monitor": ["order-svc", "order-service"],
                "logs": ["order-service-logs-*", "order-api-logs-*"]}}

用法(真实后端查询前):
  from mcp_servers.service_map import resolve_service
  resolve_service("订单服务", "monitor")   # → ["order-svc", "order-service"]
  resolve_service("order-svc", "logs")     # → ["order-service-logs-*", ...]  (跨命名空间也能定位)
  resolve_service("data-sync-service", "monitor")  # → ["data-sync-service"]  (未配别名时原样返回)

设计取舍:
  - 输入可以是口头名、监控名或日志名任一种,都能定位到同一条记录(双向查找),
    避免"LLM 拿监控名去查日志"这类跨命名空间落空。
  - 别名表是人工编辑的配置,解析失败只告警不抛异常 —— 不能让一个 JSON 手误把
    MCP 服务整体打挂;未配别名时原样返回输入,保持"零配置可用"。
  - backend 取值错误属于编程错误,直接抛 ValueError(调用方只有两个,写错立刻暴露)。
"""

import json
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from src.settings import settings

logger = logging.getLogger("Service_Map")

# 支持的后端命名空间(与 settings.SERVICE_ALIASES 的 value 键名一致)
ALIAS_BACKENDS = ("monitor", "logs")


def _as_list(value: Any) -> List[str]:
    """把别名值规整成非空字符串列表(支持字符串或数组两种写法)。"""
    if isinstance(value, str):
        items: List[Any] = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    return [str(v).strip() for v in items if str(v).strip()]


@lru_cache(maxsize=8)
def _parse_aliases(raw: str) -> Dict[str, Dict[str, List[str]]]:
    """解析别名表 JSON。失败只告警并返回空表(配置手误不应打挂服务)。"""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("SERVICE_ALIASES 不是合法 JSON,已忽略: %s", e)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("SERVICE_ALIASES 应为对象(口头名 → {backend: 名称}),实际为 %s,已忽略",
                       type(parsed).__name__)
        return {}

    table: Dict[str, Dict[str, List[str]]] = {}
    for spoken, mapping in parsed.items():
        if not isinstance(mapping, dict):
            logger.warning("SERVICE_ALIASES['%s'] 应为对象,已忽略该项", spoken)
            continue
        entry = {backend: names for backend in ALIAS_BACKENDS
                 if (names := _as_list(mapping.get(backend)))}
        if entry:
            table[str(spoken).strip()] = entry
    return table


def load_aliases() -> Dict[str, Dict[str, List[str]]]:
    """返回当前生效的别名表(排查"配置是否被读到"时用)。"""
    return _parse_aliases(settings.SERVICE_ALIASES)


def _match_entry(service_name: str,
                 table: Dict[str, Dict[str, List[str]]]) -> Optional[Tuple[str, Dict[str, List[str]]]]:
    """用 口头名/监控名/日志名 任一种输入定位别名记录;多个命中取最具体者。

    打分规则:完全相等优先(1000 + 长度),其次取"被匹配到的那个名字"最长者
    —— 名字越长越具体,避免 "order" 这种短前缀把 "order-svc" 的记录抢走。
    """
    needle = service_name.strip().lower()
    if not needle:
        return None

    best: Optional[Tuple[str, Dict[str, List[str]]]] = None
    best_score = -1
    for spoken, entry in table.items():
        all_names = [spoken, *(name for names in entry.values() for name in names)]
        for name in all_names:
            low = name.strip().lower()
            if not low:
                continue
            if low == needle:
                score = 1000 + len(low)
            elif needle in low or low in needle:
                score = len(low)
            else:
                continue
            if score > best_score:
                best, best_score = (spoken, entry), score
    return best


def resolve_service(service_name: str, backend: str) -> List[str]:
    """把服务名归一化并展开成该后端下的候选名列表。

    Args:
        service_name: 任意命名空间下的服务名(口头名 / 监控名 / 日志索引名均可)。
        backend: "monitor"(Prometheus instance 前缀)或 "logs"(ES 索引前缀)。

    Returns:
        候选名列表,index 0 最具体。命中别名时返回别名表里该 backend 的候选;
        未命中(未配别名)时原样返回输入,保证零配置可用。已去重。
    """
    if backend not in ALIAS_BACKENDS:
        raise ValueError(f"backend 必须是 {ALIAS_BACKENDS} 之一,收到: {backend!r}")

    raw = (service_name or "").strip()
    match = _match_entry(raw, load_aliases())
    candidates = list(match[1].get(backend, [])) if match else []
    if not candidates and raw:
        candidates = [raw]

    deduped: List[str] = []
    for name in candidates:
        if name not in deduped:
            deduped.append(name)
    return deduped