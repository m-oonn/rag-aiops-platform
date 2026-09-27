"""非对话类模型探测: 向量 / rerank / 视觉(VL, OCR) / 语音合成(TTS) / 语音识别(ASR)。

为什么单独一个脚本:
  probe_all_models.py 用 chat 探针去测这些模型,只会得到假阴性 —— 它们本就不接受
  纯文本对话,报 BadRequest 并不代表"不可用"。所以这里按模态拆开,每种模态用各自
  的原生接口做一次最小调用,判定的核心问题只有一个: 免费可用 还是 额度耗尽。

不探测:
  realtime 系列(qwen-audio-*-realtime / qwen3-asr-flash-realtime / qwen3-tts-*-realtime)
  只能走 WebSocket 长连接,HTTP 探针不适用,单独归类。

与业务代码保持一致:
  向量  → dashscope.TextEmbedding.call   (同 src/embedding/dashscope_embedding.py)
  rerank → dashscope.TextReRank.call     (同 src/retrieval/reranker.py)
  VL/OCR/TTS/ASR → dashscope.MultiModalConversation.call

用法:
    python scripts/probe_nonchat_models.py
    python scripts/probe_nonchat_models.py --concurrency 4
    python scripts/probe_nonchat_models.py --only qwen3.7-text-embedding
"""

import argparse
import base64
import os
import struct
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 访问阿里时绕过本地代理(与其它探针保持一致)
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

import dashscope
import httpx
from dashscope import MultiModalConversation, TextEmbedding, TextReRank

from src.settings import settings


