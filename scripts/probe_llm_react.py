"""手搓一遍 ReAct 闭环:让大模型真的把工具调起来,再用人话总结。

上一个脚本 probe_llm_with_mcp.py 只走到"模型说要调 query_cpu_metrics"就停了——
那只是【意图】(tool_calls),工具还没真的执行。本脚本把缺的半圈补上:
  ① 模型决策 → ② 我们真的执行工具 → ③ 把结果塞回去 → ④ 模型用人话总结
这就是 ReAct(Reason+Act)循环,也是 LangGraph 以后帮我们自动管的事。

核心认知:大模型碰不到任何工具,它只会"说要调啥";真正执行的是我们的代码。
执行完必须按 tool_call_id 把结果配对塞回历史,模型才认得这是哪次调用的回执。

前置:两个 MCP 服务都要起着(8003 日志 + 8004 指标)。
运行: python scripts/probe_llm_react.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 让 "python scripts/xxx.py" 能 import 到 src(把项目根塞进搜索路径)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 让阿里域名绕过本地代理,否则 404
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from src.settings import settings

MCP_SERVERS = {
    "monitor": {"transport": "streamable_http", "url": "http://127.0.0.1:8004/mcp"},
    "cls": {"transport": "streamable_http", "url": "http://127.0.0.1:8003/mcp"},
}

QUESTION = "data-sync-service 这个服务最近 CPU 正常吗?"


async def main():
    # 连上两个 MCP 服务,把工具捞成 LangChain 工具,并建一个 名字→工具 的字典备查
    client = MultiServerMCPClient(MCP_SERVERS)
    tools = await client.get_tools()
    tools_by_name = {t.name: t for t in tools}
    print("=" * 60)
    print(f"捞到 {len(tools)} 个工具:{list(tools_by_name)}")

    llm = ChatOpenAI(
        model=settings.AGENT_MODEL,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.DASHSCOPE_API_BASE,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(tools)

    # messages 是这轮对话的"全部记忆",每一步都往里追加,模型靠它积累上下文
    messages = [HumanMessage(content=QUESTION)]

    # ① 第一轮:模型决策(产出 tool_calls,跟上个脚本一样,只是"动嘴")
    print("=" * 60)
    print(f"提问: {QUESTION}")
    ai_msg = await llm_with_tools.ainvoke(messages)
    messages.append(ai_msg)  # 把模型"我要调啥"的这句话也记进历史

    if not ai_msg.tool_calls:
        print("⚠️ 模型没要调工具,直接回了:", ai_msg.content[:200])
        return

    # ② + ③ 我们替模型【真的执行】每个工具,再把结果按 id 配对塞回历史
    print("=" * 60)
    print("② 开始真的执行模型点名的工具(这一步才真的打到 8004/8003):")
    for tc in ai_msg.tool_calls:
        print(f"   -> 执行 {tc['name']}  参数={tc['args']}")

        # ===== 你来填这两行(本脚本的核心)=====
        # 1) 用 tc['name'] 从 tools_by_name 取出工具,await 它的 .ainvoke(tc['args']),拿到结果
        result = await tools_by_name[tc["name"]].ainvoke(tc["args"])
        # 2) 把结果包成 ToolMessage,带上 tool_call_id=tc['id'](这就是"回执编号"),append 进 messages
        messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        # =====================================

        print(f"      工具返回(节选): {str(result)[:120]}……")

    # ④ 第二轮:带着工具结果再问一次,这次模型说人话
    print("=" * 60)
    print("④ 把数据回填后,模型用人话总结:")
    final = await llm_with_tools.ainvoke(messages)
    print(final.content)


if __name__ == "__main__":
    print("AGENT_MODEL =", settings.AGENT_MODEL)
    asyncio.run(main())
