"""端到端验证: 通过 MCP 协议调 monitor / cls 两个服务,确认走的是真实后端。

与 probe_real_backends.py 的区别:
  probe 直接 import 客户端类,验的是"客户端能不能连上后端";
  本脚本走 HTTP + MCP 协议,验的是"Agent 实际那条链路"——
  独立进程、工具发现、参数序列化、返回值结构,全都要对。

前置: 两个 MCP 服务已在跑
    python mcp_servers/monitor_server.py    # 8104
    python mcp_servers/cls_server.py        # 8103
且 .env 里 MONITOR_BACKEND=prometheus / CLS_BACKEND=elasticsearch

用法: python scripts/verify_mcp_e2e.py
"""

import asyncio
import sys

from fastmcp import Client

MONITOR_URL = "http://127.0.0.1:8104/mcp"
CLS_URL = "http://127.0.0.1:8103/mcp"
SERVICES = ("data-sync-service", "order-service")

_failures: list[str] = []


def _check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'[ OK ]' if ok else '[FAIL]'} {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


async def _verify_monitor() -> None:
    print(f"\n── monitor_server {MONITOR_URL} ──")
    async with Client(MONITOR_URL) as client:
        tools = await client.list_tools()
        _check(len(tools) > 0, "工具发现", f"{len(tools)} 个: {', '.join(t.name for t in tools)}")

        for svc in SERVICES:
            for tool, metric in (("query_cpu_metrics", "CPU"), ("query_memory_metrics", "内存")):
                r = await client.call_tool(tool, {"service_name": svc})
                d = r.data
                pts = d.get("data_points") or []
                stat = d.get("statistics") or {}
                real = d.get("scenario") == "prometheus"
                _check(bool(pts), f"{svc} {metric}取数", f"{len(pts)} 点")
                _check(real, f"{svc} {metric}走真实后端", f"scenario={d.get('scenario')}")
                if pts:
                    vals = [p["value"] for p in pts]
                    in_range = all(0 <= v <= 100 for v in vals)
                    _check(in_range, f"{svc} {metric}数值在 0~100",
                           f"均值 {stat.get('mean')}% 峰值 {stat.get('max')}%")
                else:
                    print(f"        error={d.get('error', '(无)')}")


async def _verify_cls() -> None:
    print(f"\n── cls_server {CLS_URL} ──")
    async with Client(CLS_URL) as client:
        tools = await client.list_tools()
        _check(len(tools) > 0, "工具发现", f"{len(tools)} 个: {', '.join(t.name for t in tools)}")

        ts = (await client.call_tool("get_current_timestamp", {})).data
        _check(isinstance(ts, int) and ts > 1_600_000_000_000, "get_current_timestamp", str(ts))

        for svc in SERVICES:
            topics = (await client.call_tool(
                "search_topic_by_service_name", {"service_name": svc})).data
            total = topics.get("total", 0)
            _check(total > 0, f"{svc} 命中日志主题", f"{total} 个")
            if not total:
                continue
            topic_id = topics["topics"][0]["topic_id"]
            print(f"        首个主题: {topic_id}")

            logs = (await client.call_tool("search_log", {
                "topic_id": topic_id,
                "start_time": ts - 30 * 60 * 1000,
                "end_time": ts,
            })).data
            rows = logs.get("logs") or []
            _check(bool(rows), f"{svc} 取到日志", f"{logs.get('total', 0)} 条")
            _check(not logs.get("error"), f"{svc} 日志无错误", str(logs.get("error", "")))
            for row in rows[:2]:
                print(f"        {row['timestamp']} [{row['level']}] {row['message'][:70]}")


async def main() -> int:
    print("=" * 68)
    print("MCP 端到端验证(HTTP + MCP 协议)")
    print("=" * 68)
    await _verify_monitor()
    await _verify_cls()
    print("\n" + "=" * 68)
    if _failures:
        print(f"结论: {len(_failures)} 项未通过 → {', '.join(_failures)}")
        return 1
    print("结论: 指标链路 + 日志链路全部通过(真实后端)。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))