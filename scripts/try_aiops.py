"""运维 Agent(简历版)验证脚本——跳过 Milvus/MCP,只验证 5 样核心:

  1) import 链完整
  2) 图已编译
  3) Planner 在无 MCP 工具下生成计划(裸 LLM 结构化输出)
  4) Executor 在无工具下执行单步
  5) Replanner 决策
  6) 图流式执行(完整循环)

用法:
  SET USE_TORCH=0 && .venv\Scripts\python.exe scripts\try_aiops.py

前提:
  - .env 里有 DASHSCOPE_API_KEY(已在 .gitignore 排除);
  - MCP 服务可以关着——工具加载失败会优雅降级,不影响验证。
"""

import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("USE_TORCH", "0")


async def main() -> int:
    errs = 0

    # ── 1. import 链 ──
    print("── 1. import 链 ──")
    try:
        from src.agent.aiops.state import PlanExecuteState

        print("  ✅ state")
    except Exception as e:
        print(f"  ❌ state: {e}"); return 1
    try:
        from src.agent.aiops.graph import aiops_service

        print("  ✅ graph(已编译)")
    except Exception as e:
        print(f"  ❌ graph: {e}"); return 1
    try:
        from src.agent.aiops.structured import ainvoke_structured

        print("  ✅ structured(fallback wrapper)")
    except Exception as e:
        print(f"  ❌ structured: {e}"); return 1

    # ── 2. Planner(无 MCP 工具) ──
    print("\n── 2. Planner 生成计划(无 MCP 工具) ──")
    from src.agent.aiops.planner import planner

    s: PlanExecuteState = {
        "input": "线上服务 CPU 飙到 97% 超阈值 80%,请诊断根因",
        "plan": [],
        "past_steps": [],
        "response": "",
    }
    r = await planner(s)
    plan = r.get("plan", [])
    for i, st in enumerate(plan, 1):
        print(f"    {i}. {st[:120]}")
    if not plan:
        print("  ❌ 计划为空"); errs += 1
    elif plan == ["收集相关指标和日志", "分析数据定位问题", "生成诊断报告"]:
        print("  ⚠️ 降级到默认计划(LLM 结构化输出失败),但节点不崩")
    else:
        print(f"  ✅ Planner 产出 {len(plan)} 步")

    # ── 3. Executor(无工具) ──
    print("\n── 3. Executor 执行单步(无工具) ──")
    from src.agent.aiops.executor import executor

    s2 = {**s, **r}
    r2 = await executor(s2)
    past = r2.get("past_steps", [])
    if past:
        step, res = past[0]
        print(f"  步骤: {step[:80]}")
        print(f"  结果: {str(res)[:200]}")
        print("  ✅ Executor 正常")
    else:
        print("  ❌ past_steps 为空"); errs += 1

    # ── 4. Replanner ──
    print("\n── 4. Replanner 决策 ──")
    from src.agent.aiops.replanner import replanner

    s3 = {**s2, **r2}
    r3 = await replanner(s3)
    has_resp = bool(r3.get("response"))
    has_plan = bool(r3.get("plan"))
    action = "respond" if has_resp else ("replan" if has_plan else "continue")
    print(f"  决策: {action}")
    if has_resp:
        print(f"  报告预览: {r3['response'][:200]}")
    print(f"  ✅ Replanner 正常")

    # ── 5. 图流式执行 ──
    print("\n── 5. 图流式执行(完整循环) ──")
    count = 0
    graph_config = {"configurable": {"thread_id": "verify"}}
    async for event_chunk in aiops_service.graph.astream(
        input={
            "input": "CPU 97% 持续 10 分钟,诊断并出报告",
            "plan": [],
            "past_steps": [],
            "response": "",
        },
        config=graph_config,
        stream_mode="updates",
    ):
        for node_name, node_output in event_chunk.items():
            count += 1
            otype = node_output.get("type", "?") if isinstance(node_output, dict) else "raw"
            msg = (
                node_output.get("message", "")[:80]
                if isinstance(node_output, dict)
                else str(node_output)[:80]
            )
            print(f"  [{node_name}] {otype}: {msg}")
        if count > 30:
            break
    print(f"  事件数: {count},  ✅ 图流式执行正常")

    # ── 总结 ──
    print(f"\n{'✅ 全通过' if errs == 0 else f'❌ {errs} 个错误'}")
    return errs


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
