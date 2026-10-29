#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""带故障靶场的端到端诊断验收（2026-10-09 建立）

流程：
  1) 启动带故障的演示站点（scripts/tools/faulty_demo_site.py，埋 4 类问题）
  2) 启动诊断服务栈（MCP×3 + FastAPI）
  3) 让诊断 Agent 去查这个站点
  4) 记录：**耗时** + **真实 token 消耗** + 折算费用

用法：
    python scripts/run_demo_diagnosis.py                    # 完整流程
    python scripts/run_demo_diagnosis.py --keep-running     # 结束后保留服务（方便打开界面看）
    python scripts/run_demo_diagnosis.py --query "自定义诊断语句"
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SITE_PORT = 8090
SITE_URL = f"http://127.0.0.1:{SITE_PORT}/"


def port_ok(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def wait_port(port: int, secs: int = 60) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if port_ok(port):
            return True
        time.sleep(1)
    return False


def start_site() -> subprocess.Popen | None:
    if port_ok(SITE_PORT):
        print(f"  靶场已在运行: {SITE_URL}")
        return None
    print(f"  启动靶场（带故障站点）: {SITE_URL}")
    p = subprocess.Popen([sys.executable, str(ROOT / "tools" / "faulty_demo_site.py"), str(SITE_PORT)],
                         cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_port(SITE_PORT, 20):
        print("  ❌ 靶场启动失败")
        return None
    return p


def login() -> str:
    body = urllib.parse.urlencode(
        {"username": "demo_check", "password": "demo123456", "grant_type": "password"}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8200/api/v1/auth/login/access-token", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with opener.open(req, timeout=15) as r:
        return json.loads(r.read().decode())["access_token"]


def run_diagnosis(query: str) -> dict:
    token = login()
    req = urllib.request.Request(
        "http://127.0.0.1:8200/api/v1/aiops",
        data=json.dumps({"query": query}).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "Accept": "text/event-stream"})

    report, steps, usage = "", [], {}
    t0 = time.time()
    with opener.open(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except Exception:
                continue
            et = evt.get("type", "")
            if et == "plan":
                plan = evt.get("plan") or []
                print("  [计划]")
                for i, s in enumerate(plan, 1):
                    print(f"      {i}. {str(s)[:100]}")
            elif et == "step_complete":
                steps.append(str(evt.get("step", "")))
                print(f"  [完成] {str(evt.get('step',''))[:100]}")
            elif et in ("report", "complete"):
                report = evt.get("report") or evt.get("response") or report
            elif et == "usage":
                usage = evt
            elif et == "error":
                print(f"  [错误] {evt.get('message','')[:150]}")
    elapsed = time.time() - t0
    return {"report": report, "steps": steps, "usage": usage, "elapsed_s": elapsed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=f"帮我全面检查网站 {SITE_URL} 有没有问题")
    ap.add_argument("--keep-running", action="store_true", help="结束后保留服务")
    ap.add_argument("--no-site", action="store_true", help="不启动靶场（查外部真实网站时用）")
    args = ap.parse_args()

    print("=" * 72)
    print("  带故障靶场 · 端到端诊断验收")
    print("=" * 72)

    site_proc = None
    print("\n① 靶场")
    if not args.no_site:
        site_proc = start_site()
        print("  埋的故障: /logo.png(404) /api/orders/slow(慢4.2s) /api/orders/500(500) /health/ready(403)")
    else:
        print("  (跳过，直接查目标网站)")

    print("\n② 启动诊断服务栈")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "launch_demo.py"),
                    "start", "--no-frontend", "--no-browser"],
                   capture_output=True, text=True, timeout=300)
    if not wait_port(8200, 60):
        print("  ❌ 后端未就绪")
        return 1
    print("  服务就绪")

    print(f"\n③ 诊断任务: {args.query}")
    r = run_diagnosis(args.query)

    print("\n" + "=" * 72)
    print("  诊断报告")
    print("=" * 72)
    print(r["report"][:2400] if r["report"] else "(无报告)")

    print("\n" + "=" * 72)
    print("  真实损耗统计")
    print("=" * 72)
    u = r["usage"] or {}
    print(f"  总耗时        : {r['elapsed_s']:.1f} s")
    print(f"  LLM 调用次数  : {u.get('llm_calls', '无数据')}")
    print(f"  输入 token    : {u.get('input_tokens', '无数据'):,}" if isinstance(u.get('input_tokens'), int) else f"  输入 token    : 无数据")
    print(f"  输出 token    : {u.get('output_tokens', '无数据'):,}" if isinstance(u.get('output_tokens'), int) else f"  输出 token    : 无数据")
    if isinstance(u.get("total_tokens"), int):
        print(f"  合计 token    : {u['total_tokens']:,}")
    print(f"  折算费用(估算): ¥{u.get('cost_cny_estimated', '无数据')}")
    if u.get("by_model"):
        for m, s in u["by_model"].items():
            print(f"      {m}: {s.get('calls')} 次, 入 {s.get('in')}, 出 {s.get('out')}")

    if site_proc is not None and not args.keep_running:
        site_proc.terminate()
        print("\n（靶场已停止）")
    if not args.keep_running:
        print("提示: 服务仍在运行，用 python scripts/launch_demo.py stop 停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
