"""realtime 模型探测(WebSocket)。

probe_nonchat_models.py 把这 15 个 realtime 模型标成"跳过(需 WebSocket)",这里补上。

为什么不能只看握手:
  这些模型全部走 OpenAI-realtime 风格的
      wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=<model>
  连上并发 session.update 就会回 session.created —— 但这只证明"端点认这个模型名",
  不代表额度通过。所以探针分两段:

    第一段 握手 + session.update  → 期望 session.created
    第二段 真实触发一次生成       → 期望拿到产物(音频/转写),或暴露额度错误
      TTS  : input_text_buffer.append + commit      → response.created
      ASR  : input_audio_buffer.append + commit     → ...transcription.delta
      omni : 同 ASR(qwen-audio-* 既收音频也出文本)
      translate: 同 ASR, 但 session 配置随型号变(见下)

  只有第二段成功才算"免费可用";第二段报错则按 error 归类。
  vc/vd 系音色克隆/设计模型第二段必然报 "TTS speak request failed"(需先建音色),
  归为"需先创建音色",不算额度问题。

translate 系为什么要逐个变体试:
  它们的 session.update 必须带 translation.language(否则报 "Invalid translation
  parameter"),且只收 8000/16000 采样率;qwen3.8 还不支持纯文本输出(不给 voice
  就用默认音色 Chelsie,被服务端拒)。这些差异没有单一配置能覆盖,所以直接复用
  probe_livetranslate_params.TRANSLATE_VARIANTS 逐个试,失败时回显服务端
  原始 code/param/message,而不是只给一个归类标签。

用法:
    python scripts/probe_realtime_models.py
    python scripts/probe_realtime_models.py --concurrency 3
    python scripts/probe_realtime_models.py --only <model_id> [<model_id> ...]
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

# 访问阿里时绕过本地代理(与其它探针保持一致)
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

import httpx
import websockets

from src.settings import settings
from probe_nonchat_models import _ensure_speech_wav, classify  # 复用归类口径与探针素材
# translate 只收 8k/16k, 复用降采样; 变体表复用同一份, 避免两处硬编码漂移
from probe_livetranslate_params import TRANSLATE_VARIANTS, _pcm_16k

_WS_REALTIME = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

# 第二段拿到这些事件即视为"真的跑通了"
_TTS_OK = {"response.created", "response.audio.delta", "response.done"}
_ASR_OK = {
    "input_audio_buffer.speech_started",
    "conversation.item.input_audio_transcription.text",
    "conversation.item.input_audio_transcription.delta",
    "conversation.item.input_audio_transcription.completed",
    "response.audio_transcript.delta",
    "response.text.delta",
}
# livetranslate 系: 目标语种文本走 response.text.text(不是 delta), 音频走 response.audio.delta
_TRANSLATE_OK = {
    "response.created",
    "response.text.text",
    "response.text.delta",
    "response.audio.delta",
    "response.audio_transcript.delta",
    "response.done",
}
_OK_BY_FAMILY = {"tts": _TTS_OK, "translate": _TRANSLATE_OK}


def _family(model_id: str) -> str:
    low = model_id.lower()
    if "livetranslate" in low or "s2s" in low:
        return "translate"  # 实时翻译/语音到语音, 需额外的翻译参数
    if "tts" in low:
        return "tts"
    if "asr" in low:
        return "asr"
    return "omni"  # qwen-audio-*/qwen3-omni-*-realtime: 既收音频也出文本


def _headers() -> dict:
    return {"Authorization": "bearer " + (settings.DASHSCOPE_API_KEY or "")}


def _pcm_chunks(family: str) -> tuple[bytes, int]:
    """取探针语音并转成裸 PCM(去掉 WAV 头)。

    采样率随素材实际值,避免被判音频流无效;但 livetranslate 只收 8000/16000,
    所以翻译系统一降到 16k。
    """
    if family == "translate":
        return _pcm_16k(), 16000
    path = _ensure_speech_wav()
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


def _raw_error(err: dict) -> str:
    """把服务端 error 的 code/param/message 拼出来。

    参数类报错必须看到 param —— 只回一个"参数错误"标签会让人无从下手,
    "Invalid translation parameter" 当初就是这么被卡住的。
    """
    parts = [
        f"code={err.get('code')}",
        f"param={err.get('param')}",
        f"message={err.get('message')}",
    ]
    return " ".join(p for p in parts if not p.endswith("=None"))[:160]


async def _recv(ws, timeout: float = 15.0):
    """读一条消息;返回 (type, 归类标签, 原始报错)。"""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        return None, "超时(未收到事件)", "超时"
    except Exception as e:
        return None, classify(type(e).__name__, str(e), 0), f"{type(e).__name__}: {e}"[:160]
    if isinstance(raw, bytes):
        return "binary", None, ""
    try:
        msg = json.loads(raw)
    except Exception:
        return None, f"非 JSON 回包: {str(raw)[:80]}", str(raw)[:160]
    if msg.get("type") == "error" or "error" in msg:
        err = msg.get("error") or msg
        return (
            "error",
            classify(str(err.get("code", "")), str(err.get("message", "")), 0),
            _raw_error(err),
        )
    return msg.get("type"), None, ""


async def _trigger(ws, family: str, pcm: bytes, rate: int) -> None:
    if family == "tts":
        await ws.send(json.dumps({"event_id": uuid.uuid4().hex, "type": "input_text_buffer.append", "text": "你好"}))
        await ws.send(json.dumps({"event_id": uuid.uuid4().hex, "type": "input_text_buffer.commit"}))
        return
    # ASR / omni 走服务端 VAD: 只灌音频,不能发 commit
    # (实测发了 commit 会被判 "Error committing input audio buffer, maybe no invalid audio stream")
    for i in range(0, len(pcm), 32000):
        await ws.send(json.dumps({
            "event_id": uuid.uuid4().hex,
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm[i:i + 32000]).decode(),
        }))


async def _session_update(ws, family: str, rate: int) -> None:
    """非 translate 系的固定 session 配置; translate 的配置随型号变,走 _probe_translate。"""
    if family == "tts":
        session = {"voice": "Cherry", "response_format": "pcm"}
    else:
        session = {"modalities": ["text"], "input_audio_format": "pcm", "sample_rate": rate}
    await ws.send(json.dumps({"event_id": uuid.uuid4().hex, "type": "session.update", "session": session}))


def _connect(model_id: str):
    return websockets.connect(
        f"{_WS_REALTIME}?model={model_id}",
        additional_headers=_headers(),
        open_timeout=15,
        close_timeout=5,
        proxy=None,  # 与 HTTP 探针的 trust_env=False 对齐
    )


async def _probe_translate(
    model_id: str, pcm: bytes, rate: int, ok_signals: set[str],
) -> tuple[bool, str | None, str]:
    """livetranslate 系: session 配置随型号而异, 逐个变体试, 并把服务端原始报错带回来。

    "Invalid translation parameter" 这种错只给一个归类标签没用 —— 得看到 param/
    message 才知道是 translation.language 缺失还是采样率/音色不被接受。所以:
      error  = 归类标签(供汇总分桶用)
      detail = 服务端原始 code/param/message(供人排查用)
    """
    failures: list[tuple[str, str]] = []  # (归类标签, 原始报错)
    for name, base in TRANSLATE_VARIANTS.items():
        session = {**base, "sample_rate": rate}
        try:
            async with _connect(model_id) as ws:
                await ws.send(json.dumps({
                    "event_id": uuid.uuid4().hex,
                    "type": "session.update",
                    "session": session,
                }))
                # 先确认参数被接受(session.created → session.updated / error)
                accepted = False
                for _ in range(3):
                    etype, err, raw = await _recv(ws)
                    if etype == "error":
                        failures.append((f"[{name}] {err or raw}", raw))
                        break
                    if etype == "session.updated":
                        accepted = True
                        break
                if not accepted:
                    continue

                await _trigger(ws, "translate", pcm, rate)
                for _ in range(20):
                    etype, err, raw = await _recv(ws)
                    if etype == "error":
                        failures.append((f"[{name}] {err or raw}", raw))
                        break
                    if etype is None:
                        failures.append((f"[{name}] {err}", raw))
                        break
                    if etype in ok_signals:
                        return True, None, f"[{name}] 第二段拿到 {etype}"
        except Exception as e:
            label = classify(type(e).__name__, str(e), 0)
            failures.append((f"[{name}] {label}", f"{type(e).__name__}: {e}"[:160]))
    if not failures:
        return False, "所有变体均未跑通", "translate 变体全试"
    labels = " | ".join(l for l, _ in failures)
    raws = " | ".join(f"{l} → {r}" for l, r in failures if r)
    return False, labels, f"translate 变体全试 | {raws}" if raws else "translate 变体全试"


async def _probe_once(model_id: str) -> tuple[bool, str | None, str]:
    """返回 (是否可用, 错误标签, 过程说明)。"""
    family = _family(model_id)
    pcm, rate = _pcm_chunks(family) if family != "tts" else (b"", 24000)
    ok_signals = _OK_BY_FAMILY.get(family, _ASR_OK)

    if family == "translate":
        return await _probe_translate(model_id, pcm, rate, ok_signals)

    try:
        async with _connect(model_id) as ws:
            await _session_update(ws, family, rate)
            etype, err, _ = await _recv(ws)
            if etype != "session.created":
                return False, err or f"握手异常({etype})", "第一段"

            await _trigger(ws, family, pcm, rate)
            for _ in range(14):
                etype, err, raw = await _recv(ws)
                if etype == "error":
                    # error 留归类标签(供汇总分桶), 原始报错进 detail(供人排查)
                    return False, err or raw, f"第二段 | {raw}" if raw else "第二段"
                if etype is None:
                    return False, err, f"第二段 | {raw}" if raw else "第二段"
                if etype in ok_signals:
                    return True, None, f"第二段拿到 {etype}"
            return False, "未收到产物事件", "第二段"
    except websockets.exceptions.InvalidStatus as e:
        status = getattr(getattr(e, "response", None), "status_code", 0)
        return False, classify("", str(e), status if isinstance(status, int) else 0), "握手"
    except Exception as e:
        return False, classify(type(e).__name__, str(e), 0), "连接"


async def probe(model_id: str, sem: asyncio.Semaphore) -> dict:
    # translate 要逐个试变体, 给足时间, 免得"整体超时"把真实失败原因盖掉
    budget = 180 if _family(model_id) == "translate" else 90
    async with sem:
        try:
            ok, err, detail = await asyncio.wait_for(_probe_once(model_id), timeout=budget)
        except asyncio.TimeoutError:
            ok, err, detail = False, "整体超时", "-"
    return {"model": model_id, "family": _family(model_id), "ok": ok, "error": err, "detail": detail}


def fetch_realtime_ids() -> list[str]:
    url = settings.DASHSCOPE_API_BASE.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    with httpx.Client(timeout=30, trust_env=False) as client:
        r = client.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/models 返回 HTTP {r.status_code}: {r.text[:200]}")
    ids = {item.get("id", "") for item in r.json().get("data") or [] if item.get("id")}
    return sorted(m for m in ids if "realtime" in m.lower())


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=3, help="并发数(默认 3)")
    ap.add_argument("--only", nargs="*", default=None, help="只探测指定模型 id")
    args = ap.parse_args()

    if not settings.DASHSCOPE_API_KEY:
        print("❌ DASHSCOPE_API_KEY 为空,无法探测。")
        return 2

    targets = list(args.only) if args.only else fetch_realtime_ids()
    print(f"api_key 前缀 = {settings.DASHSCOPE_API_KEY[:6]}...")
    print(f"待探测 realtime 模型 {len(targets)} 个(并发 {args.concurrency})")
    print("=" * 78)

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(probe(m, sem) for m in targets))
    results.sort(key=lambda r: (not r["ok"], r["family"], r["model"]))

    for r in results:
        flag = "✅" if r["ok"] else "❌"
        tail = f" ← {r['error']}" if r["error"] else ""
        print(f"  {flag} [{r['family']:<4}] {r['model']:<42} {r['detail']}{tail}")

    free = [r for r in results if r["ok"]]
    # translate 的 error 可能带多个变体标签(如 "[v1] 额度耗尽 | [v2] 超时"), 用包含判断
    def _is_exhausted(r: dict) -> bool:
        return not r["ok"] and "额度耗尽" in (r["error"] or "")

    exhausted = [r for r in results if _is_exhausted(r)]
    other = [r for r in results if not r["ok"] and not _is_exhausted(r)]

    print("\n" + "=" * 78)
    print(f"汇总: 共 {len(results)} | 免费可用 {len(free)} | 额度耗尽 {len(exhausted)} | 其它 {len(other)}")

    if free:
        print(f"\n✅ 免费可用({len(free)} 个):")
        for r in free:
            print(f"   - [{r['family']}] {r['model']}")
    if exhausted:
        print(f"\n❌ 额度耗尽({len(exhausted)} 个):")
        for r in exhausted:
            print(f"   - [{r['family']}] {r['model']}")
    if other:
        print(f"\n⚠️  其它({len(other)} 个):")
        for r in other:
            print(f"   - [{r['family']}] {r['model']}  ← {r['error']}  ({r['detail']})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))