#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一键启动 / 停止 / 查看状态 —— 运维诊断 Agent 演示环境

用法（Windows 双击 start_demo.bat 即可，或命令行）：
    python scripts/launch_demo.py start    # 启动全部服务
    python scripts/launch_demo.py stop     # 停止全部服务
    python scripts/launch_demo.py status   # 看运行状态
    python scripts/launch_demo.py start --no-frontend --no-browser   # 只起后端（终端演示用）

启动 4 个服务：
    1. MCP 指标服务   http://127.0.0.1:8104/mcp
    2. MCP 日志服务   http://127.0.0.1:8103/mcp
    3. FastAPI 后端   http://127.0.0.1:8200   （诊断端点 /api/v1/aiops，SSE 流式）
    4. Vue 前端       http://127.0.0.1:5273   （演示界面）
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PID_FILE = ROOT / ".demo_pids.json"
LOG_DIR = ROOT / "logs"

SERVICES = [
    # (键, 名称, 端口, 启动命令, 健康检查 URL, 是否必需)
    ("monitor", "MCP 指标服务", 8104,
     [str(PYTHON), "mcp_servers/monitor_server.py"],
     "http://127.0.0.1:8104/mcp", True),
    ("cls", "MCP 日志服务", 8103,
     [str(PYTHON), "mcp_servers/cls_server.py"],
     "http://127.0.0.1:8103/mcp", True),
    ("rag", "MCP 知识库服务", 8105,
     [str(PYTHON), "mcp_servers/rag_server.py"],
     "http://127.0.0.1:8105/mcp", False),   # 依赖向量库,起不来不阻断诊断
    ("change", "MCP 变更服务", 8106,
     [str(PYTHON), "mcp_servers/change_server.py"],
     "http://127.0.0.1:8106/mcp", False),   # 2026-10-13 补入: Agent 四大证据源之一(变更),依赖 ES,起不来不阻断诊断
    ("api", "FastAPI 后端", 8200,
     [str(PYTHON), "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "8200"],
     "http://127.0.0.1:8200/docs", True),
    ("frontend", "Vue 前端", 5273,
     ["npm.cmd", "run", "dev"],
     "http://127.0.0.1:5273/", False),
]

C_OK = "  [OK]  "
C_BAD = "  [!!]  "
C_INFO = "  [..]  "


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def mcp_ready(port: int) -> bool:
    """MCP streamable-http 服务就绪探测：POST initialize 握手（需特定 Accept 头）。

    注意：GET /mcp 会返回 406，不能用普通网页探测方式，否则误判为"未就绪"。
    就绪判定 = TCP 可连 + 服务端开始处理（收到任意 HTTP 响应，含 406）。
    """
    if not port_in_use(port):
        return False
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "launcher", "version": "1.0"}},
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", method="POST", data=payload,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500          # 400/406 也说明服务在跑
    except Exception:
        return False


