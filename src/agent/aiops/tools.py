"""运维 Agent 的工具装配:统一加载 MCP 工具。

工具来自 settings.MCP_SERVERS 的四个独立服务——monitor(指标 8104)、cls(日志 8103)、
knowledge_base(知识库 8105)、change(变更 8106);由 mcp_client 统一加载,任一服务不可达
时按服务粒度降级,不影响其余工具。

另有一条不经工具装配的经验检索:planner 在规划前用 HybridRetriever(向量+BM25+RRF,
配 DashScopeReranker 重排)查一次知识库,把相关排查经验注入 prompt,查不到时降级到
本地 runbook(local_retrieval);同一条能力也可由 LLM 通过 knowledge_base 工具自主调用。
"""

from langchain_core.tools import BaseTool

from src.agent.mcp_client import load_mcp_tools_safe, load_tools_for_config
from src.agent.aiops.termcp_tools import wrap_termcp_tools
from src.settings import settings


def investigation_tool_catalog(tools: list) -> list[dict]:
    """Describe only the tools actually loaded for this run."""
    return [{'name': tool.name, 'description': str(tool.description)[:600],
             'parameters': getattr(tool, 'args', {})} for tool in tools]


async def load_agent_tools(include_termcp: bool = False) -> tuple[list[BaseTool], str | None]:
    """加载运维 Agent 可用的全部工具(当前 = MCP 四服务工具)。

    Returns:
        (tools, error): 成功 error 为 None;MCP 全部不可达时 tools 为 []、error 可读。
    """
    tools, err = await load_mcp_tools_safe()
    if settings.PROBE_ENABLED:
        # Native target diagnostics must keep arbitrary network/POST probes out.
        tools = [tool for tool in tools if tool.name not in {
            'check_website', 'check_ports', 'check_service_health', 'check_api_endpoint',
        }]
    if not include_termcp or not settings.TERMCP_ENABLED:
        return tools, err
    # Autonomous target/dependency probes go through the collector's allowlist.
    # Existing website/API tools accept arbitrary hosts and even business POSTs.
    tools = [tool for tool in tools if tool.name not in {
        "check_website", "check_ports", "check_service_health", "check_api_endpoint",
    }]
    if settings.DIAGNOSTIC_ENABLED and settings.DIAGNOSTIC_TOKEN:
        diagnostic_tools, diagnostic_err = await load_tools_for_config({"diagnostic": {
            "transport": "streamable_http", "url": settings.MCP_DIAGNOSTIC_URL,
            "headers": {"Authorization": f"Bearer {settings.DIAGNOSTIC_TOKEN}"},
        }})
        tools.extend(diagnostic_tools)
        if diagnostic_err:
            err = f"{err or ''}; 现场诊断不可用: {diagnostic_err}"
    terminal_tools, terminal_err = await load_tools_for_config({"termcp": settings.MCP_TERMCP_SERVER})
    tools.extend(wrap_termcp_tools(terminal_tools))
    if terminal_err:
        err = f"{err}; Termcp 不可用: {terminal_err}" if err else f"Termcp 不可用: {terminal_err}"
    return tools, err
