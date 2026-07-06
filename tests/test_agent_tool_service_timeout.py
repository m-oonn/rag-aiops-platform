"""Agent 工具服务超时包装测试。"""

import asyncio

import pytest

from src.services.agent_tool_service import _with_timeout


@pytest.mark.asyncio
async def test_with_timeout_returns_result_when_fast_enough():
    """协程在超时内完成时应返回其结果。"""
    async def fast_coro():
        return "done"

    result = await _with_timeout(fast_coro(), timeout=1.0, description="fast op")
    assert result == "done"


@pytest.mark.asyncio
async def test_with_timeout_raises_timeout_error_when_slow():
    """协程超时时应抛出包含可读描述的 TimeoutError。"""
    async def slow_coro():
        await asyncio.sleep(10.0)
        return "never"

    with pytest.raises(TimeoutError) as exc_info:
        await _with_timeout(slow_coro(), timeout=0.05, description="slow op")

    assert "slow op" in str(exc_info.value)
    assert "0.05s" in str(exc_info.value)
