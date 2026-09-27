"""摸清 livetranslate 系模型的翻译参数(session.update 里 translation 该放哪、放什么)。

probe_realtime_models.py 之前把这 6 个模型标成"需正确的翻译参数(未探明)",
本脚本就是去探明它。做法: 同一个模型依次尝试几种 session 配置,
看服务端回 session.updated(参数被接受)还是 error(参数不对),
并把 error 的 code/message/param 原样打出来 —— 参数名对不对,由服务端说了算。

参数依据(SDK + 官方文档):
  dashscope/audio/qwen_omni/omni_realtime.py  TranslationParams(language, corpus)
    → self.config["translation"] = {"language": ...}
  文档 LiveTranslate client events:
    qwen3.5-livetranslate-flash-realtime 用 modalities / voice / sample_rate(仅 8000|16000)
    qwen3.8-livetranslate-flash-realtime 用 output_modalities
    两者都用 translation.language 指定目标语种(默认 en)

用法:
    python scripts/probe_livetranslate_params.py
    python scripts/probe_livetranslate_params.py --models qwen3.5-livetranslate-flash-realtime
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
import wave
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for _p in (str(_PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

import websockets

from src.settings import settings
from probe_nonchat_models import _ensure_speech_wav

_WS_REALTIME = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

DEFAULT_MODELS = [
    "qwen3-livetranslate-flash-realtime",
    "qwen3-livetranslate-flash-realtime-2025-09-22",
    "qwen3-s2s-flash-realtime-2025-09-22",
    "qwen3.5-livetranslate-flash-realtime",
    "qwen3.5-livetranslate-flash-realtime-2026-05-19",
    "qwen3.8-livetranslate-flash-realtime",
]

# 依次尝试的 session 配置(唯一数据源: probe_realtime_models.py 也 import 这张表)。
# key 是变体名, value 是 session 对象(不含 sample_rate, 由调用方按素材填)。
# 实测结论: qwen3/qwen3.5 系纯文本即可; qwen3.8 纯文本会被拒(默认音色 Chelsie
# 不支持), 必须显式 text+audio + voice Tina。后面的变体是留作兜底的搜索空间。
TRANSLATE_VARIANTS: dict[str, dict] = {
    # 纯文本输出: 不涉及音色, 最容易过
    "3.5-text-only": {
        "modalities": ["text"],
        "input_audio_format": "pcm",
        "translation": {"language": "en"},
    },
    # 文本+音频: 文档说 3.5 的默认音色是 Tina(Cherry 会被拒)
    "3.5-text+audio-Tina": {
        "modalities": ["text", "audio"],
        "voice": "Tina",
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "translation": {"language": "en"},
    },
    # 3.8 走 output_modalities, 且不支持 voice/input_audio_transcription
    "3.8-output-text": {
        "output_modalities": ["text"],
        "translation": {"language": "en"},
    },
    "3.8-output-text+audio": {
        "output_modalities": ["text", "audio"],
        "translation": {"language": "en"},
    },
    "minimal-translation": {
        "translation": {"language": "en"},
    },
}


def _headers() -> dict:
    return {"Authorization": "bearer " + (settings.DASHSCOPE_API_KEY or "")}


def _pcm_16k() -> bytes:
    """探针语音是 24k 单声道 16bit; translate 只收 8k/16k, 这里线性插值降到 16k。"""
    path = _ensure_speech_wav()
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if rate == 16000:
        return raw
    try:
        import numpy as np
    except ImportError:
        return raw  # 没 numpy 就原样送, 采样率字段仍按 16000 声明
    src = np.frombuffer(raw, dtype="<i2")
    n_dst = int(len(src) * 16000 / rate)
    dst = np.interp(
        np.linspace(0, len(src) - 1, n_dst),
        np.arange(len(src)),
        src.astype("float32"),
    ).astype("<i2")
    return dst.tobytes()


async def _recv(ws, timeout: float):
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    if isinstance(raw, bytes):
        return {"type": "binary"}
    try:
        return json.loads(raw)
    except Exception:
        return {"type": "error", "error": {"message": f"非 JSON: {str(raw)[:120]}"}}


def _err_text(msg: dict) -> str:
    err = msg.get("error") or {}
    parts = [
        f"code={err.get('code')}",
        f"param={err.get('param')}",
        f"message={err.get('message')}",
    ]
    return " ".join(p for p in parts if not p.endswith("=None"))


async def _try_variant(ws, session: dict, timeout: float) -> tuple[bool, str]:
    await ws.send(json.dumps({
        "event_id": uuid.uuid4().hex,
        "type": "session.update",
        "session": session,
    }))
    seen = []
    while True:
        msg = await _recv(ws, timeout)
        if msg is None:
            return False, f"超时(已见 {seen or '无事件'})"
        etype = msg.get("type")
        if etype == "error":
            return False, _err_text(msg)
        if etype == "session.updated":
            return True, "session.updated(参数被接受)"
        seen.append(etype)
        if len(seen) > 8:
            return False, f"未收到 session.updated, 只见 {seen}"


async def _run_generation(ws, pcm: bytes) -> tuple[bool, str]:
    """参数被接受后, 灌一段音频, 看是否真的产出翻译结果。"""
    for i in range(0, len(pcm), 32000):
        await ws.send(json.dumps({
            "event_id": uuid.uuid4().hex,
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm[i:i + 32000]).decode(),
        }))
    await ws.send(json.dumps({"event_id": uuid.uuid4().hex, "type": "session.finish"}))

    hits: list[str] = []
    texts: list[str] = []
    for _ in range(60):
        msg = await _recv(ws, 20)
        if msg is None:
            break
        etype = msg.get("type")
        if etype == "error":
            return False, f"生成阶段报错: {_err_text(msg)}"
        if etype and etype not in hits:
            hits.append(etype)
        if etype == "response.text.text" and msg.get("text"):
            texts.append(msg["text"])
        if etype == "session.finished":
            break
    text_events = [h for h in hits if h.startswith(("response.text", "response.audio"))]
    if text_events:
        shown = "".join(texts).strip()[:80]
        return True, f"产出事件: {', '.join(hits[:8])}" + (f" | 译文: {shown}" if shown else "")
    return False, f"仅收到: {', '.join(hits[:10]) or '无事件'}"


async def _attempt(model_id: str, session: dict, pcm: bytes) -> tuple[bool, str]:
    """一次完整尝试: 连接 → session.update → 灌音频。返回 (是否真正跑通, 说明)。"""
    try:
        async with websockets.connect(
            f"{_WS_REALTIME}?model={model_id}",
            additional_headers=_headers(),
            open_timeout=15,
            close_timeout=5,
            proxy=None,
        ) as ws:
            msg = await _recv(ws, 15)
            if not msg or msg.get("type") != "session.created":
                return False, f"握手失败: {_err_text(msg) if msg else '无响应'}"
            ok, detail = await _try_variant(ws, session, 8)
            if not ok:
                return False, detail
            gen_ok, gen_detail = await _run_generation(ws, pcm)
            return gen_ok, f"session.updated → {gen_detail}" if gen_ok else f"session.updated 但{gen_detail}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def probe_model(model_id: str, pcm: bytes) -> None:
    print(f"\n{'=' * 78}\n▶ {model_id}")
    for name, base in TRANSLATE_VARIANTS.items():
        session = {**base, "sample_rate": 16000}
        ok, detail = await _attempt(model_id, session, pcm)
        print(f"  {'✓' if ok else '✗'} [{name}] {detail}")
        if ok:
            return
    print("  ⚠️  所有变体都没跑通")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=None, help="只探指定模型")
    args = ap.parse_args()

    if not settings.DASHSCOPE_API_KEY:
        print("❌ DASHSCOPE_API_KEY 为空")
        return 2

    pcm = _pcm_16k()
    print(f"api_key 前缀 = {settings.DASHSCOPE_API_KEY[:6]}... | 送检音频 {len(pcm)} 字节 @16k")
    for m in args.models or DEFAULT_MODELS:
        await probe_model(m, pcm)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))