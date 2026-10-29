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
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from src.agent.aiops import run_store
from src.agent.aiops.events import (
    investigation_summary,
    make_complete_event,
    make_draft_event,
    make_error_event,
    make_pending_review_event,
    make_plan_event,
    make_report_event,
    make_status_event,
    make_step_complete_event,
    make_evidence_event,
)
from src.agent.aiops.executor import executor
from src.agent.aiops.termcp_tools import (
    TerminalApprovalStatusError, clear_terminal_context, terminal_scope, verify_terminal_approval,
)
from src.agent.aiops.human_review import build_human_review_node
from src.agent.aiops.planner import planner
from src.agent.aiops.replanner import create_replanner
from src.agent.aiops.roles import ROLE_EXECUTOR, ROLE_REPLANNER
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
NODE_TERMINAL_REVIEW = "terminal_review"


def _diagnostic_extras(final_state) -> Dict[str, Any]:
    """从终态抽取供前端可视化的诊断元数据。

    假设空间/旁开支线/信念历史/证据源可用性都已在 state 里累积,这里统一取出,
    随 complete 事件下发,避免"后端算了、前端看不到"的静默丢弃。
    """
    values = final_state.values if final_state and final_state.values else {}
    return {
        "hypothesis_space": values.get("hypothesis_space", []),
        "sidebar_branches": values.get("sidebar_branches", []),
        "belief_history": values.get("belief_history", []),
        "evidence_source_availability": values.get("evidence_source_availability", []),
        'diagnosis': values.get('diagnosis'),
        'investigation': investigation_summary(values),
    }


def _snapshot_payload(node_name: str, state: Dict | None) -> Dict[str, Any]:
    """从节点输出抽取 JSON-安全的快照摘要（B3 步快照 payload）。"""
    st = state or {}
    if node_name == NODE_PLANNER:
        return {"plan": list(st.get("plan", []) or [])}
    if node_name == NODE_EXECUTOR:
        past = st.get("past_steps", []) or []
        if past:
            step, result = past[-1]
            return {"last_step": step, "result_digest": str(result)[:200]}
        return {}
    if node_name == NODE_REPLANNER:
        return {
            "remaining_plan": list(st.get("plan", []) or []),
            "response_digest": str(st.get("response", ""))[:200],
        }
    return {}


