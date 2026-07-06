"""Agent 配置 schema 校验测试。

目标：把 AgentCreate/AgentUpdate 中无结构的 dict 字段改成 Pydantic 模型，
确保非法配置在请求入口就被拦截，而不是等到执行时才报错。
"""

import pytest
from pydantic import ValidationError

from src.api.routers.agent import AgentCreate, AgentUpdate


def test_create_agent_accepts_valid_tools_config():
    """合法的 MCP 工具配置应能创建 Agent。"""
    agent = AgentCreate(
        name="Test Agent",
        tools_config={
            "monitor": {
                "transport": "streamable_http",
                "url": "http://localhost:8003/mcp",
            },
            "cls": {
                "transport": "streamable_http",
                "url": "http://localhost:8004/mcp",
            },
        },
    )
    assert agent.tools_config is not None
    assert "monitor" in agent.tools_config
    assert agent.tools_config["monitor"].transport == "streamable_http"


def test_create_agent_rejects_invalid_transport_in_tools_config():
    """tools_config 中不支持的 transport 类型应触发校验错误。"""
    with pytest.raises(ValidationError):
        AgentCreate(
            name="Test Agent",
            tools_config={
                "monitor": {
                    "transport": "ftp",  # 非法
                    "url": "http://localhost:8003/mcp",
                },
            },
        )


def test_create_agent_rejects_missing_url_in_streamable_http():
    """streamable_http transport 缺少 url 时应触发校验错误。"""
    with pytest.raises(ValidationError):
        AgentCreate(
            name="Test Agent",
            tools_config={
                "monitor": {
                    "transport": "streamable_http",
                    # url 缺失
                },
            },
        )


def test_create_agent_accepts_valid_llm_config():
    """合法的 LLM 配置应能创建 Agent。"""
    agent = AgentCreate(
        name="Test Agent",
        llm_config={
            "model": "qwen-max",
            "temperature": 0.5,
            "max_tokens": 2048,
        },
    )
    assert agent.llm_config is not None
    assert agent.llm_config.model == "qwen-max"


def test_create_agent_rejects_invalid_llm_config_type():
    """llm_config 中字段类型错误时应触发校验错误。"""
    with pytest.raises(ValidationError):
        AgentCreate(
            name="Test Agent",
            llm_config={
                "temperature": "hot",  # 应为数字
            },
        )


def test_create_agent_accepts_valid_execution_config():
    """合法的执行配置应能创建 Agent。"""
    agent = AgentCreate(
        name="Test Agent",
        execution_config={
            "max_iterations": 5,
            "llm_timeout": 60.0,
            "tool_timeout": 30.0,
        },
    )
    assert agent.execution_config is not None
    assert agent.execution_config.max_iterations == 5


def test_create_agent_rejects_negative_timeout():
    """execution_config 中超时不能为负数。"""
    with pytest.raises(ValidationError):
        AgentCreate(
            name="Test Agent",
            execution_config={
                "llm_timeout": -10.0,
            },
        )


def test_update_agent_partial_config_still_validated():
    """AgentUpdate 中部分更新的配置同样应被校验。"""
    with pytest.raises(ValidationError):
        AgentUpdate(
            tools_config={
                "monitor": {
                    "transport": "unknown_transport",
                },
            },
        )
