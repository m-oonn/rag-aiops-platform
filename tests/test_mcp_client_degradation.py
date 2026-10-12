"""MCP 工具加载的降级容错测试。

锁死纪律: 单个服务(如可选的知识库 8105 / 变更 8106)不可用时,不得把其余可用服务的
工具一起拖下水 —— 整体加载失败后应降级为**逐服务加载**,能连上几个返回几个,
并在 error 里说明哪些服务缺席;全部不可用才返回空列表。
"""

from types import SimpleNamespace

import pytest

from src.agent import mcp_client


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeClient:
    """模拟 MultiServerMCPClient: 被配置的任一服务在 fail 集合中即整体抛错。"""

    def __init__(self, servers, fail):
        self._servers = servers
        self._fail = fail

    async def get_tools(self):
        for name in self._servers:
            if name in self._fail:
                raise RuntimeError(f"server {name} unreachable")
        return [_FakeTool(f"{name}-tool") for name in self._servers]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """用受控的服务表替换 settings,并在前后清理全局单例缓存。"""
    mcp_client.reset_mcp_client()
    monkeypatch.setattr(
        mcp_client,
        "settings",
        SimpleNamespace(MCP_SERVERS={
            "monitor": {"transport": "streamable_http", "url": "http://x/monitor"},
            "cls": {"transport": "streamable_http", "url": "http://x/cls"},
            "knowledge_base": {"transport": "streamable_http", "url": "http://x/kb"},
        }),
    )
    yield
    mcp_client.reset_mcp_client()


def _install(monkeypatch, fail):
    monkeypatch.setattr(
        mcp_client, "MultiServerMCPClient",
        lambda servers: _FakeClient(servers, fail),
    )


@pytest.mark.asyncio
async def test_all_services_up_returns_all_tools(monkeypatch):
    _install(monkeypatch, fail=set())
    tools, err = await mcp_client.load_mcp_tools_safe()
    assert err is None
    assert {t.name for t in tools} == {"monitor-tool", "cls-tool", "knowledge_base-tool"}


@pytest.mark.asyncio
async def test_one_service_down_degrades_but_keeps_others(monkeypatch):
    """知识库不可用时,指标/日志工具必须照常返回,并说明缺席服务。"""
    _install(monkeypatch, fail={"knowledge_base"})
    tools, err = await mcp_client.load_mcp_tools_safe()
    assert {t.name for t in tools} == {"monitor-tool", "cls-tool"}
    assert err and "knowledge_base" in err
    assert "部分服务不可用" in err


@pytest.mark.asyncio
async def test_all_services_down_returns_empty(monkeypatch):
    _install(monkeypatch, fail={"monitor", "cls", "knowledge_base"})
    tools, err = await mcp_client.load_mcp_tools_safe()
    assert tools == []
    assert err and "全部 MCP 服务不可用" in err