"""Executor 节点:执行计划中的下一个步骤。

设计取舍:
  - 无工具时让 LLM 基于现有信息直接分析,不反问用户(反问在 demo 里是坏体验);
  - 有工具时 bind_tools + 手动工具执行(绕过 ToolNode 与 langchain-mcp-adapters
    的配置键兼容问题);
  - 执行完移除该步、把 (步骤, 结果) 追加进 past_steps。

注意:langchain-mcp-adapters 0.2.1 的 MCP 工具(StructuredTool)不含 config 属性,
而 langgraph-prebuilt>=1.1 的 ToolNode 强制要求 config → Missing required
config key 'N/A' for 'tools'。故手写工具调用,不依赖 ToolNode。
"""

import asyncio
import time
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops_llm import create_agent_llm
from src.utils.logger import logger

_EXECUTOR_SYSTEM = """你是资深运维诊断专家,负责执行单个诊断步骤。

原则:
1. 理解步骤目标;
2. 有可用工具就调用工具获取真实数据;无工具则基于你的运维知识给出合理分析;
3. **调用工具时,必须使用 bind_tools 注册的实际参数名**(如 start_time/end_time/interval),
   步骤描述中若提到不存在的参数名(如 duration),忽略它,以工具 schema 为准;
4. 结果要具体可操作,不要反问用户或要求提供更多信息;
5. 只返回实际获取的信息或基于知识的分析,不要编造数据;
6. 专注当前步骤,不考虑其他任务。"""

_NO_TOOLS_WARNING = """
⚠️ 重要提醒：当前没有可用的监控/日志工具，你无法获取任何真实系统数据。
在回答时你必须：
- 明确声明"以下分析基于通用运维经验，未获取到实际监控数据"；
- 不要编造具体的 CPU 数值、内存数值、日志内容等；
- 给出的建议应标注为"排查建议"而非"诊断结论"。"""

_TOOLS_CACHE_TTL = 30.0  # 工具列表缓存过期时间(秒)
_tools_cache: tuple[list, str | None] | None = None
_tools_cache_at: float = 0.0
_TOOL_INVOKE_TIMEOUT = 15.0  # 单个工具调用超时(秒)


def _build_tool_map(tools: list) -> dict[str, Any]:
    """把工具列表建成 {name: tool} 字典,便于按 name 查找。"""
    return {t.name: t for t in tools}


async def _get_tools_cached() -> tuple[list, str | None]:
    """获取工具列表,30s TTL 模块级缓存。"""
    global _tools_cache, _tools_cache_at
    now = time.monotonic()
    if _tools_cache is not None and (now - _tools_cache_at) < _TOOLS_CACHE_TTL:
        return _tools_cache
    tools, err = await load_agent_tools()
    if err:
        logger.warning(f"[executor] MCP 工具加载失败: {err}")
        _tools_cache = ([], err)
    else:
        _tools_cache = (tools, None)
    _tools_cache_at = now
    return _tools_cache


async def _run_single_tool(tc: dict, tool_map: dict) -> ToolMessage:
    """执行单个工具调用(带超时保护),返回 ToolMessage。"""
    tool_name = tc.get("name", "")
    tool_args = tc.get("args", {})
    tool_id = tc.get("id", "")
    tool = tool_map.get(tool_name)

    if not tool:
        content = f"工具 '{tool_name}' 不存在,跳过"
    else:
        try:
            result = await asyncio.wait_for(
                tool.ainvoke(tool_args),
                timeout=_TOOL_INVOKE_TIMEOUT,
            )
            content = str(result) if not isinstance(result, str) else result
        except asyncio.TimeoutError:
            content = f"工具 '{tool_name}' 调用超时(>{_TOOL_INVOKE_TIMEOUT}s)，请检查该服务是否正常运行"
            logger.warning("[executor] 工具 '%s' 调用超时", tool_name)
        except ConnectionError as e:
            content = f"工具 '{tool_name}' 连接失败(服务可能未启动): {e}"
            logger.warning("[executor] 工具 '%s' 连接失败: %s", tool_name, e)
        except Exception as e:
            content = f"工具 '{tool_name}' 调用失败: {e}"
            logger.warning("[executor] 工具 '%s' 调用异常: %s", tool_name, e)

    logger.info(f"[executor] 工具 '{tool_name}' 调用完成,结果长度 {len(content)}")
    return ToolMessage(content=content, tool_call_id=tool_id)


async def _run_tool_calls(tool_calls: list, tool_map: dict) -> list:
    """手动执行多个工具调用,返回 ToolMessage 列表。

    独立的工具调用之间没有依赖,并发执行可以缩短多工具诊断链路耗时。
    返回顺序与输入顺序一致,保证 LLM 回填时 tool_call_id 能对应上。
    """
    return await asyncio.gather(*(_run_single_tool(tc, tool_map) for tc in tool_calls))


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """执行节点:执行 plan[0],结果写入 past_steps。"""
    logger.info("=== Executor:执行步骤 ===")
    plan = state.get("plan", [])
    if not plan:
        logger.info("[executor] 计划为空,跳过")
        return {}

    task = plan[0]
    logger.info(f"[executor] 当前步骤: {task}")

    try:
        tools, err = await _get_tools_cached()

        tool_map = _build_tool_map(tools)
        llm = create_agent_llm(temperature=0)
        llm_with_tools = llm.bind_tools(tools) if tools else llm

        # 无工具时注入数据诚实性警告
        sys_content = _EXECUTOR_SYSTEM
        if not tools:
            sys_content += _NO_TOOLS_WARNING

        messages = [
            SystemMessage(content=sys_content),
            HumanMessage(content=f"请执行以下诊断步骤: {task}"),
        ]

        llm_response = await llm_with_tools.ainvoke(messages)
        tool_calls = getattr(llm_response, "tool_calls", None)

        if tool_calls:
            logger.info(f"[executor] 检测到 {len(tool_calls)} 个工具调用")
            # 手动执行工具(绕过 ToolNode)
            messages.append(llm_response)
            tool_msgs = await _run_tool_calls(tool_calls, tool_map)
            messages.extend(tool_msgs)
            # 工具结果回填给 LLM 生成最终答案
            final = await llm_with_tools.ainvoke(messages)
            result = final.content if hasattr(final, "content") else str(final)
        else:
            logger.info("[executor] 未调用工具,直接返回 LLM 输出")
            result = llm_response.content if hasattr(llm_response, "content") else str(llm_response)

        result = result if isinstance(result, str) else str(result)
        logger.info(f"[executor] 步骤完成,结果长度 {len(result)}")
        return {"plan": plan[1:], "past_steps": [(task, result)]}

    except Exception as e:
        logger.warning("[executor] 执行步骤 '%s' 异常降级: %s", task, e)
        return {"plan": plan[1:], "past_steps": [(task, f"执行步骤 '{task}' 时遇到异常: {e}")]}
