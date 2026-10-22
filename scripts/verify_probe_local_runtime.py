"""Run a disposable local Probe -> gateway -> MCP smoke test.

This deliberately uses a temporary config and a random bearer token.  It does
not install a Windows Service, modify ProgramData, or expose a non-loopback
port.  The collector still reads the real local Windows machine, but only
through the fixed read-only Probe operations.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"gateway did not listen on 127.0.0.1:{port}")


def _mcp_inventory(port: int, token: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5.0) as client:
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "local-probe-smoke", "version": "1"},
                },
            },
        )
        initialized.raise_for_status()
        session_id = initialized.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("MCP initialize did not return a session id")
        headers["Mcp-Session-Id"] = session_id
        client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        ).raise_for_status()
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "probe_inventory", "arguments": {}},
            },
        )
        response.raise_for_status()
        return response.text


def _container_probe_tools(container: str, token: str) -> None:
    """Load only the Probe MCP tools inside an existing AIOps container."""
    check = (
        "import asyncio, json; "
        "from src.settings import settings; "
        "from src.agent.mcp_client import load_tools_for_config; "
        "tools, error = asyncio.run(load_tools_for_config({'probe': settings.MCP_SERVERS['probe']})); "
        "names = sorted(tool.name for tool in tools); "
        "print(json.dumps({'tools': names, 'error': error}, ensure_ascii=False)); "
        "assert 'probe_inventory' in names"
    )
    result = subprocess.run(
        ["docker", "exec", "-e", "PROBE_ENABLED=true", "-e", f"PROBE_TOKEN={token}",
         "-e", "MCP_PROBE_URL=http://probe-gateway:18767/mcp", container, "python", "-c", check],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    # Keep output bounded and avoid echoing any environment values.
    if "probe_inventory" not in result.stdout:
        raise RuntimeError("AIOps container did not load probe_inventory")


def _container_aiops_smoke(container: str, token: str, target_id: str) -> None:
    """Run one read-only AIOps graph pass in an existing container."""
    code = r'''
import asyncio, json
from src.agent.aiops import aiops_service

async def main():
    events = []
    async for event in aiops_service.execute(
        "只读检查当前 Windows 目标的运行概况。优先使用 Probe inventory；不得执行写入、重启或终端命令。最后列出实际拿到的 target_id、证据来源和无法确认的部分。",
        session_id="probe-aiops-smoke",
        terminal_enabled=False,
    ):
        if isinstance(event, dict):
            events.append({
                "type": event.get("type"),
                "stage": event.get("stage"),
                "message": str(event.get("message", ""))[:300],
                "target_id": event.get("target_id"),
                "source": event.get("source"),
            })
    print(json.dumps({"events": events[-30:]}, ensure_ascii=False))
    await aiops_service.close()

asyncio.run(main())
'''
    result = subprocess.run(
        ["docker", "exec", "-e", "PROBE_ENABLED=true", "-e", f"PROBE_TOKEN={token}",
         "-e", "MCP_PROBE_URL=http://probe-gateway:18767/mcp", "-e", "TERMCP_ENABLED=false",
         "-e", "ENABLE_HITL=false", "-e", "DATABASE_URL=sqlite:////tmp/probe-aiops-smoke.sqlite",
         "-e", "AIOPS_CHECKPOINT_DB_PATH=/tmp/probe-aiops-checkpoints.sqlite",
         "-e", "PROBE_EVIDENCE_DIR=/tmp/probe-aiops-evidence", container, "python", "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    output = result.stdout.lower()
    try:
        summary = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        summary = {}
    events = summary.get("events") if isinstance(summary, dict) else []
    event_summary = {
        "types": sorted({str(item.get("type")) for item in events if item.get("type")} ),
        "stages": sorted({str(item.get("stage")) for item in events if item.get("stage")} ),
        "sources": sorted({str(item.get("source")) for item in events if item.get("source")} ),
        "targets": sorted({str(item.get("target_id")) for item in events if item.get("target_id")} ),
    }
    if "probe" not in output or target_id.lower() not in output:
        raise RuntimeError(f"AIOps smoke did not expose Probe evidence: {json.dumps(event_summary, ensure_ascii=False)}")


async def _adapter_inventory(port: int, token: str) -> str:
    client = MultiServerMCPClient({
        "probe": {
            "transport": "streamable_http",
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": f"Bearer {token}"},
        }
    })
    tools = await client.get_tools()
    inventory = next((tool for tool in tools if tool.name == "probe_inventory"), None)
    if inventory is None:
        raise RuntimeError(f"probe_inventory was not loaded (tools={[tool.name for tool in tools]})")
    result = await inventory.ainvoke({})
    return json.dumps(result, ensure_ascii=False, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--external-gateway",
        action="store_true",
        help="reuse a gateway already listening on PROBE_PORT instead of starting one",
    )
    parser.add_argument(
        "--check-container",
        help="also load Probe tools inside an existing AIOps container via docker exec",
    )
    parser.add_argument(
        "--check-aiops",
        help="also run one read-only AIOps graph pass inside an existing container",
    )
    args = parser.parse_args(argv)
    target_id = os.environ.get("PROBE_TARGET_ID", "windows-local-smoke")
    external = args.external_gateway
    token = os.environ.get("PROBE_TOKEN", "") if external else uuid.uuid4().hex
    if external and not token:
        raise RuntimeError("PROBE_TOKEN is required with --external-gateway")
    port = int(os.environ.get("PROBE_PORT", "18767")) if external else _free_port()
    gateway_process: subprocess.Popen | None = None
    probe_process: subprocess.Popen | None = None

    with tempfile.TemporaryDirectory(prefix="rag-aiops-probe-") as temp_dir:
        temp = Path(temp_dir)
        token_path = temp / "token"
        config_path = temp / "config.toml"
        token_path.write_text(token, encoding="utf-8")
        config_path.write_text(
            "\n".join([
                f"target_id = '{target_id}'",
                f"gateway_url = 'ws://127.0.0.1:{port}/probe/ws'",
                f"token_file = '{token_path.as_posix()}'",
                "baseline_interval_seconds = 30",
                "",
            ]),
            encoding="utf-8",
        )
        try:
            if not external:
                gateway_env = os.environ.copy()
                gateway_env.update({"PROBE_TOKEN": token, "PROBE_TARGET_ID": target_id})
                gateway_process = subprocess.Popen(
                    [PYTHON, "-m", "uvicorn", "mcp_servers.probe_gateway:app",
                     "--host", "127.0.0.1", "--port", str(port)],
                    cwd=PROJECT_ROOT,
                    env=gateway_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            _wait_port(port)

            probe_env = os.environ.copy()
            probe_env["RAG_AIOPS_PROBE_CONFIG"] = str(config_path)
            probe_process = subprocess.Popen(
                [PYTHON, "-c", "import asyncio; from scripts.windows_probe import run_probe; asyncio.run(run_probe())"],
                cwd=PROJECT_ROOT,
                env=probe_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            deadline = time.monotonic() + 15
            last_error = "probe has not connected"
            response_text = ""
            while time.monotonic() < deadline:
                try:
                    response_text = _mcp_inventory(port, token)
                    if target_id in response_text and "probe_target" in response_text:
                        adapter_text = asyncio.run(_adapter_inventory(port, token))
                        if target_id not in adapter_text or "probe_target" not in adapter_text:
                            raise RuntimeError("langchain MCP adapter returned no Probe inventory")
                        if args.check_container:
                            _container_probe_tools(args.check_container, token)
                        if args.check_aiops:
                            _container_aiops_smoke(args.check_aiops, token, target_id)
                        print(json.dumps({
                            "ok": True,
                            "target_id": target_id,
                            "operation": "inventory",
                            "transport": "LangChain MCP adapter -> MCP HTTP -> gateway WebSocket -> Probe",
                            "container_tool_check": args.check_container or None,
                            "aiops_smoke_check": args.check_aiops or None,
                        }, ensure_ascii=False))
                        return 0
                    last_error = "MCP response did not contain Probe inventory"
                except Exception as exc:  # startup races are expected here
                    last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5)
            raise RuntimeError(last_error)
        finally:
            for process in (probe_process, gateway_process):
                if process is None or process.poll() is not None:
                    continue
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
