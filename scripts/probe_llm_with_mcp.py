"""最小连通测试:让大模型自己从【真·MCP 工具】里挑一个来调。

与 scripts/probe_llm.py 的区别:
  探针用的是写死在脚本里的假 get_weather;
  这里的工具来自两个真实运行的 MCP 服务(8003 日志 + 8004 指标),
  而且【没有任何 if-else】告诉大模型该调谁 —— 它看着工具清单自己决定。
这就是 RAG(流程写死)和 Agent(模型自主决策)的分界线。

前置:必须先在两个终端分别起好
    python mcp_servers/monitor_server.py   # 8004
    python mcp_servers/cls_server.py       # 8003

运行: python scripts/probe_llm_with_mcp.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 让 "python scripts/xxx.py" 能 import 到 src:把项目根(本文件的上一级)塞进搜索路径。
# 否则 Python 只在 scripts/ 里找,找不到它的兄弟目录 src/。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 与探针一致:让阿里域名绕过本地代理,否则 404
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from src.settings import settings

# 两个 MCP 服务的地址(本地 FastMCP 用 streamable_http)
MCP_SERVERS = {
    "monitor": {"transport": "streamable_http", "url": "http://127.0.0.1:8004/mcp"},
    "cls": {"transport": "streamable_http", "url": "http://127.0.0.1:8003/mcp"},
}

# 故意用大白话,不点名工具,看模型能不能自己对应到 query_cpu_metrics
QUESTION = "data-sync-service 这个服务最近 CPU 正常吗?"


async def main():
    # 1) 连上两个 MCP 服务,把它们暴露的工具全捞成 LangChain 工具
    client = MultiServerMCPClient(MCP_SERVERS)
    tools = await client.get_tools()
    print("=" * 60)
    print(f"从 2 个 MCP 服务捞到 {len(tools)} 个工具,交给大模型挑:")
    for t in tools:
        print(f"  - {t.name}")

    # 2) 把工具绑给大模型(deepseek-v3,走 compatible-mode)
    llm = ChatOpenAI(
        model=settings.AGENT_MODEL,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.DASHSCOPE_API_BASE,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(tools)

    # 3) 问一句大白话,看模型【自己】决定调哪个工具
    print("=" * 60)
    print(f"提问: {QUESTION}")
    resp = await llm_with_tools.ainvoke(QUESTION)

    if resp.tool_calls:
        print("✅ 大模型自主决定调用工具(没有任何 if-else):")
        for tc in resp.tool_calls:
            print(f"   -> 工具={tc['name']}  参数={tc['args']}")
    else:
        print("⚠️  模型没返回 tool_calls,直接回了文本:")
        print(f"   {resp.content[:200]}")


if __name__ == "__main__":
    print("AGENT_MODEL =", settings.AGENT_MODEL)
    print("api_key 存在 =", bool(settings.DASHSCOPE_API_KEY))
    asyncio.run(main())