# ---------------------------------------------------------------------------
# 素材: 探针需要一张图和一段音频,本地生成,避免依赖外部 URL
# ---------------------------------------------------------------------------
def _tiny_png() -> bytes:
    """生成一张 8x8 纯红 PNG(手写 PNG 编码,不依赖 Pillow)。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)  # 8x8, 8bit, truecolor
    raw = b"".join(b"\x00" + bytes([255, 0, 0] * 8) for _ in range(8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(_tiny_png()).decode()
_SPEECH_WAV_PATH = _PROJECT_ROOT / "reports" / "_probe_speech.wav"

# 原生(非 compatible-mode)入口, qwen-audio 系列 ASR 只认这个
_NATIVE_BASE = settings.DASHSCOPE_API_BASE.split("/compatible-mode")[0].rstrip("/")
_NATIVE_MMGEN = _NATIVE_BASE + "/api/v1/services/aigc/multimodal-generation/generation"


def _ensure_speech_wav() -> Path:
    """ASR 需要"有内容的语音",静音会被判 ASR_RESPONSE_HAVE_NO_WORDS。

    不引外部音频 URL,直接用免费的 qwen3-tts-flash 合成一句,落盘复用。
    """
    if _SPEECH_WAV_PATH.exists() and _SPEECH_WAV_PATH.stat().st_size > 1000:
        return _SPEECH_WAV_PATH
    resp = MultiModalConversation.call(
        model="qwen3-tts-flash",
        api_key=settings.DASHSCOPE_API_KEY,
        text="你好，这是一段用于探测的测试语音。",
        voice="Cherry",
    )
    url = (getattr(resp, "output", None) or {}).get("audio", {}).get("url")
    if not url:
        raise RuntimeError(f"TTS 未返回音频 URL: {resp}")
    with httpx.Client(timeout=60, trust_env=False) as client:
        audio = client.get(url).content
    _SPEECH_WAV_PATH.write_bytes(audio)
    return _SPEECH_WAV_PATH


# ---------------------------------------------------------------------------
# 模态归类
# ---------------------------------------------------------------------------
# 与 probe_all_models.py 的 _NON_CHAT_HINTS 保持一致的"非对话"判定
_NON_CHAT_HINTS = ("embedding", "rerank", "asr", "tts", "speech", "audio", "ocr", "vl-", "-vl")


def is_non_chat(model_id: str) -> bool:
    low = model_id.lower()
    return any(h in low for h in _NON_CHAT_HINTS)


def modality_of(model_id: str) -> str:
    """判定模态。顺序有讲究: realtime 必须最先判,否则会被 asr/tts 抢先。"""
    low = model_id.lower()
    if "realtime" in low:
        return "realtime"
    if "embedding" in low:
        return "embedding"
    if "rerank" in low:
        return "rerank"
    if "asr" in low:
        return "asr"
    if "tts" in low or "speech" in low:
        return "tts"
    if "ocr" in low or "vl-" in low or "-vl" in low:
        return "vl"
    return "unknown"


# ---------------------------------------------------------------------------
# 错误归类
# ---------------------------------------------------------------------------
def classify(code: str, msg: str, status_code: int) -> str:
    blob = f"{code} {msg}".lower()
    if "freetieronly" in blob or "free tier" in blob or "free quota" in blob:
        return "额度耗尽"
    if "arrearage" in blob or "overdue" in blob or "欠费" in blob:
        return "欠费"
    if status_code == 401 or "invalidapikey" in blob or "authentication" in blob:
        return "鉴权失败"
    if status_code == 403:
        return "额度耗尽" if "free" in blob else "无权限(403)"
    if status_code == 404 or "modelnotfound" in blob or ("model" in blob and "not exist" in blob):
        return "型号不存在"
    if status_code == 429 or "throttl" in blob or "rate limit" in blob:
        return "限流"
    if "not activated" in blob or "未开通" in blob:
        return "未开通"
    if "url error" in blob or "check url" in blob:
        return "仅支持公网 URL(探针不适用)"
    if "tts speak request failed" in blob:
        return "需先创建音色(探针不适用)"
    if "invalid translation parameter" in blob:
        # 参数已被摸清(见 probe_livetranslate_params.py), 这里只说明"该变体不被接受"
        return "翻译参数不被接受"
    if "unsupported_format" in blob or "asr_response_have_no_words" in blob:
        return f"格式/素材不符({code})"
    if "invalidparameter" in blob or "badrequest" in blob or "invalidinput" in blob or status_code == 400:
        return f"参数错误({code or status_code})"
    # 兜底: 宁可回显原始信息,也不要只吐一个 "0"
    return msg.strip()[:60] if msg.strip() else f"{code or status_code}"


def _verdict(resp) -> tuple[bool, str | None]:
    """把 SDK 响应统一成 (是否可用, 错误标签)。"""
    status = getattr(resp, "status_code", None)
    code = getattr(resp, "code", None) or ""
    msg = getattr(resp, "message", None) or ""
    if status == 200 and not code:
        return True, None
    return False, classify(str(code), str(msg), status if isinstance(status, int) else 0)


# ---------------------------------------------------------------------------
# 各模态的最小调用
# ---------------------------------------------------------------------------
def probe_embedding(model_id: str) -> tuple[bool, str | None, str]:
    resp = TextEmbedding.call(model=model_id, input="探针", api_key=settings.DASHSCOPE_API_KEY)
    ok, err = _verdict(resp)
    dim = ""
    if ok:
        try:
            dim = f"dim={len(resp.output['embeddings'][0]['embedding'])}"
        except Exception:
            pass
    return ok, err, dim


def probe_rerank(model_id: str) -> tuple[bool, str | None, str]:
    resp = TextReRank.call(
        model=model_id,
        query="探针",
        documents=["甲", "乙"],
        top_n=2,
        api_key=settings.DASHSCOPE_API_KEY,
    )
    ok, err = _verdict(resp)
    return ok, err, ""


def probe_vl(model_id: str) -> tuple[bool, str | None, str]:
    resp = MultiModalConversation.call(
        model=model_id,
        api_key=settings.DASHSCOPE_API_KEY,
        messages=[{"role": "user", "content": [{"image": _PNG_DATA_URL}, {"text": "这是什么颜色?"}]}],
    )
    ok, err = _verdict(resp)
    return ok, err, ""


def probe_tts(model_id: str) -> tuple[bool, str | None, str]:
    resp = MultiModalConversation.call(
        model=model_id,
        api_key=settings.DASHSCOPE_API_KEY,
        text="你好",
        voice="Cherry",
    )
    ok, err = _verdict(resp)
    return ok, err, ""


def _post_native(body: dict) -> tuple[bool, str | None]:
    """打原生 multimodal-generation 入口(qwen-audio 系 ASR 走这里)。"""
    headers = {
        "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60, trust_env=False) as client:
        r = client.post(_NATIVE_MMGEN, headers=headers, json=body)
    try:
        payload = r.json()
    except Exception:
        return False, classify("", r.text[:200], r.status_code)
    if r.status_code == 200 and not payload.get("code"):
        return True, None
    return False, classify(str(payload.get("code", "")), str(payload.get("message", "")), r.status_code)


def probe_asr(model_id: str) -> tuple[bool, str | None, str]:
    """ASR 两套入口都试: 先 SDK(本地文件),格式不符再退原生(显式 format)。

    两套都是"最小调用",取第一个非格式类的结果作为判定。
    """
    audio = _ensure_speech_wav()
    attempts = [
        ("sdk", lambda: _verdict(MultiModalConversation.call(
            model=model_id,
            api_key=settings.DASHSCOPE_API_KEY,
            messages=[{"role": "user", "content": [{"audio": str(audio)}]}],
        ))),
        ("native", lambda: _post_native({
            "model": model_id,
            "input": {"messages": [{"role": "user", "content": [
                {"audio": "data:audio/wav;base64," + base64.b64encode(audio.read_bytes()).decode()},
            ]}]},
            "parameters": {"format": "wav"},
        })),
    ]
    last: str | None = None
    for _, call in attempts:
        try:
            ok, err = call()
        except Exception as e:
            ok, err = False, classify(type(e).__name__, str(e), 0)
        if ok:
            return True, None, ""
        last = err
        # 只有"格式/素材不符"才值得换入口重试;额度耗尽/鉴权失败等是终局结论
        if not (err or "").startswith("格式/素材不符"):
            return False, err, ""
    return False, last, ""


_PROBES = {
    "embedding": probe_embedding,
    "rerank": probe_rerank,
    "vl": probe_vl,
    "tts": probe_tts,
    "asr": probe_asr,
}


# ---------------------------------------------------------------------------
# 拉账号可见模型
# ---------------------------------------------------------------------------
def fetch_model_ids() -> list[str]:
    url = settings.DASHSCOPE_API_BASE.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    with httpx.Client(timeout=30, trust_env=False) as client:
        r = client.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/models 返回 HTTP {r.status_code}: {r.text[:200]}")
    return sorted({item.get("id", "") for item in r.json().get("data") or [] if item.get("id")})


def run_one(model_id: str) -> dict:
    modality = modality_of(model_id)
    res = {"model": model_id, "modality": modality, "ok": False, "error": None, "extra": ""}

    if modality == "realtime":
        res["error"] = "跳过(需 WebSocket)"
        return res
    probe = _PROBES.get(modality)
    if probe is None:
        res["error"] = "未归类(无对应探针)"
        return res

    try:
        ok, err, extra = probe(model_id)
        res["ok"], res["error"], res["extra"] = ok, err, extra
    except Exception as e:  # SDK 对部分错误直接抛异常
        res["error"] = classify(type(e).__name__, str(e), 0)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=4, help="并发数(默认 4)")
    ap.add_argument("--only", nargs="*", default=None, help="只探测指定模型 id")
    args = ap.parse_args()

    if not settings.DASHSCOPE_API_KEY:
        print("❌ DASHSCOPE_API_KEY 为空,无法探测。请在 .env 里填上后重跑。")
        return 2

    dashscope.api_key = settings.DASHSCOPE_API_KEY
    _SPEECH_WAV_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        speech = _ensure_speech_wav()
        print(f"ASR 探针素材 = {speech.name} ({speech.stat().st_size} bytes)")
    except Exception as e:
        print(f"⚠️  合成 ASR 探针素材失败({e}),ASR 结果将不可信。")

    if args.only:
        targets = list(args.only)
    else:
        try:
            targets = [m for m in fetch_model_ids() if is_non_chat(m)]
        except Exception as e:
            print(f"❌ 拉取模型列表失败: {e}")
            return 1

    print(f"api_key 前缀 = {settings.DASHSCOPE_API_KEY[:6]}...")
    print(f"待探测非对话类模型 {len(targets)} 个(并发 {args.concurrency})")
    print("=" * 78)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(run_one, targets))
    results.sort(key=lambda r: (not r["ok"], r["modality"], r["model"]))

    for r in results:
        flag = "✅" if r["ok"] else "❌"
        extra = f" {r['extra']}" if r["extra"] else ""
        print(f"  {flag} [{r['modality']:<9}] {r['model']:<38} {r['error'] or ''}{extra}")

    free = [r for r in results if r["ok"]]
    exhausted = [r for r in results if r["error"] == "额度耗尽"]
    skipped = [r for r in results if r["error"] and r["error"].startswith("跳过")]
    other = [r for r in results if r not in free and r not in exhausted and r not in skipped]

    print("\n" + "=" * 78)
    print(
        f"汇总: 共 {len(results)} | 免费可用 {len(free)} | 额度耗尽 {len(exhausted)} "
        f"| 跳过 {len(skipped)} | 其它 {len(other)}"
    )

    def _dump(title: str, rows: list[dict]) -> None:
        if not rows:
            return
        print(f"\n{title}({len(rows)} 个):")
        for r in rows:
            tail = f"  ← {r['error']}" if r["error"] else ""
            print(f"   - [{r['modality']}] {r['model']}{tail}")

    _dump("✅ 免费可用", free)
    _dump("❌ 额度耗尽", exhausted)
    _dump("⏭️  跳过", skipped)
    _dump("⚠️  其它失败(需人工判读)", other)
    return 0


if __name__ == "__main__":
    sys.exit(main())