"""Agent的OpenAI兼容模型工厂。

模型由显式参数、进程AGENT_MODEL或settings.AGENT_MODEL选择，地址/凭据来自
RESOLVED_LLM_API_BASE/KEY。RAG的LLMClient按模型前缀选ChatTongyi或ChatOpenAI。
供应商切换后的工具调用、结构化输出和计费须分别核验；构造实例不代表调用已通过。
"""

import asyncio

from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
import httpx

from src.settings import settings
from src.utils.logger import logger
from src.utils.metrics import AIOPS_LLM_RETRIES_TOTAL


def create_agent_llm(
    model: str | None = None,
    temperature: float = 0.0,
    streaming: bool = False,
    callbacks: list | None = None,
    max_retries: int | None = None,
) -> ChatOpenAI:
    """创建运维 Agent 用的 ChatOpenAI 实例(compatible-mode)。

    Args:
        model: 显式模型名；省略时取进程环境或settings.AGENT_MODEL。
        temperature: 默认 0,诊断要可复现、不要发散。
        streaming: 节点内部一次性 ainvoke 不需要流式;图层用 astream 做流式输出。
        callbacks: 额外的 LangChain 回调(如 TokenMeter 计量 token 消耗);
                   未显式传入时,自动挂载全局活动计量器(token_meter.start_meter() 启用)。

    Returns:
        配好 base_url / api_key 的 ChatOpenAI,可直接 bind_tools / with_structured_output。
    """
    import os  # noqa: E402
    from src.utils.token_meter import get_active_meter  # 延迟导入避免循环依赖

    cbs = list(callbacks or [])
    if not cbs:
        m = get_active_meter()
        if m is not None:
            cbs.append(m)

    primary_model = model or os.environ.get("AGENT_MODEL", settings.AGENT_MODEL)
    primary = _build_compatible_llm(primary_model, temperature,
        base_url=settings.RESOLVED_LLM_API_BASE, api_key=settings.RESOLVED_LLM_API_KEY,
        streaming=streaming, callbacks=cbs, max_retries=max_retries)
    fallback_key = settings.RESOLVED_LLM_FALLBACK_API_KEY
    fallback_base = (settings.LLM_FALLBACK_API_BASE or '').rstrip('/')
    fallback_model = settings.LLM_FALLBACK_MODEL
    if (settings.LLM_FALLBACK_ENABLED and fallback_key and fallback_base and fallback_model
            and fallback_base != settings.RESOLVED_LLM_API_BASE.rstrip('/')
            and not primary_model.lower().startswith(('qwen', 'text-embedding'))):
        fallback = _build_compatible_llm(fallback_model, temperature,
            base_url=fallback_base, api_key=fallback_key,
            streaming=streaming, callbacks=cbs, max_retries=max_retries)
        logger.warning('[llm] 主通道失败时启用官方 DeepSeek 兜底: %s', fallback_model)
        return primary.with_fallbacks([fallback], exceptions_to_handle=_FALLBACK_EXCEPTIONS)
    return primary


# ═══════════════════════════════════════════════════════════════
# LLM 调用统一重试（B5——借鉴 pi auto-retry 的指数退避）
# ═══════════════════════════════════════════════════════════════

# 可重试的 HTTP 状态码（瞬态服务端/限流错误）
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# 可重试的异常类名（连接/超时类；openai SDK 与 httpx 的常见类型）
_RETRYABLE_EXC_NAMES = frozenset({
    "APITimeoutError", "APIConnectionError", "InternalServerError",
    "RateLimitError", "ReadTimeout", "ConnectTimeout", "TimeoutException",
    "TimeoutError", "ConnectError", "RemoteProtocolError",
})

_FALLBACK_EXCEPTIONS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


def _is_retryable_error(e: Exception) -> bool:
    """判定异常是否属于「瞬态、可重试」类（429/5xx/连接超时）。

    判定依据（任一命中）：
      - 异常携带 status_code ∈ {429,500,502,503,504}；
      - 异常类名在 _RETRYABLE_EXC_NAMES 白名单。
    其他异常（如 400 参数错误、鉴权失败）立即上抛——不掩盖真错误（pi"不隐藏"哲学）。
    """
    status = getattr(e, "status_code", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS:
        return True
    return type(e).__name__ in _RETRYABLE_EXC_NAMES


def _build_compatible_llm(model: str, temperature: float, *, base_url: str,
                          api_key: str | None, streaming: bool = False,
                          callbacks: list | None = None, max_retries: int | None = None):
    """Build one OpenAI-compatible client with provider-specific thinking flags."""
    extra_body = None
    if settings.AGENT_DISABLE_THINKING:
        if base_url.rstrip('/') == 'https://dashscope.aliyuncs.com/compatible-mode/v1':
            extra_body = {"enable_thinking": False}
        else:
            extra_body = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        streaming=streaming,
        api_key=api_key,
        base_url=base_url,
        request_timeout=60,
        extra_body=extra_body,
        default_headers={"User-Agent": "Python-urllib/3.13"},
        callbacks=callbacks or None,
        **({'max_retries': max_retries} if max_retries is not None else {}),
    )


async def ainvoke_with_retry(
    runnable,
    messages,
    *,
    label: str = "",
    max_attempts: int | None = None,
    base_delay: float = 1.0,
):
    """调用 runnable.ainvoke(messages)，对瞬态错误指数退避重试。

    - 开关: settings.ENABLE_LLM_RETRY=False 时直接单次调用（旧行为,回归兼容）；
    - 次数: 入参 max_attempts > settings.LLM_RETRY_MAX_ATTEMPTS > 3；
    - 退避: base_delay * 2^(n-1)（默认 1s, 2s, 4s ...）；
    - 可见化: 每次重试 logger.warning + AIOPS_LLM_RETRIES_TOTAL 计数。
    """
    attempts = max_attempts or int(getattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 3) or 3)
    enabled = bool(getattr(settings, "ENABLE_LLM_RETRY", True))
    if not enabled or attempts <= 1:
        return await runnable.ainvoke(messages)

    for i in range(attempts):
        try:
            return await runnable.ainvoke(messages)
        except Exception as e:  # noqa: BLE001 —— 去留由 _is_retryable_error 判定
            if not _is_retryable_error(e):
                raise
            if i == attempts - 1:
                AIOPS_LLM_RETRIES_TOTAL.labels(result="exhausted").inc()
                raise
            delay = base_delay * (2 ** i)
            logger.warning(
                "[llm_retry] %s 第 %d/%d 次调用失败(%s: %s)，%.1fs 后重试",
                label or "llm", i + 1, attempts, type(e).__name__, str(e)[:120], delay,
            )
            AIOPS_LLM_RETRIES_TOTAL.labels(result="retried").inc()
            await asyncio.sleep(delay)
