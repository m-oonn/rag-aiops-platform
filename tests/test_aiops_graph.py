"""AIOps Plan-Execute-Replan 图执行的真实行为测试。

不整体 mock AIOpsService.execute，而是 mock 外部依赖（LLM、MCP 工具、知识库检索），
让 planner / executor / replanner 的真实协作逻辑进入测试。

注意：planner/executor/replanner 都在模块顶部 import 了依赖函数，
所以必须 patch 各模块的本地引用，而不是 patch 依赖函数的定义模块。
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.aiops import AIOpsService
from src.agent.aiops.planner import Plan
from src.agent.aiops.replanner import Act, Response


def _make_fake_tool(name: str, result: str):
    """构造支持 ainvoke 的假 MCP 工具。"""
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=result)
    return tool


def _make_executor_llm(tool_calls_sequence):
    """构造 executor 用的假 LLM(bind_tools 后返回的对象)。

    tool_calls_sequence 按顺序控制 ainvoke 返回值:
      - list: 带 tool_calls 的响应
      - str: 纯文本响应
    """
    call_iter = iter(tool_calls_sequence)

    async def _ainvoke(messages):
        item = next(call_iter)
        response = MagicMock()
        if isinstance(item, list):
            response.tool_calls = item
            response.content = ""
        else:
            response.tool_calls = []
            response.content = item
        return response

    llm = MagicMock()
    llm.ainvoke = _ainvoke
    return llm


def _make_base_llm(executor_llm):
    """构造 planner/executor/replanner 共用的假 LLM。"""
    base_llm = MagicMock()
    base_llm.bind_tools = MagicMock(return_value=executor_llm)
    base_llm.ainvoke = AsyncMock(return_value=MagicMock(content="", tool_calls=[]))
    base_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=AsyncMock()))
    return base_llm


async def _collect_events(aiter):
    """把异步生成器产出的事件收集成列表。"""
    events = []
    async for event in aiter:
        events.append(event)
    return events


def _structured_side_effect(plan_steps=None, act_action="respond", response_text="final report"):
    """返回一个 side_effect 函数，根据 schema 类型返回不同结构化结果。"""
    def side_effect(llm, schema, prompt, prompt_input):
        if schema is Plan:
            return Plan(steps=plan_steps or ["check cpu"])
        if schema is Act:
            return Act(action=act_action, new_steps=[])
        if schema is Response:
            return Response(response=response_text)
        raise ValueError(f"Unknown schema: {schema}")
    return side_effect


def _aiops_patches(base_llm, fake_tools, plan_steps=None, act_action="respond", response_text="final report"):
    """统一构造 AIOps 测试所需的 patch 上下文。

    必须 patch 各模块的本地引用，才能避免真实调用 OpenAI/MCP。
    """
    return (
        # planner 的本地引用
        patch("src.agent.aiops.planner.create_agent_llm", return_value=base_llm),
        patch("src.agent.aiops.planner.ainvoke_structured", side_effect=_structured_side_effect(
            plan_steps=plan_steps, act_action=act_action, response_text=response_text
        )),
        patch("src.agent.aiops.planner._retrieve_experience", return_value=""),
        patch("src.agent.aiops.planner.load_agent_tools", new_callable=AsyncMock, return_value=(fake_tools, None)),

        # executor 的本地引用
        patch("src.agent.aiops.executor.create_agent_llm", return_value=base_llm),
        patch("src.agent.aiops.executor.load_agent_tools", new_callable=AsyncMock, return_value=(fake_tools, None)),

        # replanner 的本地引用
        patch("src.agent.aiops.replanner.create_agent_llm", return_value=base_llm),
        patch("src.agent.aiops.replanner.ainvoke_structured", side_effect=_structured_side_effect(
            plan_steps=plan_steps, act_action=act_action, response_text=response_text
        )),
    )


@pytest.mark.asyncio
async def test_aiops_service_stream_emits_plan_step_report_complete():
    """AIOps 诊断流应按 plan -> step_complete -> report -> complete 顺序产出事件。"""
    service = AIOpsService()
    fake_tool = _make_fake_tool("check_cpu", "CPU usage: 15%")
    executor_llm = _make_executor_llm([
        [{"id": "tc_1", "name": "check_cpu", "args": {}}],
        "CPU is normal",
    ])
    base_llm = _make_base_llm(executor_llm)

    with ExitStack() as stack:
        for ctx in _aiops_patches(base_llm, [fake_tool], plan_steps=["check cpu"], response_text="CPU usage is healthy."):
            stack.enter_context(ctx)
        events = await _collect_events(service.execute("check cpu status", session_id="test-1"))

    event_types = [e["type"] for e in events]
    assert event_types == ["plan", "step_complete", "report", "complete"], f"unexpected event sequence: {event_types}"

    plan_event = events[0]
    assert plan_event["plan"] == ["check cpu"]

    step_event = events[1]
    assert step_event["current_step"] == "check cpu"

    report_event = events[2]
    assert report_event["report"] == "CPU usage is healthy."

    complete_event = events[3]
    assert complete_event["type"] == "complete"


@pytest.mark.asyncio
async def test_aiops_service_empty_input_yields_error_event():
    """空输入时应产出 error 事件而不是未处理异常。"""
    service = AIOpsService()
    fake_tool = _make_fake_tool("check_cpu", "CPU usage: 15%")
    executor_llm = _make_executor_llm([
        [{"id": "tc_1", "name": "check_cpu", "args": {}}],
        "CPU is normal",
    ])
    base_llm = _make_base_llm(executor_llm)

    with ExitStack() as stack:
        for ctx in _aiops_patches(base_llm, [fake_tool], plan_steps=["check cpu"], response_text="Report A"):
            stack.enter_context(ctx)
        events = await _collect_events(service.execute("", session_id="test-empty"))

    assert any(e["type"] == "error" for e in events), f"expected error event, got: {[e['type'] for e in events]}"


@pytest.mark.asyncio
async def test_aiops_service_session_isolation():
    """不同 session_id 之间的执行状态应互相隔离。"""
    service = AIOpsService()
    fake_tool = _make_fake_tool("check_cpu", "CPU usage: 15%")
    executor_llm = _make_executor_llm([
        [{"id": "tc_1", "name": "check_cpu", "args": {}}],
        "CPU is normal",
    ])
    base_llm = _make_base_llm(executor_llm)

    with ExitStack() as stack:
        for ctx in _aiops_patches(base_llm, [fake_tool], plan_steps=["check cpu"], response_text="Report A"):
            stack.enter_context(ctx)
        events_a = await _collect_events(service.execute("check cpu", session_id="session-a"))
        events_b = await _collect_events(service.execute("check cpu", session_id="session-b"))

    assert [e["type"] for e in events_a] == ["plan", "step_complete", "report", "complete"]
    assert [e["type"] for e in events_b] == ["plan", "step_complete", "report", "complete"]
# 不同 session 的报告内容应独立
    report_a = next(e for e in events_a if e["type"] == "report")["report"]
    report_b = next(e for e in events_b if e["type"] == "report")["report"]
    assert report_a == report_b == "Report A"
