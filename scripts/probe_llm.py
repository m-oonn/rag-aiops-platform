"""Phase 0 探针: 验证「单一 provider 一致性」方案是否成立。

目的(一举三得):
1. 验证用 langchain-openai 的 ChatOpenAI + DashScope compatible-mode,
   能否同时调通 qwen-max 和 deepseek 模型(同一个类/key/base_url)。
2. 验证 DeepSeek 模型在阿里百炼上的确切模型名(逐个试,服务器说了算)。
3. 验证 bind_tools(function calling)是否真能让模型返回结构化的 tool_calls。

运行: python scripts/probe_llm.py
不改任何业务代码,纯验证脚本。
"""

import os

# 让访问阿里(及 DeepSeek)时绕过本地代理: 把这些域名加进 NO_PROXY。
# 诊断已确认: 本地代理(127.0.0.1:15721)不转发阿里域名,会 404。
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com,deepseek.com"

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.settings import settings


@tool
def get_weather(city: str) -> str:
    """查询某个城市的天气。"""
    return f"{city} 晴 25 度"


def probe(model_name: str) -> None:
    """对单个模型名做一次「带工具」的最小调用,打印它是否返回 tool_calls。"""
    print(f"\n{'=' * 60}\n探测模型: {model_name}\n{'=' * 60}")
    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,  # 单一事实来源: 上一步配的
            temperature=0,
        )
        llm_with_tools = llm.bind_tools([get_weather])
        resp = llm_with_tools.invoke("北京今天天气怎么样?")

        tool_calls = getattr(resp, "tool_calls", None)
        if tool_calls:
            print("✅ 模型可用, 且成功返回 tool_calls(function calling 生效):")
            for tc in tool_calls:
                print(f"   -> 工具={tc['name']}  参数={tc['args']}")
        else:
            print("⚠️  模型可调, 但没返回 tool_calls(可能不支持/未触发):")
            print(f"   文本输出: {resp.content[:120]}")
    except Exception as e:
        print(f"❌ 失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("base_url =", settings.DASHSCOPE_API_BASE)
    print("api_key 是否存在 =", bool(settings.DASHSCOPE_API_KEY))

    # 逐个试: 服务器接受哪个名字, 哪个就是对的
    for name in ["qwen-max", "deepseek-v3", "deepseek-chat", "deepseek-r1"]:
        probe(name)
