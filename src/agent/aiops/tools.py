"""运维 Agent 的工具装配:统一加载 MCP 工具。

工具来自 settings.MCP_SERVERS 的四个独立服务——monitor(指标 8104)、cls(日志 8103)、
knowledge_base(知识库 8105)、change(变更 8106);由 mcp_client 统一加载,任一服务不可达
时按服务粒度降级,不影响其余工具。

另有一条不经工具装配的经验检索:planner 在规划前用 HybridRetriever(向量+BM25+RRF,
配 DashScopeReranker 重排)查一次知识库,把相关排查经验注入 prompt,查不到时降级到
本地 runbook(local_retrieval);同一条能力也可由 LLM 通过 knowledge_base 工具自主调用。
"""

from langchain_core.tools import BaseTool

from src.agent.mcp_client import load_mcp_tools_safe


async def load_agent_tools() -> tuple[list[BaseTool], str | None]:
    """加载运维 Agent 可用的全部工具(当前 = MCP 四服务工具)。

    Returns:
        (tools, error): 成功 error 为 None;MCP 全部不可达时 tools 为 []、error 可读。
    """
    return await load_mcp_tools_safe()
