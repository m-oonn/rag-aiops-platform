"""Plan-Execute-Replan 图装配 + 流式执行服务。

策略注入：replan_strategy 参数决定 replanner 节点的决策逻辑。
  默认: DefaultReplanStrategy（当前生产行为）
  Phase 3: DynamicClassificationStrategy（毕设创新）
"""

from typing import Any, AsyncGenerator, Dict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agent.aiops.executor import executor
from src.agent.aiops.planner import planner
from src.agent.aiops.replanner import replanner
from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.base import BaseReplanStrategy
from src.agent.aiops.strategies.default import DefaultReplanStrategy
from src.agent.aiops.strategies.dynamic_classification import DynamicClassificationStrategy
from src.settings import settings
from src.utils.logger import logger
from src.utils.tracing import trace_span

NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_REPLANNER = "replanner"


class AIOpsService:
    """运维诊断服务：封装 Plan-Execute-Replan 图，提供流式 execute()。

    Args:
        replan_strategy: 可选的 replanner 策略实例。不传则使用 DefaultReplanStrategy。
    """

    def __init__(self, replan_strategy: Optional[BaseReplanStrategy] = None) -> None:
        self.checkpointer = MemorySaver()
        self.replan_strategy = replan_strategy or DefaultReplanStrategy()
        self.graph = self._build_graph()
        logger.info("AIOpsService(Plan-Execute-Replan) 初始化完成，策略: %s",
                     type(self.replan_strategy).__name__)

    def _build_graph(self):
        workflow = StateGraph(PlanExecuteState)
        workflow.add_node(NODE_PLANNER, planner)
        workflow.add_node(NODE_EXECUTOR, executor)
        workflow.add_node(NODE_REPLANNER, replanner)

        workflow.set_entry_point(NODE_PLANNER)
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)

        def should_continue(state: PlanExecuteState) -> str:
            if state.get("response"):
                return END
            if state.get("plan"):
                return NODE_EXECUTOR
            return END

        workflow.add_conditional_edges(
            NODE_REPLANNER,
            should_continue,
            {NODE_EXECUTOR: NODE_EXECUTOR, END: END},
        )
        return workflow.compile(checkpointer=self.checkpointer)

    async def execute(
        self, user_input: str, session_id: str = "default"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async with trace_span("aiops.execute", session_id=session_id):
            logger.info(f"[aiops][{session_id}] 开始诊断: {user_input}")

            if not user_input or not user_input.strip():
                logger.warning(f"[aiops][{session_id}] 输入为空,拒绝执行")
                yield {
                    "type": "error",
                    "stage": "validation_error",
                    "message": "诊断输入不能为空,请描述当前遇到的故障现象",
                }
                return

            initial: PlanExecuteState = {
                "input": user_input,
                "plan": [],
                "past_steps": [],
                "response": "",
            }
            config = {"configurable": {"thread_id": session_id}}

            try:
                async for event in self.graph.astream(
                    input=initial, config=config, stream_mode="updates"
                ):
                    for node_name, node_output in event.items():
                        yield self._format_event(node_name, node_output)

                final_state = self.graph.get_state(config)
                final_response = ""
                if final_state and final_state.values:
                    final_response = final_state.values.get("response", "")
                yield {
                    "type": "complete",
                    "stage": "complete",
                    "message": "诊断完成",
                    "response": final_response,
                }
                logger.info(f"[aiops][{session_id}] 诊断完成")
            except Exception as e:
                logger.error(f"[aiops][{session_id}] 诊断失败: {e}", exc_info=True)
                yield {"type": "error", "stage": "error", "message": f"诊断出错: {e}"}

    @staticmethod
    def _format_event(node_name: str, state: Dict | None) -> Dict[str, Any]:
        state = state or {}
        if node_name == NODE_PLANNER:
            plan = state.get("plan", [])
            return {
                "type": "plan",
                "stage": "plan_created",
                "message": f"诊断计划已制定,共 {len(plan)} 步",
                "plan": plan,
            }
        if node_name == NODE_EXECUTOR:
            past_steps = state.get("past_steps", [])
            plan = state.get("plan", [])
            if past_steps:
                last_step, _ = past_steps[-1]
                done = len(past_steps)
                return {
                    "type": "step_complete",
                    "stage": "step_executed",
                    "message": f"步骤完成 ({done}/{done + len(plan)})",
                    "current_step": last_step,
                    "remaining_steps": len(plan),
                }
            return {"type": "status", "stage": "executor", "message": "执行步骤中"}
        if node_name == NODE_REPLANNER:
            response = state.get("response", "")
            plan = state.get("plan", [])
            if response:
                return {
                    "type": "report",
                    "stage": "final_report",
                    "message": "诊断报告已生成",
                    "report": response,
                }
            return {
                "type": "status",
                "stage": "replanner",
                "message": "继续执行剩余步骤" if plan else "准备生成报告",
                "remaining_steps": len(plan),
            }
        return {"type": "status", "stage": node_name, "message": f"{node_name} 执行中"}


# 全局单例（根据 settings 自动选择策略）
_default_strategy = DynamicClassificationStrategy() if settings.ENABLE_DYNAMIC_CLASSIFICATION else None
aiops_service = AIOpsService(replan_strategy=_default_strategy)
