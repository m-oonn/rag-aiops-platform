"""Planner 节点:制定诊断计划。

流程:
  1. 用 VectorRetriever 查一次知识库,捞相关排查经验(best-effort,查不到不报错);
  2. 本地 runbook 降级检索(从 local_retrieval 模块);
  3. 加载 MCP 工具(指标/日志)列表,供 LLM 制定计划时参考用哪个工具;
  4. with_structured_output(Plan) 强制 LLM 输出步骤列表。
"""

from textwrap import dedent
from typing import Any, Dict, List
import os

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.agent.aiops.local_retrieval import retrieve_local
from src.utils.logger import logger

_EXPERIENCE_TOP_K = 2  # 少 tokens(2026-09-23): 3→2, 2 条相关经验足够参考

# 计划步数硬上限：与 DynamicClassificationStrategy._MAX_STEPS 匹配，
# 防止 LLM 生成超长计划导致"步数上限强制 respond"时 Top1 尚未收敛。
_MAX_PLAN_STEPS = 6


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


def _compress_case(text: str, max_chars: int = 700) -> str:
    """压缩知识库案例文本: 优先保留根因/解决方案段落(heading 语义段), 并截断到 max_chars。

    openEuler 案例为半结构化 Markdown(#标题/#内核版本/#问题现象/#问题根因/#解决方案)。
    现象段最长且对诊断价值低, 诊断需要的是"根因+解法", 借此少 tokens(2026-09-23)。
    非半结构文本直接截断, 保标题。
    """
    if not text:
        return text
    out_parts = [text.strip()]
    if len(text) <= max_chars:
        return text.strip()
    # 只保留含 根因/解决/方案/排查 的段落
    key_secs = []
    cur_title = ""
    cur_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            if cur_title and any(k in cur_title for k in ("根因", "解决", "方案", "排查", "处理", "修复")):
                key_secs.append((cur_title, " ".join(cur_lines)))
            cur_title = line
            cur_lines = []
        else:
            cur_lines.append(line)
    if cur_title and any(k in cur_title for k in ("根因", "解决", "方案", "排查", "处理", "修复")):
        key_secs.append((cur_title, " ".join(cur_lines)))
    if key_secs:
        # 段内容短是预期(只要根因+解法, 恰恰是少 token 目标), 不必与原文比值兜底
        joined = "\n".join(f"{t}: {c}" for t, c in key_secs)
        return joined[:max_chars]
    return out_parts[0][:max_chars]


def _retrieve_experience(query: str, kb_ids: list = None) -> str:
    """查知识库捞排查经验。优先 HybridRetriever（向量+BM25+RRF），不可用时降级本地 runbooks。

    A/B 对照开关(2026-09-16): 环境变量 ENABLE_EXPERIENCE_CONTEXT=false 时跳过知识检索,
    用于量化"经验注入"对诊断的净贡献; 默认开启, 不影响现有行为。
    """
    if os.environ.get("ENABLE_EXPERIENCE_CONTEXT", "true").strip().lower() in ("0", "false", "no", "off"):
        return ""
    try:
        from src.retrieval.hybrid_retriever import HybridRetriever
        from src.retrieval.reranker import DashScopeReranker
        from src.settings import settings as app_settings

        retriever = HybridRetriever()
        reranker = DashScopeReranker() if app_settings.ENABLE_RERANK else None

        # 知识噪声修复(2026-09-16): 检索源白名单 + 相关性阈值
        #   kb_ids 默认 None(全部知识库), 可通过 settings.EXPERIENCE_KB_IDS 限定
        #   只检索运维案例库, 排除功能测试上传的"运维排查手册"等误导性文档。
        exp_kb_ids = None
        if app_settings.EXPERIENCE_KB_IDS:
            exp_kb_ids = [
                int(x) for x in str(app_settings.EXPERIENCE_KB_IDS).split(",") if x.strip()
            ]
        min_score = float(getattr(app_settings, "EXPERIENCE_MIN_SCORE", 0.0) or 0.0)

        initial_k = _EXPERIENCE_TOP_K * 2 if reranker else _EXPERIENCE_TOP_K
        results = retriever.retrieve(query, top_k=initial_k, kb_ids=exp_kb_ids, min_score=min_score)

        if reranker and results:
            results = reranker.rerank(query, results)
            results = results[:_EXPERIENCE_TOP_K]

        if results:
            # 少 tokens(2026-09-23): 案例压缩到根因+解法段, 再注入 prompt
            parts = [f"【经验 {i}】{_compress_case(r.text)}" for i, r in enumerate(results, 1)]
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
        description=(
            "完成诊断所需的步骤,按顺序执行。每步必须是一句通顺的大白话,"
            "讲清'这一步做什么、查什么'(读者是不懂技术的用户);"
            "禁止出现工具函数名、参数赋值或其他代码写法。"
        )
    )


planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是一个专家级运维诊断规划者,负责把故障诊断任务拆成可执行的步骤。
                你的"步骤文案"会展示给不懂技术的用户看,必须是人话(详见下方写法要求)。

                可用工具列表(告诉你具备哪些能力,用来判断步骤是否可行;
                **注意:步骤文案里不要出现工具名和参数**,执行器会自动选择合适的工具):
                {tools_description}

                {experience_context}

                诊断规划原则:不要生搬硬套统一流程。先根据故障征兆判断最可能的故障类型,
                选择与之匹配的主诊断路径,只挑与当前故障强相关的工具与步骤,宁可精简也不凑数。

                主诊断路径(按征兆对应,选最契合的一套聚焦执行,不必全部覆盖工具):
                - 网络/连通性:延迟、丢包、连接超时、连通性错误、DNS 解析失败等 → 优先查
                  网络/连通性指标与日志中的网络错误;若观测含混沌/故障注入,根因锁定为网络;
                - 网址/网站健康检查:**用户直接给出网址(URL)**、或要求检查某网站能否访问
                  → 通常**一步完成**:实际访问该网站检查能否正常打开,并逐个检查首页里的
                  链接和图片资源是否正常(一步即可覆盖全面检查,不必拆成两步);
                  按探测结果给出结论;**如实报告**:网站正常就写"网站正常"(可附状态码/耗时),
                  访问不了就报告具体错误类型;**严禁**臆造不存在的故障;
                - 页面能打开但功能/任务异常(**重要,别漏**):用户说"网页能打开,但点某功能
                  报错/提交没反应/任务一直不返回/审校卡住"这类"页面好、服务坏"的故障 →
                  页面检查看不出来,**必须下沉到业务层**:规划成"检查该服务的健康端点/业务
                  接口是否正常(状态码、是否超时、返回内容)",必要时再查后台日志;
                  **不要把结论停在"网站正常"**,也不要把根因直接归到"资源耗尽"——
                  页面正常不等于后台服务正常;
                - 服务未启动 / 端口不通:用户给出 `主机:端口`、或怀疑"某个服务没起来" →
                  规划成"探测该主机的端口是否有服务在监听";**同机/同网段**下端口"连接被拒绝"
                  说明服务未启动,端口"连接超时"只能说明网络层不可达(不能据此断定服务状态);
                - 基础设施/资源瓶颈:CPU/内存/连接池/线程/IO 等资源耗尽、慢查询、任务堆积
                  超载 → 优先查资源类指标、连接数、进程/线程状态、队列长度;
                - 应用层异常:服务崩溃、5xx、接口超时、错误堆栈、近期发布/回滚、SDK/依赖
                  行为变更 → 优先查应用日志、错误堆栈、发布记录;
                - 配置错误:配置下发、参数/阈值/超时设置不合理 → 优先核对配置变更时间线,
                  并结合日志中配置相关报错;
                - 变更/发布引入(重要,别漏):故障时间点与发布、部署、配置变更、灰度或回滚
                  高度吻合(如"刚上线/刚发版/刚改过配置就出问题")→ 规划一步"查该服务近期的
                  变更/发布记录",把变更时间与故障发生时间对齐;排查资源/应用/配置类故障时,
                  若怀疑与近期改动相关,也应补一步变更核对(变更与指标/日志是相互独立的证据);
                - 外部依赖:数据库/消息队列/缓存等依赖不可用、连接失败、MQ 堆积 → 优先查
                  依赖可用性、连接错误、消费端 lag/积压。

                步骤写法(重要——步骤文案会直接展示给不懂技术的用户看):
                - 每一步用一句通顺的大白话讲清"这一步要做什么、查什么",像给同事交代任务;
                - **禁止**出现工具函数名(如 check_website、search_log、query_cpu_metrics)、
                  参数赋值写法(如 url=…、deep=true、timeout_s=10.0)或任何代码符号;
                - **禁止**写"如果…则…否则…"的条件指令长句——结论由最后的报告统一给出;
                - 必要的具体信息(用户给的目标网址、服务名、要查的关键词等)要用自然语言
                  写进步骤。示例:"检查网站 https://example.com/ 能否正常打开,
                  并逐个检查首页里的链接和图片资源是否正常";

                执行要求:
                - 整个计划不超过 6 步,聚焦关键排查路径,不用覆盖全部工具;
                - **严禁臆造规划阶段无法得知的标识符值**(如日志主题 id、具体时间戳)。
                  这类值只能在实际执行时从前序步骤的结果里拿到,要用前后衔接的话表达
                  (例:"先找到该服务的日志主题,再查看它最近的错误日志"),**不要写死**
                  'log-topic-xxx-001' 之类的假 id,也不要写具体时间数值;
                - 时间范围用"最近 15 分钟"这类自然说法即可,执行器会自动处理精确时间;
                - 仅当确实需要参考知识库经验时,才加一步"检索知识库里的相关排查经验",
                  不需要就直接跳过;
                - 步骤之间有清晰依赖;若有相关经验文档,参考其中的排查方法;
                - 步骤要具体可操作。同一类型故障尽量复用同类排查手段,避免堆砌无意义步骤;
                - 若某一步需要同时采集多个**相互独立**的数据源(如监控指标与系统日志),
                  在该步描述前加 `[并行]` 前缀,执行器会并发采集这两类观测。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """规划节点:据输入生成诊断步骤列表。"""
    logger.info("=== [role=planner] Planner:制定诊断计划 ===")
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
        # 硬截断，防止 LLM 输出超长计划（超长计划会撞上策略的步数上限，
        # 在 Top1 未收敛时就强制 respond）
        if len(steps) > _MAX_PLAN_STEPS:
            logger.warning(f"[planner] 计划 {len(steps)} 步超过上限 {_MAX_PLAN_STEPS},截断")
            steps = steps[:_MAX_PLAN_STEPS]
        logger.info(f"[planner] 计划已生成,共 {len(steps)} 步")
        return {"plan": steps}

    except Exception:
        logger.exception("[planner] 生成计划失败,用默认计划")
        return {"plan": ["收集相关指标和日志", "分析数据定位问题", "生成诊断报告"]}
