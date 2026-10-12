"""LLM 调用统一重试（B5：ainvoke_with_retry）测试。

覆盖：可重试判定（状态码/异常类名）、重试成功、非瞬态立即上抛、
耗尽后上抛、开关停用、设置内次数上限。
"""

import pytest

from src.agent.aiops_llm import _is_retryable_error, ainvoke_with_retry
from src.settings import settings


class _StatusError(Exception):
    def __init__(self, status: int, msg: str = "err"):
        super().__init__(msg)
        self.status_code = status


class _FakeRunnable:
    """按剧本依次抛错/返回值；记录调用次数。"""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        out = self._outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


# ── 可重试判定 ──────────────────────────────────────────────


def test_retryable_status_codes():
    for status in (429, 500, 502, 503, 504):
        assert _is_retryable_error(_StatusError(status)), status
    for status in (400, 401, 403, 404, 422):
        assert not _is_retryable_error(_StatusError(status)), status


def test_retryable_exc_class_names():
    for name in ("APITimeoutError", "APIConnectionError", "ReadTimeout"):
        exc = type(name, (Exception,), {})()
        assert _is_retryable_error(exc), name
    assert not _is_retryable_error(ValueError("x"))
    assert not _is_retryable_error(RuntimeError("y"))


# ── 重试行为 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_then_success():
    r = _FakeRunnable([_StatusError(429), "ok"])
    res = await ainvoke_with_retry(r, [], base_delay=0.01)
    assert res == "ok"
    assert r.calls == 2


@pytest.mark.asyncio
async def test_no_retry_on_non_retryable():
    r = _FakeRunnable([_StatusError(400)])
    with pytest.raises(_StatusError):
        await ainvoke_with_retry(r, [], base_delay=0.01)
    assert r.calls == 1


@pytest.mark.asyncio
async def test_exhausted_raises_after_max_attempts():
    r = _FakeRunnable([_StatusError(503), _StatusError(503), _StatusError(503)])
    with pytest.raises(_StatusError):
        await ainvoke_with_retry(r, [], base_delay=0.01, max_attempts=3)
    assert r.calls == 3


@pytest.mark.asyncio
async def test_switch_disables_retry(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LLM_RETRY", False)
    r = _FakeRunnable([_StatusError(503)])
    with pytest.raises(_StatusError):
        await ainvoke_with_retry(r, [], base_delay=0.01)
    assert r.calls == 1


@pytest.mark.asyncio
async def test_max_attempts_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 2)
    r = _FakeRunnable([_StatusError(500), _StatusError(500)])
    with pytest.raises(_StatusError):
        await ainvoke_with_retry(r, [], base_delay=0.01)
    assert r.calls == 2


@pytest.mark.asyncio
async def test_timeout_exc_name_retried():
    TimeoutErrorFake = type("APITimeoutError", (Exception,), {})
    r = _FakeRunnable([TimeoutErrorFake(), "ok"])
    res = await ainvoke_with_retry(r, [], base_delay=0.01)
    assert res == "ok" and r.calls == 2
