"""运维 Agent 的 LLM 工厂(走 OpenAI compatible-mode,不用 ChatTongyi)。

为什么 Agent 侧单独建工厂、不复用 src/llm/llm_client.py:
  - RAG 路径用 ChatTongyi(走 dashscope 原生 SDK,只认通义 Qwen 系列);
  - Agent 路径要 function calling + 可调 DeepSeek,必须走 ChatOpenAI compatible-mode。
  探针(scripts/probe_llm.py)实测: qwen-max / deepseek-v3 经 compatible-mode 均支持
  tool_calls;deepseek-r1 是推理模型不返回 tool_calls,严禁用于 Agent。

单一事实来源: 模型名读 settings.AGENT_MODEL,地址读 settings.DASHSCOPE_API_BASE,
改模型/改站点只动 settings,不动这里。
"""

from langchain_openai import ChatOpenAI

from src.settings import settings


def create_agent_llm(
    model: str | None = None,
    temperature: float = 0.0,
    streaming: bool = False,
) -> ChatOpenAI:
    """创建运维 Agent 用的 ChatOpenAI 实例(compatible-mode)。

    Args:
        model: 模型名;默认取 settings.AGENT_MODEL(deepseek-v3)。
        temperature: 默认 0,诊断要可复现、不要发散。
        streaming: 节点内部一次性 ainvoke 不需要流式;图层用 astream 做流式输出。

    Returns:
        配好 base_url / api_key 的 ChatOpenAI,可直接 bind_tools / with_structured_output。
    """
    import os  # noqa: E402
    return ChatOpenAI(
        model=model or os.environ.get("AGENT_MODEL", settings.AGENT_MODEL),
        temperature=temperature,
        streaming=streaming,
        base_url=settings.DASHSCOPE_API_BASE,
        api_key=settings.DASHSCOPE_API_KEY,
    )
