"""一次性全链路打通脚本。

启动 3 个 MCP Mock 服务，然后使用真实 DashScope API Key 运行 AIOpsService，
验证 planner( LLM) → executor(MCP) → replanner(动态分类策略) → response 完整链路。
"""

import os
import socket
import subprocess
import sys
import time
import asyncio

# 优先从 .env 加载环境变量,避免手动 export
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 请通过环境变量或 .env 提供 DashScope API Key，不要在代码中硬编码
os.environ.setdefault("ENABLE_DYNAMIC_CLASSIFICATION", "true")

if not os.environ.get("DASHSCOPE_API_KEY"):
    print("[错误] 请先设置环境变量 DASHSCOPE_API_KEY 或在项目根目录放置 .env 文件")
    sys.exit(1)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = sys.executable

MCP_SERVERS = [
    ("mcp_servers/cls_server.py", 8103),
    ("mcp_servers/monitor_server.py", 8104),
    ("mcp_servers/rag_server.py", 8105),
]


def _port_ready(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_ports(ports: list[int], procs: list[subprocess.Popen], max_wait: int = 60) -> None:
    started = time.time()
    while time.time() - started < max_wait:
        ready = {p: _port_ready(p) for p in ports}
        if all(ready.values()):
            return
        # 每 5 秒打印一次状态，方便观察
        if int(time.time() - started) % 5 == 0:
            print("  端口状态:", ready)
        time.sleep(0.5)
    # 超时后打印各子进程日志路径以便排查
    print("\n[诊断] MCP 日志文件:")
    for proc in procs:
        print("  ", getattr(proc, "_log_path", "unknown"))
    raise TimeoutError(f"MCP 服务端口未在 {max_wait}s 内就绪: {ports}")


def _start_servers() -> list[subprocess.Popen]:
    procs = []
    for script, port in MCP_SERVERS:
        cmd = [PYTHON_EXE, os.path.join(PROJECT_ROOT, script)]
        print(f"[启动] {script} -> 127.0.0.1:{port}")
        log_path = os.path.join(PROJECT_ROOT, f"{os.path.basename(script)}.log")
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=open(log_path, "w", encoding="utf-8"),
        )
        proc._log_path = log_path
        procs.append(proc)
    return procs


def _stop_servers(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


async def _run_aiops(user_input: str | None = None) -> None:
    # 延迟导入，确保环境变量已设置
    import src.agent.aiops.graph as graph

    service = graph.AIOpsService(replan_strategy=graph.DynamicClassificationStrategy())
    if not user_input:
        user_input = "data-sync-service CPU 负载高，请排查根因"
    print(f"\n[诊断输入] {user_input}\n")

    events = []
    async for event in service.execute(user_input, session_id="full-pipeline"):
        events.append(event)
        print(event)

    print("\n[事件总数]", len(events))


def main() -> None:
    user_input = sys.argv[1] if len(sys.argv) > 1 else None
    procs = _start_servers()
    try:
        print("[等待] MCP 服务就绪...")
        _wait_for_ports([port for _, port in MCP_SERVERS], procs)
        print("[就绪] MCP 服务全部在线\n")
        asyncio.run(_run_aiops(user_input))
    finally:
        print("\n[清理] 关闭 MCP 服务...")
        _stop_servers(procs)
        print("[完成]")


if __name__ == "__main__":
    main()
