"""一次性端到端验证:扮演 Agent,走一遍"两层查日志"的真实排障动作。

链路:get_current_timestamp(锚定时间) → search_topic(服务名找主题)
     → search_log(拿 topic_id 查日志)。这正是 Agent 按顺序串工具的样子。

用法(cls_server 必须已在另一个终端跑着):
    python mcp_servers/try_cls_client.py
"""

import asyncio

from fastmcp import Client

SERVER_URL = "http://127.0.0.1:8003/mcp"


async def main():
    async with Client(SERVER_URL) as client:
        tools = await client.list_tools()
        print("=" * 60)
        print(f"连上了 {SERVER_URL},对面有 {len(tools)} 个工具:")
        for t in tools:
            print(f"  - {t.name}")

        # 第一层:服务名 → topic
        print("=" * 60)
        print("① search_topic_by_service_name(service_name='data-sync') ...")
        topic_res = (await client.call_tool(
            "search_topic_by_service_name", {"service_name": "data-sync"})).data
        print(f"  命中 {topic_res['total']} 个主题")
        topic_id = topic_res["topics"][0]["topic_id"]
        print(f"  取第一个 topic_id = {topic_id}")

        # 锚定时间窗:最近 15 分钟
        now = (await client.call_tool("get_current_timestamp", {})).data
        start = now - 15 * 60 * 1000

        # 第二层:拿 topic_id 查日志
        print("=" * 60)
        print(f"② search_log(topic_id='{topic_id}', 最近15分钟) ...")
        log_res = (await client.call_tool("search_log", {
            "topic_id": topic_id, "start_time": start, "end_time": now})).data
        print(f"  查到 {log_res['total']} 条日志")
        print(f"  首条: {log_res['logs'][0] if log_res['logs'] else '无'}")
        levels = {lg["level"] for lg in log_res["logs"]}
        print(f"  出现的日志级别: {levels}  ← 全是 INFO,没有 ERROR(故意埋的死胡同)")


if __name__ == "__main__":
    asyncio.run(main())
