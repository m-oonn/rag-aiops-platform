"""
mini_agent_pne.py — 从零手搓的最小 Plan-and-Execute-Replan Agent
不依赖 LangGraph, 仅复用项目 LLM 工厂 (src.agent.aiops_llm.create_agent_llm)。

闭环: Planner 出步骤 -> Executor 执行 plan[0] 并调 calculator 工具 -> Replanner 决定 continue / respond
对照: src/agent/aiops/ 下的完整实现 (planner / executor / replanner / graph)

运行: 从项目根目录执行  python scripts/mini_agent_pne.py
"""
import sys
import os
import json
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.aiops_llm import create_agent_llm


# ----------------------------------------------------------------------------
# 工具 (Tools)
# ----------------------------------------------------------------------------
def calculator(expr: str) -> str:
    """极简安全计算器: 只允许数字与 +-*/(). 空格, 用受限 eval 执行。"""
    allowed = set("0123456789+-*/(). ")
    if not set(expr) <= allowed:
        return "error: 含非法字符"
    try:
        val = eval(expr, {"__builtins__": {}}, {})
        return f"{expr} = {val}"
    except Exception as e:
        return f"error: {e}"


TOOLS = {"calculator": calculator}


# ----------------------------------------------------------------------------
# 基础设施: 让 LLM 返回 JSON (从零实现, 不依赖 with_structured_output)
# ----------------------------------------------------------------------------
def _call_llm_json(llm, system: str, user: str) -> dict:
    msg = llm.invoke([
        SystemMessage(content=system + "\n只返回 JSON, 不要多余文字。"),
        HumanMessage(content=user),
    ])
    text = msg.content if hasattr(msg, "content") else str(msg)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


# ----------------------------------------------------------------------------
# Planner 节点
# ----------------------------------------------------------------------------
PLANNER_SYS = (
    "你是任务规划专家。把用户任务拆成有序、独立的执行步骤。"
    "如果需要计算, 步骤里写明'调用 calculator 计算: <表达式>'。"
)


def planner(llm, task: str) -> list:
    out = _call_llm_json(
        llm, PLANNER_SYS,
        f"任务: {task}\n返回JSON: {{\"steps\": [步骤1, 步骤2, ...]}}",
    )
    steps = out.get("steps", [])
    return steps if isinstance(steps, list) else []


# ----------------------------------------------------------------------------
# Executor 节点
# ----------------------------------------------------------------------------
EXECUTOR_SYS = (
    "你是执行专家, 负责完成单个步骤。"
    "如果该步骤需要计算, 请返回 use_tool=true 并给出 expr(纯算术表达式, 如 100*0.8)。"
    "否则 use_tool=false, 直接给 answer。"
)


def execute_step(llm, step: str, history: list) -> str:
    hist_text = "\n".join(f"- {s}: {r}" for s, r in history) or "(无)"
    user = (
        f"已完成步骤:\n{hist_text}\n\n当前步骤: {step}\n"
        f"返回JSON: {{\"use_tool\": bool, \"expr\": \"\", \"answer\": \"\"}}"
    )
    out = _call_llm_json(llm, EXECUTOR_SYS, user)
    if out.get("use_tool") and out.get("expr"):
        tool_res = calculator(out["expr"])
        return f"[调calculator] {tool_res}\n结论: {out.get('answer', '')}"
    return out.get("answer", str(out))


# ----------------------------------------------------------------------------
# Replanner 节点 (简化版: continue / respond 两决策)
# ----------------------------------------------------------------------------
REPLANNER_SYS = (
    "你是复盘专家。根据已完成步骤判断是否可以输出最终答案。"
    "若信息已足够, 返回 action='respond' 并给 report; 否则 action='continue'。"
)


def replanner(llm, task: str, history: list) -> dict:
    hist_text = "\n".join(f"- {s}: {r}" for s, r in history) or "(无)"
    user = (
        f"原始任务: {task}\n已完成:\n{hist_text}\n"
        f"返回JSON: {{\"action\": \"continue|respond\", \"report\": \"\"}}"
    )
    return _call_llm_json(llm, REPLANNER_SYS, user)


# ----------------------------------------------------------------------------
# 主循环
# ----------------------------------------------------------------------------
def run(task: str, model: str = "qwen-plus", max_steps: int = 6) -> str:
    llm = create_agent_llm(model=model, temperature=0)
    print(f"\n=== 任务: {task} ===")
    plan = planner(llm, task)
    print(f"[Planner] 计划 {len(plan)} 步:")
    for i, s in enumerate(plan, 1):
        print(f"   {i}. {s}")

    past = []
    while plan and len(past) < max_steps:
        step = plan[0]
        print(f"\n[Executor] 执行: {step}")
        result = execute_step(llm, step, past)
        past.append((step, result))
        print(f"   结果: {result[:200]}")

        decision = replanner(llm, task, past)
        action = decision.get("action", "continue")
        print(f"[Replanner] 决策: {action}")

        if action == "respond":
            report = decision.get("report", "")
            print(f"\n=== 最终报告 ===\n{report}")
            return report
        plan = plan[1:]

    return "超过最大步数, 未完成。"


if __name__ == "__main__":
    task = (
        "某商品原价 100 元, 先打 8 折, 再满 200 减 30(不满不减), "
        "最后加 13% 增值税。求最终到手价, 并分步验证。"
    )
    run(task)
