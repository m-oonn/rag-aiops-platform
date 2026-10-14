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

from langchain_openai import ChatOpenAI

from src.settings import settings


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
