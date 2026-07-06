"""Planner 节点:制定诊断计划。

流程:
  1. 用 VectorRetriever 查一次知识库,捞相关排查经验(best-effort,查不到不报错);
  2. 本地 runbook 降级检索(从 local_retrieval 模块);
  3. 加载 MCP 工具(指标/日志)列表,供 LLM 制定计划时参考用哪个工具;
  4. with_structured_output(Plan) 强制 LLM 输出步骤列表。
"""

from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.agent.aiops.local_retrieval import retrieve_local
from src.utils.logger import logger

_EXPERIENCE_TOP_K = 3


def _format_tools(tools: list) -> str:
    """把工具列表格式化成 名称 + 参数 + 描述 的多行文本。

    包含参数签名,让 Planner 生成步骤时使用正确的参数名,
    避免写出 duration='30m' 这种工具实际不存在的参数。
    """
    if not tools:
        return "(当前无可用工具)"
    lines = []
    for t in tools:
        # 提取参数 JSON schema (dict 或 Pydantic model)
        json_schema = None
        schema = getattr(t, "args_schema", None)
        if isinstance(schema, dict):
            json_schema = schema
        elif schema and hasattr(schema, "model_json_schema"):
            try:
                json_schema = schema.model_json_schema()
            except Exception:
                pass
        if json_schema is None:
            # fallback: tool_call_schema
            tc_schema = getattr(t, "tool_call_schema", None)
            if isinstance(tc_schema, dict):
                json_schema = tc_schema

        # 解析参数
        param_parts = []
        if json_schema:
            props = json_schema.get("properties", {})
            required = set(json_schema.get("required", []))
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                # Handle anyOf (Optional types)
                if "anyOf" in pinfo:
                    types = [a.get("type", "?") for a in pinfo["anyOf"] if a.get("type") != "null"]
                    ptype = types[0] if types else "any"
                desc = pinfo.get("description", "")
                default = pinfo.get("default")
                if pname in required:
                    param_parts.append(f"{pname}({ptype}, 必填): {desc}")
                elif default is not None:
                    param_parts.append(f"{pname}({ptype}, 默认={default}): {desc}")
                else:
                    param_parts.append(f"{pname}({ptype}, 可选): {desc}")

        params_block = "\n    ".join(param_parts) if param_parts else "无参数"
        # 截断 description 避免过长
        desc_short = t.description.split("\n")[0][:120]
        lines.append(f"- **{t.name}**: {desc_short}\n  参数:\n    {params_block}")
    return "\n".join(lines)


def _retrieve_experience(query: str, kb_ids: list = None) -> str:
    """查知识库捞排查经验。优先 HybridRetriever（向量+BM25+RRF），不可用时降级本地 runbooks。"""
    try:
        from src.retrieval.hybrid_retriever import HybridRetriever
        from src.retrieval.reranker import DashScopeReranker
        from src.settings import settings as app_settings

        retriever = HybridRetriever()
        reranker = DashScopeReranker() if app_settings.ENABLE_RERANK else None

        initial_k = _EXPERIENCE_TOP_K * 2 if reranker else _EXPERIENCE_TOP_K
        results = retriever.retrieve(query, top_k=initial_k, kb_ids=kb_ids)

        if reranker and results:
            results = reranker.rerank(query, results)
            results = results[:_EXPERIENCE_TOP_K]

        if results:
            parts = [f"【经验 {i}】{r.text}" for i, r in enumerate(results, 1)]
            block = "\n".join(parts)
            return dedent(
                f"""
                ## 相关排查经验
                以下是从知识库检索到的经验,请参考:
                {block}
                ---
                """
            ).strip()
        local = retrieve_local(query)
        if local:
            logger.info("[planner] 降级到本地 runbook 经验")
            return local
        return ""
    except Exception as e:
        logger.warning(f"[planner] 经验检索失败,尝试本地: {e}")
        return retrieve_local(query)


class Plan(BaseModel):
    """计划输出格式。"""

    steps: List[str] = Field(
        description="完成诊断所需的步骤,按顺序执行,每步说明用哪个工具(若需要)及参数。"
    )


planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是一个专家级运维诊断规划者,负责把故障诊断任务拆成可执行的步骤。

                可用工具列表(制定计划时**必须**使用每个工具的实际参数名):
                {tools_description}

                {experience_context}

                诊断流程建议:
                1. 先用监控工具(query_cpu_metrics/query_memory_metrics)获取实时指标数据;
                2. 如果指标异常,用 search_knowledge_base 从知识库检索相关的故障排查文档;
                3. 用 search_log 查看相关日志;
                4. 结合监控数据、知识库文档和日志,给出根因分析和修复建议。

                请为给定任务创建简单、逐步的计划。要求:
                - 每步逻辑独立,明确用哪个工具(如需)及**实际参数名和示例值**;
                - **严禁**发明工具参数列表中不存在的参数名(如 duration 不存在于 query_cpu_metrics);
                - 时间范围用 start_time/end_time 而非 duration;
                - 建议先调用 get_current_timestamp 获取当前时间,再据此计算时间范围;
                - 若需要查知识库,先用 list_knowledge_bases 获取可用知识库列表,再用 search_knowledge_base;
                - 步骤之间有清晰依赖;
                - 若有相关经验文档,参考其中的排查方法;
                - 步骤要具体可操作,不要空泛。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """规划节点:据输入生成诊断步骤列表。"""
    logger.info("=== Planner:制定诊断计划 ===")
    input_text = state.get("input", "")

    try:
        experience_context = _retrieve_experience(input_text)
        tools, err = await load_agent_tools()
        if err:
            logger.warning(f"[planner] MCP 工具加载失败: {err}")
        tools_description = _format_tools(tools)

        llm = create_agent_llm(temperature=0)
        result = await ainvoke_structured(llm, Plan, planner_prompt, {
            "messages": [("user", input_text)],
            "tools_description": tools_description,
            "experience_context": experience_context,
        })
        steps = result.steps
        logger.info(f"[planner] 计划已生成,共 {len(steps)} 步")
        return {"plan": steps}

    except Exception:
        logger.exception("[planner] 生成计划失败,用默认计划")
        return {"plan": ["收集相关指标和日志", "分析数据定位问题", "生成诊断报告"]}
