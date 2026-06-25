"""一次性的端到端验证脚本:扮演"Agent",通过网络连到 monitor_server 调一次工具。

它要证明的事:工具不在本进程里,而是另一个跑在 127.0.0.1:8004 的独立服务。
我们这边只知道一个 URL,连过去、列工具、喊一声,拿回结果——这就是 Agent 用工具的本质。

用法(monitor_server 必须已经在另一个终端跑着):
    python mcp_servers/try_client.py
"""

import asyncio

from fastmcp import Client

# 注意:这里只有一个地址,没有 import 任何 monitor_server 的代码。
# 我们对工具内部一无所知——它怎么算 CPU、mock 还是真实,全不关心。这就是"解耦"。
SERVER_URL = "http://127.0.0.1:8004/mcp"


async def main():
    # Client(URL) = 通过网络连到那个独立进程,不是函数调用
    async with Client(SERVER_URL) as client:
        # 1) 问它:你都有哪些工具?(Agent 启动时就是这样"发现"工具的)
        tools = await client.list_tools()
        print("=" * 60)
        print(f"连上了 {SERVER_URL}")
        print(f"对面暴露了 {len(tools)} 个工具:")
        for t in tools:
            print(f"  - {t.name}: {t.description.splitlines()[0]}")

        # 2) 真的喊一声 query_cpu_metrics(参数通过网络传过去)
        print("=" * 60)
        print("调用 query_cpu_metrics(service_name='data-sync-service') ...")
        result = await client.call_tool(
            "query_cpu_metrics",
            {"service_name": "data-sync-service"},
        )
        data = result.data
        print(f"  峰值 CPU: {data['statistics']['max']}%")
        print(f"  是否告警: {data['alert_info']['triggered']}")
        print(f"  告警信息: {data['alert_info']['message']}")
        print(f"  数据点数: {len(data['data_points'])}")


if __name__ == "__main__":
    asyncio.run(main())