def wait_ready(url: str, seconds: float, is_mcp: bool = False, port: int = 0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if mcp_ready(port) if is_mcp else http_ok(url):
            return True
        time.sleep(1.0)
    return False


def load_pids() -> dict:
    if PID_FILE.exists():
        try:
            return json.loads(PID_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_pids(data: dict) -> None:
    PID_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def preflight() -> bool:
    ok = True
    if not PYTHON.exists():
        print(f"{C_BAD} 缺虚拟环境: {PYTHON}")
        print("        请先建 .venv（见 README 安装步骤）")
        ok = False
    if not (ROOT / ".env").exists():
        print(f"{C_BAD} 缺 .env 文件（需要 DASHSCOPE_API_KEY / SECRET_KEY）")
        ok = False
    if not (ROOT / "frontend" / "node_modules").exists():
        print(f"{C_INFO} 前端依赖未装（frontend/node_modules 缺失）—— 将跳过前端")
    return ok


def start(args) -> int:
    print("=" * 60)
    print("  运维诊断 Agent · 演示环境 一键启动")
    print("=" * 60)
    if not preflight():
        return 1

    LOG_DIR.mkdir(exist_ok=True)
    existing = load_pids()
    running = {k: v for k, v in existing.items() if v.get("pid") and _pid_alive(v["pid"])}
    if running:
        print(f"{C_INFO} 检测到已运行的服务: {', '.join(running)}")
        print("        如需重启，请先执行:  python scripts/launch_demo.py stop")
        return 1

    pids: dict = {}
    failures: list[str] = []

    for key, name, port, cmd, url, required in SERVICES:
        if key == "frontend":
            if args.no_frontend:
                print(f"{C_INFO} {name}: 已跳过（--no-frontend）")
                continue
            if not (ROOT / "frontend" / "node_modules").exists():
                print(f"{C_INFO} {name}: 已跳过（依赖未装）")
                continue

        if port_in_use(port):
            print(f"{C_BAD} {name}: 端口 {port} 已被占用（可能上次没关干净）")
            print(f"        可执行: python scripts/launch_demo.py stop")
            failures.append(name)
            continue

        print(f"{C_INFO} {name}: 启动中 ...", end="", flush=True)
        cwd = ROOT / "frontend" if key == "frontend" else ROOT
        log = open(LOG_DIR / f"demo_{key}.log", "ab")
        try:
            # DETACHED_PROCESS + NEW_PROCESS_GROUP + NO_WINDOW：
            # 服务完全脱离本控制台，关掉启动窗口 / 启动器退出后服务继续跑。
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                creationflags=0x00000008 | 0x00000200 | 0x08000000,
            )
        except Exception as e:
            print(f"\r{C_BAD} {name}: 启动失败 {e}")
            failures.append(name)
            continue

        # 等待就绪（MCP 服务用协议握手探测，其他用 HTTP）
        is_mcp = key in ("monitor", "cls")
        ready = wait_ready(url, args.timeout if required else min(args.timeout, 25),
                           is_mcp=is_mcp, port=port)
        if ready:
            print(f"\r{C_OK} {name}: 已就绪  ({url.replace('/docs','').replace('/mcp','')})")
            pids[key] = {"pid": proc.pid, "port": port, "name": name}
        else:
            alive = _pid_alive(proc.pid)
            status = "进程在但未就绪" if alive else "进程已退出"
            print(f"\r{C_BAD} {name}: {status}（日志: logs/demo_{key}.log）")
            if required:
                failures.append(name)
            if alive:
                pids[key] = {"pid": proc.pid, "port": port, "name": name}

    save_pids(pids)

    print("-" * 60)
    if failures:
        print(f"{C_BAD} 有 {len(failures)} 个必需服务未起来: {', '.join(failures)}")
        print("        请查看 logs/demo_*.log 定位原因；可先 stop 再 start 重试")
    else:
        print(f"{C_OK} 全部就绪！")

    if pids.get("api"):
        print()
        print("  演示入口")
        if pids.get("frontend"):
            print("    ① 打开界面   http://127.0.0.1:5273   →  「AIOps 诊断」页")
        print("    ② 接口文档   http://127.0.0.1:8200/docs")
        print("    ③ 诊断端点   POST http://127.0.0.1:8200/api/v1/aiops  (SSE 流式)")
        print()
        print("  停止服务:  python scripts/launch_demo.py stop")

    if pids.get("frontend") and not args.no_browser:
        url = "http://127.0.0.1:5273"
        print(f"\n  正在打开浏览器: {url}")
        try:
            os.startfile(url)  # Windows
        except Exception:
            pass

    return 0 if not failures else 1


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
            errors="replace",
        )
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def _listener_pid(port: int) -> int | None:
    """找到监听指定端口的进程 PID（Windows netstat + tasklist 解析）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=8, errors="replace")
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                return int(parts[4])
    except Exception:
        pass
    return None


def _kill_port(port: int) -> bool:
    """按端口终止监听进程（含子进程树）。返回是否执行了终止。"""
    pid = _listener_pid(port)
    if pid is None:
        return False
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   capture_output=True, text=True, errors="replace")
    return True


def stop(_args) -> int:
    print("=" * 60)
    print("  停止演示环境")
    print("=" * 60)
    stopped = 0
    # 以端口为准（进程树里的孙进程也能清干净），PID 记录作兜底
    for key, name, port, cmd, url, required in SERVICES:
        if port_in_use(port):
            if _kill_port(port):
                print(f"{C_OK} {name}: 已停止（端口 {port}）")
                stopped += 1
        else:
            print(f"{C_INFO} {name}: 未在运行")
    # 兜底：PID 记录里还有存活的（非端口监听类）
    for key, info in load_pids().items():
        pid = info.get("pid")
        if pid and _pid_alive(pid):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, text=True, errors="replace")
            print(f"{C_OK} {info.get('name', key)} (PID {pid}) 已停止")
            stopped += 1
    if PID_FILE.exists():
        PID_FILE.unlink()
    print("-" * 60)
    print(f"{C_OK} 已停止 {stopped} 个服务" if stopped else f"{C_INFO} 没有需要停止的服务")
    return 0


def status(_args) -> int:
    print("=" * 60)
    print("  演示环境状态")
    print("=" * 60)
    pids = load_pids()
    n_run = 0
    for key, name, port, cmd, url, required in SERVICES:
        if port_in_use(port):
            pid = _listener_pid(port)
            print(f"{C_OK} {name}: 运行中（端口 {port}，PID {pid}）")
            n_run += 1
        else:
            print(f"{C_BAD} {name}: 未运行")
    print("-" * 60)
    if n_run:
        print(f"  共 {n_run} 个服务在运行")
        if port_in_use(5273):
            print("  界面入口: http://127.0.0.1:5273")
        if port_in_use(8200):
            print("  接口文档: http://127.0.0.1:8200/docs")
    print("  启动: python scripts/launch_demo.py start")
    print("  停止: python scripts/launch_demo.py stop")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="演示环境一键启停")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="启动全部服务")
    p_start.add_argument("--no-frontend", action="store_true", help="只启动后端（终端演示用）")
    p_start.add_argument("--no-browser", action="store_true", help="启动后不自动开浏览器")
    p_start.add_argument("--timeout", type=int, default=90, help="每个服务的就绪等待秒数")

    sub.add_parser("stop", help="停止全部服务")
    sub.add_parser("status", help="查看运行状态")

    args = ap.parse_args()
    # 统一用系统 python 运行本脚本没问题（只需标准库）；子进程用 .venv 的 python
    if args.cmd == "start":
        return start(args)
    if args.cmd == "stop":
        return stop(args)
    return status(args)


if __name__ == "__main__":
    sys.exit(main())
