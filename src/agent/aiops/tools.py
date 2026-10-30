"""运维 Agent 的工具装配:统一加载 MCP 工具。

工具来自 settings.MCP_SERVERS 的四个独立服务——monitor(指标 8104)、cls(日志 8103)、
knowledge_base(知识库 8105)、change(变更 8106);由 mcp_client 统一加载,任一服务不可达
时按服务粒度降级,不影响其余工具。

规划前经验检索按 EXPERIENCE_KB_IDS 中的库配置选本地 BM25 或原混检；显式范围无结果
不扩大检索。未指定范围保留原混检和本地 runbook 降级。调查中也可调用知识 MCP。
"""

import re
from copy import deepcopy

from langchain_core.tools import BaseTool, StructuredTool

from src.agent.mcp_client import load_mcp_tools_safe, load_tools_for_config
from src.agent.aiops.termcp_tools import wrap_termcp_tools
from src.settings import settings


def config_file_read_unavailable(step: str, tools: list) -> bool:
    """Recognize explicit file-read requests; actual tools still enforce permissions.

    shortcut: this covers explicit Chinese/English configuration-file reads,
    not arbitrary natural-language capability inference.
    """
    names = {tool.name for tool in tools}
    if {'shell_input', 'shell_key'} <= names:
        return False  # Existing terminal wrappers still require command approval.
    return bool(re.search(
        r'(?:打开|读取|查看|读出|翻看)[^。；;\n]{0,60}(?:配置文件|配置文档)'
        r'|(?:read|open|view)\b[^.;\n]{0,60}\b(?:config(?:uration)?[ -]file|settings[ -]file)\b',
        step, re.IGNORECASE))


def _knowledge_scope_values(scope) -> list[int]:
    if not isinstance(scope, (list, tuple)) or not scope or any(
            type(value) is not int or value <= 0 for value in scope):
        raise ValueError('knowledge scope must contain positive integer ids')
    return list(dict.fromkeys(scope))


def _scope_knowledge_tool(tool: BaseTool, scope: list[int]) -> BaseTool:
    """Give the model an allow-listed KB schema and enforce it before MCP."""
    original_schema = getattr(tool, 'args_schema', None)
    if not isinstance(original_schema, dict):
        get_schema = getattr(tool, 'get_input_schema', None)
        if get_schema is None:
            raise ValueError('knowledge tool input schema unavailable')
        original_schema = get_schema().model_json_schema()
    args_schema = deepcopy(original_schema)
    kb = args_schema.get('properties', {}).get('kb_id')
    if not isinstance(kb, dict):
        raise ValueError('knowledge tool schema has no kb_id')
    kb['enum'] = list(scope)
    kb.pop('default', None)
    required = list(args_schema.get('required', []))
    if len(scope) == 1:
        kb['default'] = scope[0]
        required = [key for key in required if key != 'kb_id']
    elif 'kb_id' not in required:
        required.append('kb_id')
    args_schema['required'] = required

    async def invoke(**kwargs):
        kb_id = kwargs.get('kb_id', scope[0] if len(scope) == 1 else None)
        if type(kb_id) is not int or kb_id not in scope:
            raise PermissionError(f'knowledge library outside configured scope; allowed kb_id: {scope}')
        return await tool.ainvoke({**kwargs, 'kb_id': kb_id})

    return StructuredTool.from_function(
        coroutine=invoke, name=tool.name,
        description=f'仅可检索已配置知识库 {scope}；资料不是现场证据。\n{tool.description}',
        args_schema=args_schema)


def scope_knowledge_tools(tools: list[BaseTool], scope) -> list[BaseTool]:
    """Wrap only the knowledge search tool; leave all other tools unchanged."""
    if scope is None:
        return tools
    values = _knowledge_scope_values(scope)
    return [_scope_knowledge_tool(tool, values) if tool.name == 'search_knowledge_base' else tool
            for tool in tools]


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
    if settings.EXPERIENCE_KB_IDS:
        try:
            selected = [int(value.strip()) for value in settings.EXPERIENCE_KB_IDS.split(',') if value.strip()]
            tools = scope_knowledge_tools(tools, selected)
        except ValueError:
            tools = [tool for tool in tools if tool.name != 'search_knowledge_base']
            err = f'{err or ""}; 知识库范围配置无效，检索工具未开放'.lstrip('; ')
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
