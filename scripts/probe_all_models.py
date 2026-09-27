"""全量探测百炼(DashScope)账号下所有模型: 可用性 + 免费额度状态。

与另两个探针的区别:
  probe_available_models.py  只测 settings.AVAILABLE_MODELS 里那几个(白名单)
  probe_more_models.py       硬编码 ~36 个候选名
  本脚本                     先调 /compatible-mode/v1/models 拉账号可见的**全量**
                             模型,再逐个最小调用探测,所以"有多少免费模型"这个问题
                             只有它能答。

用法:
    python scripts/probe_all_models.py              # 对话可用性 + 免费额度
    python scripts/probe_all_models.py --fc         # 额外测 function calling(翻倍调用量)
    python scripts/probe_all_models.py --concurrency 8

判读:
    FreeTierOnly / 403   → 免费额度已耗尽(有权限但要计费),脚本归到"耗尽"
    404 / Model not exist → 账号不可见或型号名不对
    对话 OK 且未报 403    → 计为"免费可用"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 访问阿里时绕过本地代理(与其它探针保持一致)
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.settings import settings


@tool
def get_weather(city: str) -> str:
    """查询某个城市的天气。"""
    return f"{city} 晴 25 度"


# 非对话模型: 用 chat 探针测它们只会得到假阴性,单独归类
# "realtime" 也算: 它们走 WebSocket 双工协议,不是对话模型,由 probe_realtime_models.py 负责
_NON_CHAT_HINTS = ("embedding", "rerank", "asr", "tts", "speech", "audio", "ocr", "vl-", "-vl", "realtime")


def _is_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(h in low for h in _NON_CHAT_HINTS)


def _classify_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "freetieronly" in low or "free tier" in low:
        return "额度耗尽"
    if "404" in msg or "not exist" in low or "model_not_found" in low:
        return "型号不存在"
    if "401" in msg or "invalid api key" in low or "authentication" in low:
        return "鉴权失败"
    if "429" in msg or "rate limit" in low:
        return "限流"
    return f"{type(exc).__name__}"


async def fetch_model_ids() -> list[str]:
    """拉账号可见的全量模型 id。"""
    url = settings.DASHSCOPE_API_BASE.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        r = await client.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/models 返回 HTTP {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or []
    return sorted({item.get("id", "") for item in data if item.get("id")})


async def probe(model_id: str, sem: asyncio.Semaphore, with_fc: bool) -> dict:
    res = {"model": model_id, "chat_ok": False, "fc_ok": None, "error": None}
    async with sem:
        llm = ChatOpenAI(
            model=model_id,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,
            temperature=0,
            max_tokens=8,  # 只要"能跑通",不浪费额度
            request_timeout=30,
        )
        try:
            await llm.ainvoke("你好")
            res["chat_ok"] = True
        except Exception as e:
            res["error"] = _classify_error(e)
            return res

        if with_fc:
            try:
                r2 = await llm.bind_tools([get_weather]).ainvoke("北京今天天气怎么样?")
                res["fc_ok"] = bool(getattr(r2, "tool_calls", None))
            except Exception as e:
                res["fc_ok"] = False
                res["error"] = f"fc:{_classify_error(e)}"
    return res


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fc", action="store_true", help="额外探测 function calling")
    ap.add_argument("--concurrency", type=int, default=6, help="并发数(默认 6)")
    args = ap.parse_args()

    print("base_url =", settings.DASHSCOPE_API_BASE)
    if not settings.DASHSCOPE_API_KEY:
        print("\n❌ DASHSCOPE_API_KEY 为空,无法探测。")
        print("   请在 .env 里填上 key 后重跑: DASHSCOPE_API_KEY=sk-...")
        return 2
    print("api_key 前缀 =", settings.DASHSCOPE_API_KEY[:6] + "...")

    try:
        model_ids = await fetch_model_ids()
    except Exception as e:
        print(f"\n❌ 拉取模型列表失败: {e}")
        return 1

    chat_models = [m for m in model_ids if _is_chat_model(m)]
    other_models = [m for m in model_ids if not _is_chat_model(m)]
    print(f"\n账号可见模型 {len(model_ids)} 个(对话类 {len(chat_models)} / 非对话类 {len(other_models)})")
    print(f"开始探测(并发 {args.concurrency}{', 含 FC' if args.fc else ''})...\n" + "=" * 78)

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(probe(m, sem, args.fc) for m in chat_models))
    results.sort(key=lambda r: (not r["chat_ok"], r["model"]))

    free, exhausted, other_fail = [], [], []
    for r in results:
        flag = "✅" if r["chat_ok"] else "❌"
        fc = "" if r["fc_ok"] is None else f" fc={'✅' if r['fc_ok'] else '❌'}"
        print(f"  {flag} {r['model']:<34}{fc} {r['error'] or ''}")
        if r["chat_ok"] and r["error"] is None:
            free.append(r)
        elif r["chat_ok"]:
            free.append(r)          # 对话通但 FC 失败,仍算免费可用
        elif r["error"] == "额度耗尽":
            exhausted.append(r)
        else:
            other_fail.append(r)

    print("\n" + "=" * 78)
    print(f"汇总: 对话类 {len(results)} 个 | 免费可用 {len(free)} | 额度耗尽 {len(exhausted)} | 其它失败 {len(other_fail)}")
    print(f"      非对话类 {len(other_models)} 个(未探测,向量/rerank/语音等)")

    if args.fc:
        fc_ok = [r for r in free if r["fc_ok"]]
        print(f"\n✅ 免费 + 支持 function calling(可直接做 Agent 主推理,共 {len(fc_ok)} 个):")
        for r in fc_ok:
            print(f"   - {r['model']}")

    print(f"\n✅ 免费可用全量({len(free)} 个):")
    for r in free:
        print(f"   - {r['model']}")

    print(f"\n❌ 额度耗尽({len(exhausted)} 个):")
    for r in exhausted:
        print(f"   - {r['model']}")

    if other_models:
        print(f"\nℹ️  非对话类({len(other_models)} 个,如需探测请单独写探针):")
        for m in other_models:
            print(f"   - {m}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))