class AIOpsService:
    """运维诊断服务：封装 Plan-Execute-Replan 图，提供流式 execute() / resume()。

    Args:
        replan_strategy: 可选的 replanner 策略实例。不传则使用 DefaultReplanStrategy。
    """

    def __init__(self, replan_strategy: Optional[BaseReplanStrategy] = None) -> None:
        self.checkpointer = MemorySaver()
        self._persistent_checkpointer = None
        self._persistent_context = None
        self._checkpoint_lock = asyncio.Lock()
        self._resume_locks: dict[str, asyncio.Lock] = {}
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

    def _create_run_strategy(self, terminal_enabled: bool = False) -> BaseReplanStrategy:
        """终端自主调查强制使用带假设/证据门控的策略；保留测试注入策略。"""
        strategy = self._create_strategy()
        if terminal_enabled and isinstance(strategy, DefaultReplanStrategy):
            return DynamicClassificationStrategy()
        return strategy

    async def close(self) -> None:
        """Release the persistent SQLite checkpointer connection on shutdown."""
        if self._persistent_context is not None:
            await self._persistent_context.__aexit__(None, None, None)
            self._persistent_context = None
            self._persistent_checkpointer = None

    async def run_diagnosis(self, thread_id: str) -> dict | None:
        return (await self.run_details(thread_id))['diagnosis']

    async def run_details(self, thread_id: str) -> dict:
        """Caller must check run ownership before reading its checkpoint."""
        graph = await self._persistent_graph(self._create_strategy())
        snapshot = await graph.aget_state({'configurable': {'thread_id': thread_id}})
        values = (snapshot.values or {}) if snapshot else {}
        return {'diagnosis': values.get('diagnosis'), 'investigation': investigation_summary(values),
                'investigation_failure': values.get('investigation_failure')}

    async def _persistent_graph(self, strategy: BaseReplanStrategy):
        async with self._checkpoint_lock:
            if self._persistent_checkpointer is None:
                checkpoint_path = Path(settings.AIOPS_CHECKPOINT_DB_PATH)
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                self._persistent_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
                self._persistent_checkpointer = await self._persistent_context.__aenter__()
                await self._persistent_checkpointer.setup()
        return self._build_graph(strategy, checkpointer=self._persistent_checkpointer)

    def _build_graph(self, strategy: BaseReplanStrategy, checkpointer=None):
        """装配 Plan-Execute-Replan 图；HITL 开启时追加 human_review 节点。"""
        workflow = StateGraph(PlanExecuteState)
        workflow.add_node(NODE_PLANNER, planner)
        workflow.add_node(NODE_EXECUTOR, executor)
        workflow.add_node(NODE_REPLANNER, create_replanner(strategy))

        async def terminal_review(state: PlanExecuteState) -> Dict[str, Any]:
            approval = state.get("terminal_approval") or {}
            decision = interrupt({
                "type": "pending_terminal_approval",
                "request_id": approval.get("request_id"),
                "session_id": approval.get("session_id"),
                "command": approval.get("command"),
                "expires_at": approval.get("expires_at"),
            })
            if not isinstance(decision, dict) or decision.get("action") != "approve":
                return {
                    "response": "终端命令未获批准或审批已失效；本次诊断未执行该命令。",
                    "terminal_rejected": True,
                    "terminal_approval": {},
                }

            from src.agent.aiops.executor import _build_tool_map, _get_tools_cached
            from src.agent.aiops.termcp_tools import register_shell_session
            register_shell_session(approval["shell_id"], approval["session_id"])
            tools, err = await _get_tools_cached(True)
            tool = _build_tool_map(tools).get("shell_output")
            if not tool:
                raise RuntimeError(f"Termcp shell_output unavailable: {err or 'tool missing'}")
            result = await tool.ainvoke({"shell_id": approval["shell_id"], "timeout": 1})
            output = str(result)
            raw_output = json.dumps({
                "data_source": "termcp_approved_target", "target_id": settings.TERMCP_SSH_PROFILE,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "approval_request_id": approval["request_id"], "command": approval["command"],
                "output": output,
            }, ensure_ascii=False)
            step = str(approval.get("step") or "受控终端诊断")
            return {
                "plan": (state.get("plan") or [])[1:],
                "past_steps": [(step, output)],
                "raw_evidence": [(step, raw_output)],
                "terminal_approval": {},
                "terminal_session_id": approval.get("session_id", ""),
                "terminal_shell_id": approval.get("shell_id", ""),
                "terminal_rejected": False,
                "_step_progress": {
                    "done": len(state.get("past_steps") or []) + 1,
                    "total": len(state.get("past_steps") or []) + len(state.get("plan") or []),
                },
            }

        workflow.add_node(NODE_TERMINAL_REVIEW, terminal_review)

        workflow.set_entry_point(NODE_PLANNER)
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)

        def after_executor(state: PlanExecuteState) -> str:
            return NODE_TERMINAL_REVIEW if state.get("terminal_approval") else NODE_REPLANNER

        workflow.add_conditional_edges(
            NODE_EXECUTOR,
            after_executor,
            {NODE_TERMINAL_REVIEW: NODE_TERMINAL_REVIEW, NODE_REPLANNER: NODE_REPLANNER},
        )
        workflow.add_conditional_edges(
            NODE_TERMINAL_REVIEW,
            lambda state: END if state.get("terminal_rejected") else NODE_REPLANNER,
            {NODE_REPLANNER: NODE_REPLANNER, END: END},
        )

        if settings.ENABLE_HITL:
            workflow.add_node(NODE_HUMAN_REVIEW, build_human_review_node())

            def should_continue(state: PlanExecuteState) -> str:
                if state.get('investigation_failure'):
                    return END
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
        return workflow.compile(checkpointer=checkpointer or self.checkpointer)

    async def _stream_events(
        self, graph, config, input
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """统一的事件流封装：跳过 __interrupt__ 内部事件，格式化节点事件。

        ENABLE_STEP_SNAPSHOTS 开启时：顺路把每步节点输出摘要落库
        （run_store.add_step_snapshot，best-effort，供回放/审计）。
        """
        thread_id = str((config.get("configurable") or {}).get("thread_id", ""))
        step_index = 0
        scope_token = terminal_scope.set(thread_id)
        try:
            while True:
                boundary = False
                async for event in graph.astream(
                    input, config, stream_mode="updates", interrupt_after=[NODE_REPLANNER]
                ):
                    for node_name, node_output in event.items():
                        if node_name == "__interrupt__":
                            continue
                        boundary = boundary or node_name == NODE_REPLANNER
                        if settings.ENABLE_STEP_SNAPSHOTS and thread_id:
                            run_store.add_step_snapshot(
                                thread_id, step_index, node_name,
                                _snapshot_payload(node_name, node_output),
                            )
                        step_index += 1
                        if isinstance(node_output, dict):
                            for item in node_output.get("evidence_events", []) or []:
                                try:
                                    yield make_evidence_event(**item)
                                except TypeError:
                                    continue
                        yield self._format_event(node_name, node_output)
                checkpoint = await graph.aget_state(config)
                if not boundary or not checkpoint.next:
                    break
                # Continue from the checkpointed next node; a segment boundary is
                # neither completion nor approval and never replays finished tools.
                input = None
                await asyncio.sleep(0)
        finally:
            terminal_scope.reset(scope_token)

    def _yield_pending_review(self, thread_id: str, draft: str) -> Dict[str, Any]:
        return make_pending_review_event(thread_id, draft)

    def _failed_investigation(self, thread_id: str, final_state, *, managed: bool = True) -> Dict[str, Any] | None:
        values = (final_state.values or {}) if final_state else {}
        failure = values.get('investigation_failure')
        if not failure:
            return None
        report = values.get('response', '')
        if managed:
            run_store.mark_failed(thread_id, failure['message'], report=report)
            self._thread_runs.pop(thread_id, None)
        clear_terminal_context(thread_id)
        return {**make_error_event(failure['message'], stage='investigation_failed'),
                'thread_id': thread_id, 'response': report, 'investigation_failure': failure,
                **_diagnostic_extras(final_state)}

    async def execute(
        self, user_input: str, session_id: str = "default", user_id: Optional[int] = None,
        terminal_enabled: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """开始一次诊断（流式）。

        HITL 开启时：每线程独立策略+编译图（假设空间跨请求存活），并落运行记录；
        非 HITL：复用全局单例策略并 reset（原行为，回归兼容）。
        """
        if not user_input or not user_input.strip():
            yield make_error_event("诊断输入不能为空,请描述当前遇到的故障现象", stage="validation_error")
            return
        # 每次诊断使用唯一 thread_id,防止 MemorySaver 累积 past_steps
        unique_session = f"{session_id[:24]}-{uuid4().hex}"

        terminal_enabled = bool(terminal_enabled and settings.TERMCP_ENABLED)
        managed_run = settings.ENABLE_HITL or settings.TERMCP_ENABLED or settings.PROBE_ENABLED
        if managed_run:
            strategy = self._create_run_strategy(terminal_enabled)
            graph = await self._persistent_graph(strategy)
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
                yield make_error_event(
                    "诊断输入不能为空,请描述当前遇到的故障现象", stage="validation_error"
                )
                return

            from src.agent.aiops.strategies.investigation import mechanism_config
            initial: PlanExecuteState = {
                "input": user_input,
                "plan": [],
                "past_steps": [],
                "response": "",
                "terminal_enabled": terminal_enabled,
                "autonomous_investigation": terminal_enabled or settings.PROBE_ENABLED,
                "investigation_config": mechanism_config(),
                "thread_id": unique_session,
                "user_id": user_id,
                "evidence_events": [],
            }
            config = {"configurable": {"thread_id": unique_session}}

            try:
                async for event in self._stream_events(graph, config, initial):
                    yield event

                final_state = await graph.aget_state(config)
                failure_event = self._failed_investigation(unique_session, final_state, managed=managed_run)
                if failure_event:
                    yield failure_event
                    return

                if final_state and NODE_TERMINAL_REVIEW in (final_state.next or ()):
                    approval = (final_state.values or {}).get("terminal_approval") or {}
                    run_store.mark_pending_terminal(unique_session, approval)
                    yield {
                        "type": "pending_terminal_approval",
                        "stage": "pending_terminal_approval",
                        "thread_id": unique_session,
                        **approval,
                        "termcp_ui_url": settings.TERMCP_UI_URL,
                        "message": "终端命令等待 Termcp UI 审批；批准后回到本页继续诊断",
                    }
                    return

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
                if managed_run:
                    run_store.mark_completed(unique_session, final_response)
                    self._thread_runs.pop(unique_session, None)
                clear_terminal_context(unique_session)
                yield make_complete_event(final_response, thread_id=unique_session, **_diagnostic_extras(final_state))
                logger.info(f"[aiops][{session_id}] 诊断完成")
            except (asyncio.CancelledError, GeneratorExit):
                if managed_run:
                    record = run_store.get_run(unique_session)
                    if record and record.status in {run_store.STATUS_RUNNING, run_store.STATUS_APPROVED}:
                        run_store.mark_failed(unique_session, "诊断连接已取消，已停止选择后续检查")
                    self._thread_runs.pop(unique_session, None)
                clear_terminal_context(unique_session)
                raise
            except Exception as e:
                logger.exception("[aiops][{}] 诊断失败: {}", session_id, e)
                if managed_run:
                    run_store.mark_failed(unique_session, str(e))
                    self._thread_runs.pop(unique_session, None)
                clear_terminal_context(unique_session)
                yield make_error_event(f"诊断出错: {e}")

    async def resume(
        self, thread_id: str, decision: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        lock = self._resume_locks.setdefault(thread_id, asyncio.Lock())
        if lock.locked():
            yield make_error_event("诊断正在续跑，请勿重复提交", stage="resume_conflict")
            return
        async with lock:
            async for event in self._resume(thread_id, decision):
                yield event

    async def _resume(
        self, thread_id: str, decision: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """恢复挂起的诊断（HITL 审批后调用）。

        Args:
            thread_id: execute() 挂起时下发的 thread_id。
            decision: {"action": "approve"|"reject", "instruction": str|None}。
        """
        run = self._thread_runs.get(thread_id)
        if not run:
            record = run_store.get_run(thread_id)
            if not record or record.status not in {
                run_store.STATUS_PENDING_REVIEW, run_store.STATUS_PENDING_TERMINAL
            }:
                logger.warning(f"[aiops] 恢复失败: 线程 {thread_id} 不存在或非待审状态")
                yield make_error_event(f"诊断 {thread_id} 不存在或不在待恢复状态", stage="not_found")
                return
            strategy = self._create_strategy()
            graph = await self._persistent_graph(strategy)
            run = (strategy, graph)
            self._thread_runs[thread_id] = run

        strategy, graph = run
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint = await graph.aget_state(config)
        if not checkpoint or not checkpoint.next:
            yield make_error_event("找不到待恢复的持久化诊断，请重新诊断", stage="not_found")
            return
        if ((checkpoint.values or {}).get("terminal_enabled")
                and isinstance(strategy, DefaultReplanStrategy)):
            strategy = DynamicClassificationStrategy()
            graph = await self._persistent_graph(strategy)
            self._thread_runs[thread_id] = (strategy, graph)
            checkpoint = await graph.aget_state(config)
        if NODE_TERMINAL_REVIEW in checkpoint.next and decision.get("action") == "approve":
            try:
                await verify_terminal_approval(checkpoint.values.get("terminal_approval") or {})
            except TerminalApprovalStatusError as exc:
                if exc.terminal:
                    run_store.mark_failed(thread_id, str(exc))
                    self._thread_runs.pop(thread_id, None)
                    clear_terminal_context(thread_id)
                yield make_error_event(str(exc), stage="terminal_approval_invalid")
                return
        async with trace_span("aiops.resume", session_id=thread_id):
            logger.info(f"[aiops] 恢复诊断 {thread_id}: {decision}")
            try:
                async for event in self._stream_events(graph, config, Command(resume=decision)):
                    yield event

                final_state = await graph.aget_state(config)
                failure_event = self._failed_investigation(thread_id, final_state)
                if failure_event:
                    yield failure_event
                    return
                if final_state and NODE_TERMINAL_REVIEW in (final_state.next or ()):
                    approval = (final_state.values or {}).get("terminal_approval") or {}
                    run_store.mark_pending_terminal(thread_id, approval)
                    yield {
                        "type": "pending_terminal_approval",
                        "stage": "pending_terminal_approval",
                        "thread_id": thread_id,
                        **approval,
                        "termcp_ui_url": settings.TERMCP_UI_URL,
                        "message": "终端命令仍待审批；批准后可继续诊断",
                    }
                    return
                # 驳回重诊后再次 respond → 再次挂起等待审批
                if final_state and NODE_HUMAN_REVIEW in (final_state.next or ()):
                    draft = (final_state.values or {}).get("response", "")
                    run_store.mark_pending_review(thread_id, draft)
                    yield self._yield_pending_review(thread_id, draft)
                    return

                final_response = (final_state.values or {}).get("response", "") if final_state else ""
                run_store.mark_completed(thread_id, final_response)
                self._thread_runs.pop(thread_id, None)
                clear_terminal_context(thread_id)
                yield make_complete_event(final_response, thread_id=thread_id, **_diagnostic_extras(final_state))
                logger.info(f"[aiops] 诊断恢复完成 {thread_id}")
            except (asyncio.CancelledError, GeneratorExit):
                record = run_store.get_run(thread_id)
                if record and record.status in {run_store.STATUS_RUNNING, run_store.STATUS_APPROVED}:
                    run_store.mark_failed(thread_id, "诊断连接已取消，已停止选择后续检查")
                self._thread_runs.pop(thread_id, None)
                clear_terminal_context(thread_id)
                raise
            except Exception as e:
                logger.exception("[aiops] 恢复诊断失败: {}", e)
                run_store.mark_failed(thread_id, str(e))
                self._thread_runs.pop(thread_id, None)
                clear_terminal_context(thread_id)
                yield make_error_event(f"恢复诊断出错: {e}")

    @staticmethod
    def _format_event(node_name: str, state: Dict | None) -> Dict[str, Any]:
        """节点输出 → SSE 事件（统一经 events.py 构造函数产出，字段结构不变）。"""
        state = state or {}
        if node_name == NODE_PLANNER:
            return make_plan_event(state.get("plan", []))
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
                else:
                    done = len(past_steps)
                    total = done + len(plan)
                return make_step_complete_event(done, total, last_step, len(plan))
            return make_status_event("executor", ROLE_EXECUTOR, "执行步骤中")
        if node_name == NODE_TERMINAL_REVIEW:
            if state.get("response"):
                return make_report_event(state["response"], state.get('diagnosis'))
            past = state.get("past_steps") or []
            if past:
                progress = state.get("_step_progress") or {}
                return make_step_complete_event(progress.get("done", 1), progress.get("total", 1),
                                                past[-1][0], len(state.get("plan") or []))
        if node_name == NODE_REPLANNER:
            summary = investigation_summary(state)
            extra = {'investigation': summary} if summary is not None else {}
            if state.get('investigation_failure'):
                extra['investigation_failure'] = state['investigation_failure']
            response = state.get("response", "")
            plan = state.get("plan", [])
            branches = state.get("sidebar_branches", [])
            running = sum(1 for b in branches if b.get("status") == "running")
            sidebar_note = f"，旁开支线 {running} 条" if branches else ""
            if response:
                # HITL 开启时 replanner 产出的是"草稿"，最终报告需人工审批
                if settings.ENABLE_HITL and not state.get('investigation_failure'):
                    return {**make_draft_event(response), **extra}
                event = {**make_report_event(response, state.get('diagnosis')), **extra}
                if state.get('investigation_failure'):
                    event['message'] = '调查未完成，已保留已有证据与失败说明'
                return event
            return make_status_event(
                "replanner",
                ROLE_REPLANNER,
                f"继续执行剩余步骤{sidebar_note}" if plan else f"准备生成报告{sidebar_note}",
                remaining_steps=len(plan),
                **extra,
            )
        return make_status_event(node_name, node_name, f"{node_name} 执行中")


# 全局单例（根据 settings 自动选择策略）
_default_strategy = DynamicClassificationStrategy() if settings.ENABLE_DYNAMIC_CLASSIFICATION else None
aiops_service = AIOpsService(replan_strategy=_default_strategy)
