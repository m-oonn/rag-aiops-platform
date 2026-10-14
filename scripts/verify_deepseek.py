#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DeepSeek 切换验证 + 端到端自检（2026-10-09）

用途：切到 DeepSeek 官方 API 后，一条命令验证整条链路。
    1) 配置解析检查（BASE_URL / KEY / MODEL）
    2) DeepSeek API 连通性（无效 key 也能测出 401=网络通）
    3) 【可选】真实诊断端到端测试（需有效 key + 服务已启动，会产生极少 API 费用）

用法：
    python scripts/verify_deepseek.py            # 只做 1+2（零成本）
    python scripts/verify_deepseek.py --full     # 加做 3（真实跑一次诊断，约 1 毛钱）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener_proxy = urllib.request.build_opener()


def step1_config() -> tuple[bool, str, str]:
    """检查配置解析。"""
    print("=" * 64)
    print("  ① 配置解析检查")
    print("=" * 64)
    from src.settings import settings
    base = settings.RESOLVED_LLM_API_BASE
    key = settings.RESOLVED_LLM_API_KEY or ""
    model = settings.AGENT_MODEL
    print(f"  BASE_URL : {base}")
    print(f"  API_KEY  : {key[:8]}****（{len(key)} 字符）")
    print(f"  AGENT_MODEL: {model}")
    problems = []
    if "deepseek.com" not in base:
        problems.append(f"BASE_URL 未指向 DeepSeek（当前 {base}）")
    if not key or key.startswith("填入"):
        problems.append("API_KEY 还没填（.env 里 LLM_API_KEY=填入你的DeepSeekKey）")
    elif len(key) < 20:
        problems.append(f"API_KEY 长度可疑（{len(key)} 字符，正常应 ≥20）")
    if not model.startswith("deepseek"):
        problems.append(f"AGENT_MODEL 不是 DeepSeek 模型（当前 {model}）")
    if problems:
        for p in problems:
            print(f"  ❌ {p}")
        return False, base, key
    print("  ✅ 配置正确")
    return True, base, key


def step2_reachability(base: str) -> bool:
    """网络连通性 + key 有效性（直接用真 key 打一个 1-token 请求）。"""
    print()
    print("=" * 64)
    print("  ② API 连通性与 Key 有效性")
    print("=" * 64)
    url = base.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + (__import__("src.settings", fromlist=["settings"]).settings.RESOLVED_LLM_API_KEY or ""),
    })
    try:
        with opener_direct.open(req, timeout=20) as r:
            print(f"  ✅ API 调用成功（HTTP {r.status}）—— key 有效、余额可用")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        if e.code == 401:
            print("  ❌ 401 认证失败 —— key 无效或没填对")
        elif e.code == 402:
            print("  ❌ 402 余额不足 —— 请到 platform.deepseek.com 充值")
        else:
            print(f"  ❌ HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"  ❌ 网络错误: {type(e).__name__} {str(e)[:100]}")
        return False


def step3_e2e() -> bool:
    """端到端：启动服务 → 发诊断 → 看结果（真实调用 LLM，按量计费）。"""
    print()
    print("=" * 64)
    print("  ③ 端到端诊断测试（真实调用，会产生少量费用）")
    print("=" * 64)

    def wait_ok(url, secs=90):
        end = time.time() + secs
        while time.time() < end:
            try:
                with opener_direct.open(url, timeout=3):
                    return True
            except Exception:
                time.sleep(2)
        return False

    subprocess.run([sys.executable, str(ROOT / "scripts" / "launch_demo.py"),
                    "start", "--no-frontend", "--no-browser"],
                   capture_output=True, text=True, timeout=240)
    print("  服务启动完成，等待后端就绪 ...")
    if not wait_ok("http://127.0.0.1:8200/docs", 90):
        print("  ❌ 后端未就绪，请查看 logs/demo_api.log")
        return False
    print("  ✅ 后端就绪")

    # 登录（demo 账号）
    body = urllib.parse.urlencode(
        {"username": "demo_check", "password": "demo123456", "grant_type": "password"}
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8200/api/v1/auth/login/access-token", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener_direct.open(req, timeout=15) as r:
            token = json.loads(r.read().decode())["access_token"]
    except Exception as e:
        print(f"  ❌ 登录失败（{e}）；若 demo_check 账号不存在，先注册或换账号")
        return False

    # 发诊断请求
    query = "帮我检查网站 https://www.baidu.com 是否正常"
    req = urllib.request.Request(
        "http://127.0.0.1:8200/api/v1/aiops",
        data=json.dumps({"query": query}).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}",
                 "Accept": "text/event-stream"})
    print(f"  诊断任务: {query}")
    report, called = "", False
    t0 = time.time()
    try:
        with opener_direct.open(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue
                et = evt.get("type", "")
                if et == "step_complete":
                    if "check_website" in json.dumps(evt, ensure_ascii=False):
                        called = True
                    print(f"    [步骤] {str(evt.get('step',''))[:80]}")
                elif et in ("report", "complete"):
                    report = evt.get("report") or evt.get("response") or report
                elif et == "error":
                    print(f"    [错误] {evt.get('message','')[:120]}")
    except Exception as e:
        print(f"  流式读取异常: {e}")

    print(f"\n  耗时 {time.time()-t0:.0f}s")
    print("-" * 64)
    print(report[:1200] if report else "(无报告)")
    print("-" * 64)
    ok = bool(report) and "Arrearage" not in report and "BadRequest" not in report
    print(f"  结果: {'✅ 端到端跑通' if ok else '❌ 未通过（见上方输出）'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="加做端到端诊断测试（产生少量费用）")
    args = ap.parse_args()

    ok1, base, _ = step1_config()
    if not ok1:
        print("\n请先在 .env 里填好 LLM_API_KEY，再运行本脚本。")
        return 1
    ok2 = step2_reachability(base)
    if not ok2:
        return 1
    if args.full:
        ok3 = step3_e2e()
        return 0 if ok3 else 1
    print()
    print("=" * 64)
    print("  ① ② 全部通过 ✅")
    print("  如需端到端诊断测试: python scripts/verify_deepseek.py --full")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
