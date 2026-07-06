"""MCP 客户端统一封装（全局单例 + per-config 缓存）。

提供两层 API：
  - 固定配置层（AIOps 用）：get_mcp_client() / load_mcp_tools_safe()
    全局单例，读 settings.MCP_SERVERS。整个应用只建一次。
  - 动态配置层（用户 Agent 用）：get_mcp_client_for_config() / load_tools_for_config()
    按 tools_config 字典缓存 MultiServerMCPClient，不同配置不共享连接。

设计原则：
  - 超时、错误处理、失败后重置逻辑只在此文件，不散落到各消费方。
  - 加载失败返回 (空列表, 错误信息) 而非抛异常，上游自行决定是否降级。
"""

import asyncio
import json
import logging
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.settings import settings

logger = logging.getLogger("mcp_client")

# ── 全局单例（固定配置，AIOps 用） ──────────────────────────────
_mcp_client: Optional[MultiServerMCPClient] = None

# ── per-config 缓存（动态配置，用户 Agent 用） ────────────────────
_config_clients: dict[str, MultiServerMCPClient] = {}

# ── 默认超时（秒） ─────────────────────────────────────────────
_DEFAULT_MCP_LOAD_TIMEOUT = 10.0


async def _with_timeout(coro, timeout: float, description: str):
    """包装协程，增加超时保护。超时时抛出可读异常。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise asyncio.TimeoutError(f"{description} 超时({timeout}s)") from e


def _tools_config_key(tools_config: dict) -> str:
    """把 tools_config 转成可哈希的字符串 key，用于 client 缓存。"""
    return json.dumps(tools_config, sort_keys=True, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 固定配置层——全局单例（AIOps 消费）
# ═══════════════════════════════════════════════════════════════


def get_mcp_client() -> MultiServerMCPClient:
    """获取全局唯一的 MCP 客户端（单例）。读 settings.MCP_SERVERS。"""
    global _mcp_client
    if _mcp_client is None:
        logger.info("创建新的 MultiServerMCPClient 连接 MCP 服务: %s", settings.MCP_SERVERS)
        _mcp_client = MultiServerMCPClient(settings.MCP_SERVERS)
    return _mcp_client


async def load_mcp_tools_safe() -> tuple[list[BaseTool], Optional[str]]:
    """加载全局单例 MCP 工具；失败时返回 (空列表, 错误信息)，不抛异常。

    Returns:
        (tools, error): 成功时 error 为 None；失败时 tools 为 [] 且 error 为可读信息。
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
        error_msg = f"{type(e).__name__}: {e}"
        logger.warning("加载 MCP 工具失败(已降级): %s", error_msg)
        reset_mcp_client()
        return [], error_msg


def reset_mcp_client() -> None:
    """重置全局单例，下次 get_mcp_client() 会重新创建连接。"""
    global _mcp_client
    _mcp_client = None
    logger.info("全局 MCP 客户端单例已重置，下次调用将重新建连")


# ═══════════════════════════════════════════════════════════════
# 动态配置层——per-config 缓存（用户 Agent 消费）
# ═══════════════════════════════════════════════════════════════


def get_mcp_client_for_config(tools_config: dict) -> MultiServerMCPClient:
    """获取指定 tools_config 对应的 MCP 客户端（有缓存则复用）。

    同一份 tools_config（JSON 序列化相同）共享同一个 MultiServerMCPClient，
    避免重复建连。不同配置各拥有独立连接。
    """
    if not tools_config:
        raise ValueError("tools_config 为空，无法创建 MCP 客户端")
    cache_key = _tools_config_key(tools_config)
    client = _config_clients.get(cache_key)
    if client is None:
        logger.info("创建 per-config MultiServerMCPClient: %s", cache_key[:60])
        client = MultiServerMCPClient(tools_config)
        _config_clients[cache_key] = client
    return client


def close_client_for_config(tools_config: dict) -> None:
    """关闭指定 tools_config 对应的 MCP client（若存在）并清除缓存。"""
    cache_key = _tools_config_key(tools_config)
    client = _config_clients.pop(cache_key, None)
    if client is not None:
        _close_client(client, f"tools_config({cache_key[:40]})")


async def load_tools_for_config(
    tools_config: dict,
    timeout: float = _DEFAULT_MCP_LOAD_TIMEOUT,
) -> tuple[list[BaseTool], Optional[str]]:
    """按 tools_config 加载 MCP 工具。

    与 load_mcp_tools_safe() 行为一致，区别在于使用 per-config 客户端。
    返回 (tools, error)，不抛异常。
    """
    if not tools_config:
        return [], None
    cache_key = _tools_config_key(tools_config)
    try:
        client = get_mcp_client_for_config(tools_config)
        tools = await _with_timeout(
            client.get_tools(),
            timeout=timeout,
            description=f"加载 per-config MCP 工具",
        )
        logger.info("per-config 加载 %d 个 MCP 工具 (key=%s)", len(tools), cache_key[:40])
        return tools, None
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.warning("per-config 加载 MCP 工具失败(key=%s): %s", cache_key[:40], error_msg)
        # 加载失败时清掉缓存，下次重试会重新建连
        _config_clients.pop(cache_key, None)
        return [], error_msg


# ═══════════════════════════════════════════════════════════════
# 公共清理
# ═══════════════════════════════════════════════════════════════


def _close_client(client: Any, label: str) -> None:
    """安全关闭一个 MCP client。"""
    try:
        close_fn = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close_fn is not None:
            asyncio.create_task(close_fn())
            logger.info("已关闭 MCP client (%s)", label)
    except Exception as e:
        logger.warning("关闭 MCP client (%s) 时出错: %s", label, e)


def close_mcp_client() -> None:
    """关闭并清空全局单例 MCP 客户端。"""
    global _mcp_client
    if _mcp_client is not None:
        _close_client(_mcp_client, "全局单例")
        _mcp_client = None


def close_all_clients() -> None:
    """关闭所有 MCP 客户端（全局单例 + per-config 缓存）。应用退出时调用。"""
    close_mcp_client()
    for cache_key in list(_config_clients.keys()):
        client = _config_clients.pop(cache_key, None)
        if client is not None:
            _close_client(client, f"config({cache_key[:40]})")
    logger.info("所有 MCP 客户端已关闭")
