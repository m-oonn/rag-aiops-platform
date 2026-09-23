"""探测 settings.AVAILABLE_MODELS 中所有模型的可用性与 function calling 支持。

运行: python scripts/probe_available_models.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 让脚本无论从哪运行都能找到 src
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 让访问阿里时绕过本地代理
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com,deepseek.com"

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.settings import settings


@tool
def get_weather(city: str) -> str:
    """查询某个城市的天气。"""
    return f"{city} 晴 25 度"


async def probe(model_name: str, display_name: str) -> dict:
    """对单个模型做最小调用,返回可用性信息。"""
    result = {
        "model": model_name,
        "display": display_name,
        "chat_ok": False,
        "tool_ok": False,
        "error": None,
        "tool_calls": [],
        "content_sample": "",
    }
    print(f"\n{'=' * 60}\n探测模型: {display_name} ({model_name})\n{'=' * 60}")

    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,
            temperature=0,
        )

        # 1. 基础对话
        try:
            resp = await llm.ainvoke("你好，用一句话回答。")
            result["chat_ok"] = True
            result["content_sample"] = getattr(resp, "content", "")[:80]
            print(f"  ✅ 对话可用 | {result['content_sample']}")
        except Exception as e:
            result["error"] = f"对话失败: {type(e).__name__}: {e}"
            print(f"  ❌ {result['error']}")
            return result

        # 2. function calling
        try:
            llm_with_tools = llm.bind_tools([get_weather])
            resp = await llm_with_tools.ainvoke("北京今天天气怎么样?")
            tool_calls = getattr(resp, "tool_calls", None) or []
            if tool_calls:
                result["tool_ok"] = True
                result["tool_calls"] = [
                    {"name": tc.get("name"), "args": tc.get("args")} for tc in tool_calls
                ]
                print(f"  ✅ function_calling 可用 | tool={tool_calls[0]['name']} args={tool_calls[0]['args']}")
            else:
                result["error"] = "未返回 tool_calls"
                print(f"  ⚠️  可调对话,但未返回 tool_calls | {getattr(resp, 'content', '')[:80]}")
        except Exception as e:
            result["error"] = f"function_calling 失败: {type(e).__name__}: {e}"
            print(f"  ❌ {result['error']}")

    except Exception as e:
        result["error"] = f"初始化失败: {type(e).__name__}: {e}"
        print(f"  ❌ {result['error']}")

    return result


async def main() -> None:
    print("base_url =", settings.DASHSCOPE_API_BASE)
    print("api_key 是否存在 =", bool(settings.DASHSCOPE_API_KEY))

    models = settings.AVAILABLE_MODELS.split(",")
    displays = settings.MODEL_DISPLAY_NAMES.split(",")
    if len(models) != len(displays):
        displays = models

    results = []
    for name, disp in zip(models, displays):
        name = name.strip()
        disp = disp.strip()
        if not name:
            continue
        r = await probe(name, disp)
        results.append(r)

    # 汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    agent_ok = [r for r in results if r["chat_ok"] and r["tool_ok"]]
    chat_only = [r for r in results if r["chat_ok"] and not r["tool_ok"]]
    failed = [r for r in results if not r["chat_ok"]]

    print("\n✅ 推荐用于 Agent(支持 function calling):")
    for r in agent_ok:
        print(f"   - {r['display']} ({r['model']})")

    print("\n⚠️  仅推荐用于 RAG/闲聊(不支持 function calling):")
    for r in chat_only:
        print(f"   - {r['display']} ({r['model']}) | {r['error']}")

    print("\n❌ 不可用:")
    for r in failed:
        print(f"   - {r['display']} ({r['model']}) | {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
