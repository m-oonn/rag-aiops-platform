"""运维 Agent 的 LLM 工厂(走 OpenAI compatible-mode,不用 ChatTongyi)。

为什么 Agent 侧单独建工厂、不复用 src/llm/llm_client.py:
  - RAG 路径用 ChatTongyi(走 dashscope 原生 SDK,只认通义 Qwen 系列);
  - Agent 路径要 function calling + 可切供应商,必须走 ChatOpenAI compatible-mode。
  探针(scripts/probe_llm.py)实测: qwen-max / deepseek-v3 经 compatible-mode 均支持
  tool_calls;deepseek-r1 是推理模型不返回 tool_calls,严禁用于 Agent。

单一事实来源: 模型名读 settings.AGENT_MODEL,地址/密钥读
settings.RESOLVED_LLM_API_BASE / RESOLVED_LLM_API_KEY(供应商无关,
支持 DeepSeek 官方 API: .env 里 LLM_API_BASE=https://api.deepseek.com + LLM_API_KEY=sk-xxx)。
"""

import asyncio

from langchain_openai import ChatOpenAI

from src.settings import settings
from src.utils.logger import logger
from src.utils.metrics import AIOPS_LLM_RETRIES_TOTAL


def create_agent_llm(
    model: str | None = None,
    temperature: float = 0.0,
    streaming: bool = False,
    callbacks: list | None = None,
) -> ChatOpenAI:
    """创建运维 Agent 用的 ChatOpenAI 实例(compatible-mode)。

    Args:
        model: 模型名;默认取 settings.AGENT_MODEL(deepseek-v3)。
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

    # thinking 模式会拒绝"强制 tool_choice",使 with_structured_output(method=
    # "function_calling") 报 400 并降级成正则抠 JSON;关闭后原生强制工具调用可用。
    # 供应商相关参数(DeepSeek 认 thinking.type),换供应商时置 AGENT_DISABLE_THINKING=False。
    extra_body = {"thinking": {"type": "disabled"}} if settings.AGENT_DISABLE_THINKING else None

    return ChatOpenAI(
        model=model or os.environ.get("AGENT_MODEL", settings.AGENT_MODEL),
        temperature=temperature,
        streaming=streaming,
        base_url=settings.RESOLVED_LLM_API_BASE,
        api_key=settings.RESOLVED_LLM_API_KEY,
        request_timeout=60,  # 网络慢/额度受限时快速失败,避免诊断链路被 LLM 卡死
        extra_body=extra_body,
        # 关键修复: httpx 默认 UA(python-httpx/x.y.z) 被 DashScope 拒绝导致读超时挂起,
        # 模拟 Python-urllib UA 后 0.6s 即通。所有 Agent LLM 调用必须携带该 UA。
        default_headers={"User-Agent": "Python-urllib/3.13"},
        callbacks=cbs or None,
    )


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
