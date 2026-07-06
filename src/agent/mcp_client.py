"""MCP 客户端封装(精简版,从 OnCall 的 app/agent/mcp_client.py 提炼)。

只做两件事,够 Phase 1 本地 mock 用:
  1) 全局单例:整个应用只建一个 MultiServerMCPClient,避免每次提问都重连 8003/8004
  2) 优雅降级:工具加载失败时返回 (空列表, 错误信息),而不是抛异常炸掉整条链

本版本补充(与 src/services/agent_tool_service.py 保持一致):
  - 对 get_tools() 增加超时控制,避免 MCP 不可用时请求挂死。
  - 提供 reset_mcp_client()/close_mcp_client(),支持重连与优雅关闭。
  - 加载失败时自动重置单例,下次调用会重新建连。

刻意没做(等接真实 Prometheus 再补,见下方 TODO):
  - 重试拦截器(指数退避):本地 127.0.0.1 几乎不失败,过早加只会拖慢 mock 调试
  - 异常链展开(format_exception_chain):并发多工具报错才需要,本地用不上
为什么分阶段:本地 mock 抽走了网络/数据的不确定性,代码可以很薄;接真实云环境
时不确定性回来了,那时再补抗噪能力。对的阶段做对的事(YAGNI)。
"""

import asyncio
import logging
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.settings import settings

logger = logging.getLogger("mcp_client")

# 全局单例(延迟初始化):模块级变量,整个进程共享同一个客户端实例
_mcp_client: Optional[MultiServerMCPClient] = None

# 默认超时(秒),与 agent_tool_service.py 保持一致
_DEFAULT_MCP_LOAD_TIMEOUT = 10.0


async def _with_timeout(coro, timeout: float, description: str):
    """包装协程,增加超时保护。超时时抛出可读异常。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise asyncio.TimeoutError(f"{description} 超时({timeout}s)") from e


def get_mcp_client() -> MultiServerMCPClient:
    """获取全局唯一的 MCP 客户端(单例)。第一次调用时创建,之后复用同一个。

    为什么单例:真实服务里每次用户提问都重建客户端会反复重连 8003/8004,又慢又费连接。
    单例 = 整个应用只建一次,大家复用。

    注意:adapters 0.1.0+ 起 MultiServerMCPClient 不再是上下文管理器,
    直接 MultiServerMCPClient(servers) new 出来即可用,不需要 async with / __aenter__。
    """
    global _mcp_client

    if _mcp_client is None:
        logger.info("创建新的 MultiServerMCPClient 连接 MCP 服务: %s", settings.MCP_SERVERS)
        _mcp_client = MultiServerMCPClient(settings.MCP_SERVERS)
    return _mcp_client


def reset_mcp_client() -> None:
    """重置全局单例,下次 get_mcp_client() 会重新创建连接。

    适用场景:MCP 服务重启后,旧连接可能失效,调用此方后下次自动重连。
    注意:本方法不会关闭旧 client,如需关闭请先用 close_mcp_client()。
    """
    global _mcp_client
    _mcp_client = None
    logger.info("MCP 客户端单例已重置,下次调用将重新建连")


def close_mcp_client() -> None:
    """关闭并清空当前全局 MCP 客户端。"""
    global _mcp_client
    if _mcp_client is not None:
        try:
            close_fn = getattr(_mcp_client, "close", None) or getattr(_mcp_client, "aclose", None)
            if close_fn is not None:
                asyncio.create_task(close_fn())
                logger.info("已关闭全局 MCP 客户端")
        except Exception as e:
            logger.warning("关闭全局 MCP 客户端时出错: %s", e)
        finally:
            _mcp_client = None


async def load_mcp_tools_safe() -> tuple[list[BaseTool], Optional[str]]:
    """加载 MCP 工具;失败时返回 (空列表, 错误信息),不向上抛异常(优雅降级)。

    好处:某个 MCP 服务挂了,Agent 还能用剩下能连上的工具,不至于整条链崩。

    Returns:
        (tools, error): 成功时 error 为 None;失败时 tools 为 [] 且 error 为可读信息。
    """
    try:
        client = get_mcp_client()
        tools = await _with_timeout(
            client.get_tools(),
            timeout=_DEFAULT_MCP_LOAD_TIMEOUT,
            description="加载 MCP 工具",
        )
        logger.info("成功加载 %d 个 MCP 工具", len(tools))
        return tools, None
    except Exception as e:
        # TODO(接真实环境): MCP 底层用 TaskGroup,异常常被包成 ExceptionGroup,
        #   到时搬 OnCall 的 format_exception_chain 递归展开,定位真实子异常。
        error_msg = f"{type(e).__name__}: {e}"
        logger.warning("加载 MCP 工具失败(已降级): %s", error_msg)
        # 失败后重置单例,下次重试会重新建连,避免长期持有坏连接
        reset_mcp_client()
        return [], error_msg


# TODO(接真实 Prometheus 时再补): retry_interceptor 指数退避重试 + get_mcp_client_with_retry
#   本地 mock 几乎不失败,先不加,避免调试 mock 时被拦截器绕晕。
