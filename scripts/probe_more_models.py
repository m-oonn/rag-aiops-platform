"""扩展探测百炼模型：覆盖 AVAILABLE_MODELS 之外的常见文本模型。

对每个模型做最小调用(对话 + function calling),输出可用矩阵。
用法: .\.venv\Scripts\python.exe scripts/probe_more_models.py
"""
import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com,deepseek.com"

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.settings import settings


@tool
def get_weather(city: str) -> str:
    """查询某个城市的天气。"""
    return f"{city} 晴 25 度"


# 百炼常见文本模型候选(官方商业名 + 常见托管名),按可探测性排序
MODEL_CANDIDATES: list[tuple[str, str]] = [
    # qwen3 系列(2025 新架构)
    ("qwen3", "Qwen3(旗舰)"),
    ("qwen3-flash", "Qwen3-Flash"),
    ("qwen3-turbo", "Qwen3-Turbo"),
    ("qwen3-plus", "Qwen3-Plus"),
    ("qwen3-max", "Qwen3-Max"),
    ("qwen3-235b-a22b-instruct", "Qwen3-235B-A22B"),
    ("qwen3-32b", "Qwen3-32B"),
    ("qwen3-30b-a3b-instruct", "Qwen3-30B-A3B"),
    ("qwen3-moe-60b", "Qwen3-MoE-60B"),
    # qwen2.5 系列(托管开放模型)
    ("qwen2.5-72b-instruct", "Qwen2.5-72B"),
    ("qwen2.5-32b-instruct", "Qwen2.5-32B"),
    ("qwen2.5-14b-instruct", "Qwen2.5-14B"),
    ("qwen2.5-7b-instruct", "Qwen2.5-7B"),
    ("qwen2-57b-a14b-instruct", "Qwen2-57B-A14B"),
    # 商业版(非 thinking)
    ("qwen-plus", "Qwen-Plus 最新"),
    ("qwen-turbo", "Qwen-Turbo 最新"),
    ("qwen-max", "Qwen-Max 最新"),
    ("qwen-long", "Qwen-Long(长文本)"),
    # 时间戳版本
    ("qwen-plus-2025-07-28", "Qwen-Plus 0728"),
    ("qwen-turbo-2025-10-31", "Qwen-Turbo 1031"),
    ("qwen-max-2025-08-21", "Qwen-Max 0821"),
    # deepseek / glm / kimi / hunyuan / minimax / baichuan
    ("deepseek-v3.1", "DeepSeek-V3.1"),
    ("deepseek-r1", "DeepSeek-R1"),
    ("deepseek-r1-distill-qwen-32b", "DeepSeek-R1-32B"),
    ("deepseek-r1-distill-qwen-14b", "DeepSeek-R1-14B"),
    ("glm-4-plus", "GLM-4-Plus"),
    ("glm-4-flash", "GLM-4-Flash"),
    ("glm-z1-plus", "GLM-Z1-Plus"),
    ("glm-4.5", "GLM-4.5"),
    ("kimi-k2-0905", "Kimi-K2-0905"),
    ("kimi-k2-turbo-preview", "Kimi-K2-Turbo"),
    ("moonshot-v1-8k", "Moonshot-V1-8K"),
    ("moonshot-v1-32k", "Moonshot-V1-32K"),
    ("hunyuan-turbos-latest", "混元 TurboS"),
    ("hunyuan-t1-latest", "混元 T1"),
    ("minimax-text-01", "MiniMax-Text-01"),
    ("abab6.5s-chat", "ABAB6.5S"),
    ("baichuan-4", "百川 4"),
]


async def probe(model_name: str, display_name: str) -> dict:
    result = {"model": model_name, "display": display_name,
              "chat_ok": False, "tool_ok": False, "error": None}
    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,
            temperature=0,
        )
        resp = await llm.ainvoke("你好，用一句话回答。")
        result["chat_ok"] = True
        sample = getattr(resp, "content", "")[:60]
        try:
            r2 = await llm.bind_tools([get_weather]).ainvoke("北京今天天气怎么样?")
            tc = getattr(r2, "tool_calls", None) or []
            result["tool_ok"] = bool(tc)
        except Exception as e:
            result["error"] = f"tool: {type(e).__name__}"
        print(f"  {'✅' if result['chat_ok'] else '❌'} {display_name:<22} ({model_name}) | chat={'✅' if result['chat_ok'] else '❌'} tool={'✅' if result['tool_ok'] else '❌'} {sample} {result['error'] or ''}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}"
        msg = str(e)
        if "FreeTierOnly" in msg or "free tier" in msg.lower():
            result["error"] = "FreeTierOnly(免费额度耗尽)"
        print(f"  ❌ {display_name:<22} ({model_name}) | {result['error']}")
    return result


async def main() -> None:
    print("base_url =", settings.DASHSCOPE_API_BASE)
    print("api_key 是否存在 =", bool(settings.DASHSCOPE_API_KEY))
    print(f"待探测 {len(MODEL_CANDIDATES)} 个模型\n" + "=" * 78)
    results = [await probe(n, d) for n, d in MODEL_CANDIDATES]

    agent_ok = [r for r in results if r["chat_ok"] and r["tool_ok"]]
    chat_only = [r for r in results if r["chat_ok"] and not r["tool_ok"]]
    failed = [r for r in results if not r["chat_ok"]]

    print("\n" + "=" * 78)
    print(f"汇总: 共 {len(results)}  |  Agent可用(function calling) {len(agent_ok)}  |  仅对话 {len(chat_only)}  |  失败 {len(failed)}")
    print("\n✅ 推荐用于 Agent(支持 function calling):")
    for r in agent_ok:
        print(f"   - {r['display']} ({r['model']})")
    print("\n⚠️  仅对话(不支持 function calling):")
    for r in chat_only:
        print(f"   - {r['display']} ({r['model']})")
    print("\n❌ 不可用:")
    for r in failed:
        print(f"   - {r['display']} ({r['model']}) | {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
