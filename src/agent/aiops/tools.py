"""运维 Agent 的工具装配:统一加载 MCP 工具(指标/日志)。

简历版(甲)只用 MCP 工具(monitor 指标 + cls 日志);RAG 经验检索不做成 LangChain
工具,而是在 planner 里直接用现有 VectorRetriever 查一次注入 prompt(更简单,不必为
单一调用包一层 @tool)。将来要把检索也做成"工具"交给 LLM 自主调,再在这里补。
"""

from langchain_core.tools import BaseTool

from src.agent.mcp_client import load_mcp_tools_safe


async def load_agent_tools() -> tuple[list[BaseTool], str | None]:
    """加载运维 Agent 可用的全部工具(当前 = MCP 指标/日志)。

    Returns:
        (tools, error): 成功 error 为 None;MCP 全部不可达时 tools 为 []、error 可读。
    """
    return await load_mcp_tools_safe()
