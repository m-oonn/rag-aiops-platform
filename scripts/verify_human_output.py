# -*- coding: utf-8 -*-
"""端到端验证「人话化」诊断输出（2026-10-09 建立）。

用途：在 UI 演示前快速核对诊断步骤与报告是否"人人看得懂"。
注意：真实调用 DeepSeek（每个场景约 0.1~0.3 元），需 MCP 服务已启动。
场景 faulty 需先启动演示靶站: python tools/faulty_demo_site.py 8090

用法: .venv/Scripts/python.exe scripts/verify_human_output.py [web|faulty|cpu|all]
"""
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src.agent.aiops import aiops_service  # noqa: E402


async def run(query: str, tag: str) -> str:
    print(f"\n{'=' * 70}\n场景[{tag}] 任务: {query}\n{'=' * 70}")
    report = ""
    async for evt in aiops_service.execute(user_input=query, session_id=f"e2e-{tag}"):
        t = evt.get("type")
        if t == "plan":
            print("\n--- 诊断计划 ---")
            for i, s in enumerate(evt.get("plan", []), 1):
                print(f"  {i}. {s}")
        elif t == "report":
            report = evt.get("report", "")
        elif t == "complete":
            report = report or evt.get("response", "")
        elif t == "error":
            print("!! ERROR:", evt.get("message"))
    print("\n--- 最终报告 ---")
    print(report)
    print(f"\n[报告长度 {len(report)}]")
    return report


CASES = {
    "web": ("帮我检查网站 https://deeppub.keyanjia.com/ 是否正常", "web"),
    "faulty": ("帮我检查网站 http://127.0.0.1:8090/ 是否正常", "faulty"),
    "cpu": ("数据同步服务 CPU 飙升，定位原因", "cpu"),
}


async def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "web"
    keys = list(CASES) if which == "all" else [which]
    for key in keys:
        query, tag = CASES[key]
        await run(query, tag)


if __name__ == "__main__":
    asyncio.run(main())
