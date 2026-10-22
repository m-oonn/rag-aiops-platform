"""Termcp tool wrappers that enforce and correlate per-command approval."""

import asyncio
import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.tools import BaseTool, StructuredTool

from src.settings import settings

terminal_scope = ContextVar("aiops_terminal_scope", default="standalone")
_contexts: dict[str, dict] = {}


def _context() -> dict:
    return _contexts.setdefault(terminal_scope.get(), {"sessions": {}, "buffer": {}})


def clear_terminal_context(thread_id: str) -> None:
    _contexts.pop(thread_id, None)


def register_shell_session(shell_id: str, session_id: str) -> None:
    if shell_id and session_id:
        _context()["sessions"][str(shell_id)] = str(session_id)


class TerminalProtocolError(RuntimeError):
    """An ambiguous terminal write must stop the run instead of being retried."""


class TerminalApprovalStatusError(RuntimeError):
    def __init__(self, message: str, status_code: int, terminal: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.terminal = terminal


async def verify_terminal_approval(approval: dict) -> dict:
    """Trust Termcp's stored decision, never a browser's claimed approval."""
    import re

    session_id = str(approval.get("session_id") or "")
    request_id = approval.get("request_id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session_id) or not request_id:
        raise TerminalApprovalStatusError("审批关联信息无效，诊断已停止", 409, True)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{settings.TERMCP_APPROVAL_API_URL.rstrip('/')}/api/sessions/{session_id}/approval"
            )
            response.raise_for_status()
            payload = response.json()
        requests = payload.get("requests") if isinstance(payload, dict) else None
        if not isinstance(requests, list):
            raise ValueError("Invalid approval response")
    except (httpx.HTTPError, ValueError) as exc:
        raise TerminalApprovalStatusError("无法核验 Termcp 审批状态；请稍后重试", 503) from exc
    matched = [r for r in requests if isinstance(r, dict) and r.get("id") == request_id]
    if len(matched) != 1:
        raise TerminalApprovalStatusError("找不到唯一审批记录，诊断已停止", 409, True)
    row = matched[0]
    if (row.get("session_id") != session_id or row.get("shell_id") != approval.get("shell_id")
            or row.get("text") != approval.get("command") or row.get("keys") != ["enter"]
            or row.get("source") != "mcp"):
        raise TerminalApprovalStatusError("审批命令与待执行命令不匹配，诊断已停止", 409, True)
    expires_at = row.get("expires_at")
    if (not isinstance(expires_at, int) or expires_at <= 0
            or expires_at != approval.get("expires_at")):
        raise TerminalApprovalStatusError("审批没有有效期限，诊断已停止", 410, True)
    state = row.get("state")
    if state == "pending" and int(time.time() * 1000) < expires_at:
        raise TerminalApprovalStatusError("命令仍待 Termcp UI 审批", 409)
    if state != "approved":
        raise TerminalApprovalStatusError("审批未通过或已过期，诊断已停止", 410, True)
    resolved_at = row.get("resolved_at")
    if not isinstance(resolved_at, int) or not 0 < resolved_at < expires_at:
        raise TerminalApprovalStatusError("审批裁决时间无效，诊断已停止", 410, True)
    return row


@dataclass
class TerminalApprovalPending(Exception):
    request_id: str
    session_id: str
    shell_id: str
    command: str
    expires_at: int


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parsed = _json_value(item["text"])
                if isinstance(parsed, dict):
                    return parsed
    return value


def _match_pending_request(before: dict, after: dict, shell_id: str, command: str) -> dict:
    prior_ids = {
        str(row.get("id"))
        for row in before.get("requests", [])
        if isinstance(row, dict) and row.get("id")
    }
    matches = [
        row for row in after.get("requests", [])
        if isinstance(row, dict)
        and str(row.get("id")) not in prior_ids
        and row.get("shell_id") == shell_id
        and row.get("source") == "mcp"
        and row.get("state") in {"pending", "approved", "rejected", "expired", "cancelled"}
        and row.get("text") == command
        and row.get("keys") == ["enter"]
    ]
    if len(matches) != 1:
        raise TerminalProtocolError("Could not uniquely match the Termcp approval; stopping without replay")
    return matches[0]


def wrap_termcp_tools(tools: list[BaseTool]) -> list[BaseTool]:
    """Limit the exposed tool set and enforce the fixed approval policy per session."""
    allowed = {"session_start", "session_list", "shell_open", "shell_list", "shell_input", "shell_key", "shell_output"}
    wrapped: list[BaseTool] = []

    async def api(method: str, path: str, **kwargs):
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.request(
                method, f"{settings.TERMCP_APPROVAL_API_URL.rstrip('/')}{path}", **kwargs
            )
            response.raise_for_status()
            return response.json()

    for tool in tools:
        if tool.name not in allowed:
            continue
        original = tool

        async def invoke(_original=original, **kwargs):
            context = _context()
            sessions_by_shell = context["sessions"]
            buffered_text = context["buffer"]
            name = _original.name
            if name == "session_start" and kwargs.get("command"):
                raise ValueError("session_start initial commands are disabled; use an individually approved shell command")
            if name == "shell_open" and kwargs.get("command"):
                raise ValueError("shell_open initial commands are disabled; use an individually approved shell command")
            if name == "shell_key" and str(kwargs.get("key", "")).lower() not in {"enter", "return"}:
                raise ValueError("Only Enter may submit a reviewed terminal command")

            shell_id = str(kwargs.get("shell_id") or "")
            session_id = sessions_by_shell.get(shell_id, "")
            if name in {"shell_input", "shell_key", "shell_output"} and not session_id:
                raise ValueError("Shell does not belong to this diagnostic run")
            if name in {"shell_open", "shell_list"} and kwargs.get("session_id") not in sessions_by_shell.values():
                raise ValueError("Session does not belong to this diagnostic run")
            before = None
            if name == "shell_key":
                before = await api("GET", f"/api/sessions/{session_id}/approval")

            try:
                result = await _original.ainvoke(kwargs)
            except (Exception, asyncio.CancelledError) as exc:
                if name in {"session_start", "shell_open", "shell_input", "shell_key"}:
                    raise TerminalProtocolError("Terminal write outcome is unknown; stopping without replay") from exc
                raise
            value = _json_value(result)
            if name == "session_start" and isinstance(value, dict):
                session_id = str(value.get("session_id") or "")
                shell_id = str(value.get("shell_id") or "")
                if not session_id or not shell_id:
                    raise TerminalProtocolError("Termcp returned no session/shell id")
                sessions_by_shell[shell_id] = session_id
                register_shell_session(shell_id, session_id)
            elif name == "shell_open" and isinstance(value, dict):
                shell_id = str(value.get("shell_id") or "")
                session_id = str(value.get("session_id") or kwargs.get("session_id") or "")
                if shell_id and session_id:
                    sessions_by_shell[shell_id] = session_id
                    register_shell_session(shell_id, session_id)
            elif name == "shell_input":
                if not isinstance(value, dict) or value.get("review_pending") is not True:
                    raise TerminalProtocolError("Termcp did not stage this input for review")
                buffered_text[shell_id] = buffered_text.get(shell_id, "") + str(kwargs.get("text") or "")
            elif name == "shell_key":
                try:
                    after = await api("GET", f"/api/sessions/{session_id}/approval")
                except Exception as exc:
                    raise TerminalProtocolError("Submitted command could not be verified; stopping without replay") from exc
                command = buffered_text.get(shell_id, "")
                buffered_text[shell_id] = ""
                row = _match_pending_request(before or {}, after, shell_id, command)
                raise TerminalApprovalPending(
                    request_id=str(row["id"]), session_id=session_id, shell_id=shell_id,
                    command=command, expires_at=int(row.get("expires_at") or 0),
                )
            elif name == "session_list" and isinstance(value, dict):
                value["sessions"] = [s for s in value.get("sessions", []) if s.get("id") in sessions_by_shell.values()]
                return json.dumps(value)
            return result

        wrapped.append(StructuredTool.from_function(
            coroutine=invoke,
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            # BaseTool.ainvoke(args) already unwraps the MCP content/artifact tuple.
            response_format="content",
        ))
    return wrapped
