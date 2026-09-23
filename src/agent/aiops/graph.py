"""Plan-Execute-Replan 图装配 + 流式执行服务。

策略注入：replan_strategy 参数决定 replanner 节点的决策逻辑。
  默认: DefaultReplanStrategy（当前生产行为）
  Phase 3: DynamicClassificationStrategy（毕设创新）

HITL（人在回路，settings.ENABLE_HITL）：
  拓扑追加 human_review 节点——replanner 决定 respond 后先挂起等待人工审批，
  审批端点通过 Command(resume=...) 恢复。挂起期间每线程持有独立策略实例与
  编译图（_thread_runs），保证假设空间跨 HTTP 请求存活；运行/审批记录落库
  （run_store / aiops_runs / aiops_approvals）。
"""

from typing import Any, AsyncGenerator, Dict, Optional
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from src.agent.aiops import run_store
from src.agent.aiops.executor import executor
from src.agent.aiops.human_review import build_human_review_node
from src.agent.aiops.planner import planner
from src.agent.aiops.replanner import create_replanner
from src.agent.aiops.roles import ROLE_EXECUTOR, ROLE_PLANNER, ROLE_REPLANNER
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
NODE_HUMAN_REVIEW = "human_review"


class AIOpsService:
    """运维诊断服务：封装 Plan-Execute-Replan 图，提供流式 execute() / resume()。

    Args:
        replan_strategy: 可选的 replanner 策略实例。不传则使用 DefaultReplanStrategy。
    """

    def __init__(self, replan_strategy: Optional[BaseReplanStrategy] = None) -> None:
        self.checkpointer = MemorySaver()
        self.replan_strategy = replan_strategy or DefaultReplanStrategy()
        self.graph = self._build_graph(self.replan_strategy)
        # HITL：thread_id -> (strategy, compiled_graph)，挂起期间策略状态跨请求存活
        self._thread_runs: Dict[str, tuple] = {}
        logger.info("AIOpsService(Plan-Execute-Replan) 初始化完成，策略: %s，HITL: %s",
                     type(self.replan_strategy).__name__, settings.ENABLE_HITL)

    def _create_strategy(self) -> BaseReplanStrategy:
        """按 settings 创建策略实例（HITL 每线程独立实例）。"""
        return (DynamicClassificationStrategy() if settings.ENABLE_DYNAMIC_CLASSIFICATION
                else DefaultReplanStrategy())

    def _build_graph(self, strategy: BaseReplanStrategy):
        """装配 Plan-Execute-Replan 图；HITL 开启时追加 human_review 节点。"""
        workflow = StateGraph(PlanExecuteState)
        workflow.add_node(NODE_PLANNER, planner)
        workflow.add_node(NODE_EXECUTOR, executor)
        workflow.add_node(NODE_REPLANNER, create_replanner(strategy))

        workflow.set_entry_point(NODE_PLANNER)
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)

        if settings.ENABLE_HITL:
            workflow.add_node(NODE_HUMAN_REVIEW, build_human_review_node())

            def should_continue(state: PlanExecuteState) -> str:
                if state.get("response"):
                    return NODE_HUMAN_REVIEW
                if state.get("plan"):
                    return NODE_EXECUTOR
                return END

            def after_review(state: PlanExecuteState) -> str:
                return END if state.get("response") else NODE_EXECUTOR

            workflow.add_conditional_edges(
                NODE_REPLANNER,
                should_continue,
                {NODE_EXECUTOR: NODE_EXECUTOR, NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW, END: END},
            )
            workflow.add_conditional_edges(
                NODE_HUMAN_REVIEW,
                after_review,
                {NODE_EXECUTOR: NODE_EXECUTOR, END: END},
            )
        else:

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

    async def _stream_events(
        self, graph, config, input
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """统一的事件流封装：跳过 __interrupt__ 内部事件，格式化节点事件。"""
        async for event in graph.astream(input, config, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    continue
                yield self._format_event(node_name, node_output)

    def _yield_pending_review(self, thread_id: str, draft: str) -> Dict[str, Any]:
        return {
            "type": "pending_review",
            "stage": "pending_review",
            "thread_id": thread_id,
            "message": "报告草稿已生成, 等待人工审批",
            "draft": draft,
        }

    async def execute(
        self, user_input: str, session_id: str = "default", user_id: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """开始一次诊断（流式）。

        HITL 开启时：每线程独立策略+编译图（假设空间跨请求存活），并落运行记录；
        非 HITL：复用全局单例策略并 reset（原行为，回归兼容）。
        """
        # 每次诊断使用唯一 thread_id,防止 MemorySaver 累积 past_steps
        unique_session = f"{session_id}-{int(time.time() * 1000)}"

        if settings.ENABLE_HITL:
            strategy = self._create_strategy()
            graph = self._build_graph(strategy)
            self._thread_runs[unique_session] = (strategy, graph)
            run_store.create_run(unique_session, user_id, user_input)
        else:
            # 会话隔离: 策略实例跨诊断复用(全局单例),必须先清理上一轮的有状态内存
            reset = getattr(self.replan_strategy, "reset", None)
            if callable(reset):
                reset()
            graph = self.graph

        async with trace_span("aiops.execute", session_id=unique_session):
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
            config = {"configurable": {"thread_id": unique_session}}

            try:
                async for event in self._stream_events(graph, config, initial):
                    yield event

                final_state = graph.get_state(config)

                # HITL：检测 human_review 挂起 → 待审批
                if (settings.ENABLE_HITL and final_state
                        and NODE_HUMAN_REVIEW in (final_state.next or ())):
                    draft = (final_state.values or {}).get("response", "")
                    run_store.mark_pending_review(unique_session, draft)
                    logger.info(f"[aiops][{session_id}] 报告草稿待人工审批")
                    yield self._yield_pending_review(unique_session, draft)
                    return

                final_response = ""
                if final_state and final_state.values:
                    final_response = final_state.values.get("response", "")
                if settings.ENABLE_HITL:
                    run_store.mark_completed(unique_session, final_response)
                    self._thread_runs.pop(unique_session, None)
                yield {
                    "type": "complete",
                    "stage": "complete",
                    "message": "诊断完成",
                    "response": final_response,
                    "hypothesis_space": (final_state.values.get("hypothesis_space", [])
                                         if final_state and final_state.values else []),
                }
                logger.info(f"[aiops][{session_id}] 诊断完成")
            except Exception as e:
                logger.error(f"[aiops][{session_id}] 诊断失败: {e}", exc_info=True)
                if settings.ENABLE_HITL:
                    run_store.mark_failed(unique_session, str(e))
                    self._thread_runs.pop(unique_session, None)
                yield {"type": "error", "stage": "error", "message": f"诊断出错: {e}"}

    async def resume(
        self, thread_id: str, decision: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """恢复挂起的诊断（HITL 审批后调用）。

        Args:
            thread_id: execute() 挂起时下发的 thread_id。
            decision: {"action": "approve"|"reject", "instruction": str|None}。
        """
        run = self._thread_runs.get(thread_id)
        if not run:
            logger.warning(f"[aiops] 恢复失败: 线程 {thread_id} 不存在或已过期")
            yield {
                "type": "error",
                "stage": "not_found",
                "message": f"诊断 {thread_id} 不存在或已过期",
            }
            return

        _strategy, graph = run
        config = {"configurable": {"thread_id": thread_id}}
        async with trace_span("aiops.resume", session_id=thread_id):
            logger.info(f"[aiops] 恢复诊断 {thread_id}: {decision}")
            try:
                async for event in self._stream_events(graph, config, Command(resume=decision)):
                    yield event

                final_state = graph.get_state(config)
                # 驳回重诊后再次 respond → 再次挂起等待审批
                if final_state and NODE_HUMAN_REVIEW in (final_state.next or ()):
                    draft = (final_state.values or {}).get("response", "")
                    run_store.mark_pending_review(thread_id, draft)
                    yield self._yield_pending_review(thread_id, draft)
                    return

                final_response = (final_state.values or {}).get("response", "") if final_state else ""
                run_store.mark_completed(thread_id, final_response)
                self._thread_runs.pop(thread_id, None)
                yield {
                    "type": "complete",
                    "stage": "complete",
                    "message": "诊断完成",
                    "response": final_response,
                }
                logger.info(f"[aiops] 诊断恢复完成 {thread_id}")
            except Exception as e:
                logger.error(f"[aiops] 恢复诊断失败: {e}", exc_info=True)
                run_store.mark_failed(thread_id, str(e))
                self._thread_runs.pop(thread_id, None)
                yield {"type": "error", "stage": "error", "message": f"恢复诊断出错: {e}"}

    @staticmethod
    def _format_event(node_name: str, state: Dict | None) -> Dict[str, Any]:
        state = state or {}
        if node_name == NODE_PLANNER:
            plan = state.get("plan", [])
            return {
                "type": "plan",
                "stage": "plan_created",
                "role": ROLE_PLANNER,
                "message": f"诊断计划已制定,共 {len(plan)} 步",
                "plan": plan,
            }
        if node_name == NODE_EXECUTOR:
            past_steps = state.get("past_steps", [])
            plan = state.get("plan", [])
            if past_steps:
                last_step, _ = past_steps[-1]
                # updates 模式下 state 是 executor 的增量输出, past_steps 仅含本轮步骤;
                # 累计进度由 executor 按输入历史计算后通过 _step_progress 携带。
                progress = state.get("_step_progress")
                if progress:
                    done, total = progress.get("done"), progress.get("total")
                    message = f"步骤完成 ({done}/{total})"
                else:
                    done = len(past_steps)
                    total = done + len(plan)
                    message = f"步骤完成 ({done}/{total})"
                return {
                    "type": "step_complete",
                    "stage": "step_executed",
                    "role": ROLE_EXECUTOR,
                    "message": message,
                    "done": done,          # 累计已完成步数(前端进度条按此对齐)
                    "total": total,        # 计划总步数
                    "current_step": last_step,
                    "remaining_steps": len(plan),
                }
            return {"type": "status", "stage": "executor", "role": ROLE_EXECUTOR, "message": "执行步骤中"}
        if node_name == NODE_REPLANNER:
            response = state.get("response", "")
            plan = state.get("plan", [])
            branches = state.get("sidebar_branches", [])
            running = sum(1 for b in branches if b.get("status") == "running")
            sidebar_note = f"，旁开支线 {running} 条" if branches else ""
            if response:
                # HITL 开启时 replanner 产出的是"草稿"，最终报告需人工审批
                if settings.ENABLE_HITL:
                    return {
                        "type": "draft",
                        "stage": "draft_ready",
                        "role": ROLE_REPLANNER,
                        "message": "报告草稿已生成",
                        "report": response,
                    }
                return {
                    "type": "report",
                    "stage": "final_report",
                    "role": ROLE_REPLANNER,
                    "message": "诊断报告已生成",
                    "report": response,
                }
            return {
                "type": "status",
                "stage": "replanner",
                "role": ROLE_REPLANNER,
                "message": f"继续执行剩余步骤{sidebar_note}" if plan else f"准备生成报告{sidebar_note}",
                "remaining_steps": len(plan),
            }
        return {"type": "status", "stage": node_name, "role": node_name, "message": f"{node_name} 执行中"}


# 全局单例（根据 settings 自动选择策略）
_default_strategy = DynamicClassificationStrategy() if settings.ENABLE_DYNAMIC_CLASSIFICATION else None
aiops_service = AIOpsService(replan_strategy=_default_strategy)
