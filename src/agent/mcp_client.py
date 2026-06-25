"""MCP 客户端封装(精简版,从 OnCall 的 app/agent/mcp_client.py 提炼)。

只做两件事,够 Phase 1 本地 mock 用:
  1) 全局单例:整个应用只建一个 MultiServerMCPClient,避免每次提问都重连 8003/8004
  2) 优雅降级:工具加载失败时返回 (空列表, 错误信息),而不是抛异常炸掉整条链

刻意没做(等接真实 Prometheus 再补,见下方 TODO):
  - 重试拦截器(指数退避):本地 127.0.0.1 几乎不失败,过早加只会拖慢 mock 调试
  - 异常链展开(format_exception_chain):并发多工具报错才需要,本地用不上
为什么分阶段:本地 mock 抽走了网络/数据的不确定性,代码可以很薄;接真实云环境
时不确定性回来了,那时再补抗噪能力。对的阶段做对的事(YAGNI)。
"""

import logging
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.settings import settings

logger = logging.getLogger("mcp_client")

# 全局单例(延迟初始化):模块级变量,整个进程共享同一个客户端实例
_mcp_client: Optional[MultiServerMCPClient] = None


def get_mcp_client() -> MultiServerMCPClient:
    """获取全局唯一的 MCP 客户端(单例)。第一次调用时创建,之后复用同一个。

    为什么单例:真实服务里每次用户提问都重建客户端会反复重连 8003/8004,又慢又费连接。
    单例 = 整个应用只建一次,大家复用。

    注意:adapters 0.1.0+ 起 MultiServerMCPClient 不再是上下文管理器,
    直接 MultiServerMCPClient(servers) new 出来即可用,不需要 async with / __aenter__。
    """
    global _mcp_client

    # ===== 你来填这个单例判断(本文件的核心)=====
    # 思路:_mcp_client 为 None 才创建(用 settings.MCP_SERVERS),否则直接返回老的
    # 1) if _mcp_client is None: 打条日志,赋值 MultiServerMCPClient(settings.MCP_SERVERS)
    # 2) return _mcp_client
    if _mcp_client is None:
        logger.info("创建新的 MultiServerMCPClient 连接 MCP 服务: %s", settings.MCP_SERVERS)
        _mcp_client = MultiServerMCPClient(settings.MCP_SERVERS)
    return _mcp_client
    # ============================================


async def load_mcp_tools_safe() -> tuple[list[BaseTool], Optional[str]]:
    """加载 MCP 工具;失败时返回 (空列表, 错误信息),不向上抛异常(优雅降级)。

    好处:某个 MCP 服务挂了,Agent 还能用剩下能连上的工具,不至于整条链崩。

    Returns:
        (tools, error): 成功时 error 为 None;失败时 tools 为 [] 且 error 为可读信息。
    """
    try:
        client = get_mcp_client()
        tools = await client.get_tools()
        logger.info("成功加载 %d 个 MCP 工具", len(tools))
        return tools, None
    except Exception as e:
        # TODO(接真实环境): MCP 底层用 TaskGroup,异常常被包成 ExceptionGroup,
        #   到时搬 OnCall 的 format_exception_chain 递归展开,定位真实子异常。
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("加载 MCP 工具失败: %s", error_msg)
        return [], error_msg


# TODO(接真实 Prometheus 时再补): retry_interceptor 指数退避重试 + get_mcp_client_with_retry
#   本地 mock 几乎不失败,先不加,避免调试 mock 时被拦截器绕晕。
