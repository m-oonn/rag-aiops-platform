"""Executor 节点:执行计划中的下一个步骤。

设计取舍:
  - 无工具时让 LLM 基于现有信息直接分析,不反问用户(反问在 demo 里是坏体验);
  - 有工具时 bind_tools + 手动工具执行(绕过 ToolNode 与 langchain-mcp-adapters
    的配置键兼容问题);
  - 执行完移除该步、把 (步骤, 结果) 追加进 past_steps。

注意:langchain-mcp-adapters 0.2.1 的 MCP 工具(StructuredTool)不含 config 属性,
而 langgraph-prebuilt>=1.1 的 ToolNode 强制要求 config → Missing required
config key 'N/A' for 'tools'。故手写工具调用,不依赖 ToolNode。
"""

import json
import os
import re

import asyncio
import time
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops_llm import create_agent_llm
from src.settings import settings
from src.utils.logger import logger
from src.utils.metrics import AIOPS_PARALLEL_BATCHES, AIOPS_TOOL_CALLS_TOTAL

_EXECUTOR_SYSTEM = """你是资深运维诊断专家,负责执行单个诊断步骤。

原则:
1. 理解步骤目标;
2. 有可用工具就调用工具获取真实数据;无工具则基于你的运维知识给出合理分析;
3. **调用工具时,必须使用 bind_tools 注册的实际参数名**(如 start_time/end_time/interval),
   步骤描述中若提到不存在的参数名(如 duration),忽略它,以工具 schema 为准;
4. 结果要具体可操作,不要反问用户或要求提供更多信息;
5. 只返回实际获取的信息或基于知识的分析,不要编造数据;
6. 专注当前步骤,不考虑其他任务;
7. **必须复用先前步骤的产物**: 若本步需要某个标识符(如 topic_id、kb_id、
   service_name、task_id 等)或时间戳,优先从"已完成的步骤及结果"/"可用真实标识符"
   中工具的真实返回里提取,将其作为工具参数的真实值调用;
   **严禁**使用计划文本或本步描述中的示例/占位值(例如形如 'log-topic-api-gateway-001'
   的占位 topic_id,或写死的假时间戳);
   8. **不得因标识符是占位而跳过工具**: 只要本次给出的"可用真实标识符"里存在某步骤
   所需工具(如 search_log)需要的真实 topic_id,且本步明确要求查日志,就**必须调用该工具**，
   用真实 topic_id + 真实时间窗执行,并以工具返回结果作答;不要自行"认为查不到"而不调用。"""

_NO_TOOLS_WARNING = """
⚠️ 重要提醒：当前没有可用的监控/日志工具，你无法获取任何真实系统数据。
在回答时你必须：
- 明确声明"以下分析基于通用运维经验，未获取到实际监控数据"；
- 不要编造具体的 CPU 数值、内存数值、日志内容等；
- 给出的建议应标注为"排查建议"而非"诊断结论"。"""

_TOOLS_CACHE_TTL = 30.0  # 工具列表缓存过期时间(秒)
_tools_cache: tuple[list, str | None] | None = None
_tools_cache_at: float = 0.0
_TOOL_INVOKE_TIMEOUT = 15.0  # 单个工具调用超时(秒)


def _build_tool_map(tools: list) -> dict[str, Any]:
    """把工具列表建成 {name: tool} 字典,便于按 name 查找。"""
    return {t.name: t for t in tools}


# 从工具返回文本里抽取真实标识符(如 topic_id/task_id/kb_id)的关键字:
# 优先匹配 "topic_id=xxx" / "topic_id: xxx" / "'xxx'" 等形式。
_IDENTIFIER_PATTERNS = [
    (r"topic_id\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", "topic_id"),
    (r"task_id\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", "task_id"),
    (r"kb_id\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", "kb_id"),
]


def _extract_real_identifiers(histories: list) -> str:
    """从 past_steps 的真实返回里确定性地抽取 topic_id 等标识符,拼成提示块。

    这样不再依赖 LLM 从长文本里自行寻找，只要前置工具确实返回了真实 id，
    就能稳定、可复现地把它喂给后续步骤。
    """
    found: dict[str, set] = {}
    for _s, r in histories:
        text = str(r)
        for pat, key in _IDENTIFIER_PATTERNS:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                val = m.strip()
                # 过滤掉明显的占位/示例值
                if not val or val.lower().startswith(("log-topic-", "log_topic_")):
                    continue
                found.setdefault(key, set()).add(val)
    if not found:
        return ""
    lines = []
    for key in ("topic_id", "task_id", "kb_id"):
        vals = found.get(key)
        if vals:
            for v in sorted(vals):
                lines.append(f"  {key} = {v}")
    return "可用真实标识符(本步如需要,务必使用这些真实值调用工具):\n" + "\n".join(lines)


async def _get_tools_cached() -> tuple[list, str | None]:
    """获取工具列表,30s TTL 模块级缓存。"""
    global _tools_cache, _tools_cache_at
    now = time.monotonic()
    if _tools_cache is not None and (now - _tools_cache_at) < _TOOLS_CACHE_TTL:
        return _tools_cache
    tools, err = await load_agent_tools()
    if err and not tools:
        logger.warning(f"[executor] MCP 工具加载失败(全不可用): {err}")
        _tools_cache = ([], err)
    elif err:
        # 部分服务可用:保留成功加载的工具,仅提示缺失(修复:F 组单点故障不再丢弃全部工具)
        logger.warning(f"[executor] MCP 部分工具不可用, 使用可用 {len(tools)} 个: {err}")
        _tools_cache = (tools, None)
    else:
        _tools_cache = (tools, None)
    _tools_cache_at = now
    return _tools_cache


# ── B2 检索净化辅助(确定性) ─────────────────────────────────
# search_log 的 query 由 LLM 生成时常用裸泛词(error/exception/timeout/失败/异常),
# 这类词在应用层/依赖/网络日志里都常见,检索结果的子集天然偏"含 app 字样"的行,
# 是盲测端到端 202/303/606 判偏(应用层/外部依赖被无差别抬升)的输入侧根因。
# 这里在工具参数层过滤裸泛词:过滤后余词聚焦真实症状词(connection refused、oom、
# gc pause 等对假设有区分度的词);余词为空则退化为全量检索,让裁判看到整批日志。

# 需要剔除的裸泛词:与"具体层"词(connection refused / oom / gc pause / 令牌过期)区分开,
# 这些词在 505(应用层 SQL 超时)等多场景日志里同样出现,无层级区分度。
_GENERIC_RETRIEVAL_WORDS = re.compile(
    r"\b(error|errors|exception|exceptions|timeout|timed out|failed|fail|失败的?|错误|异常|故障)\b",
    flags=re.IGNORECASE,
)


def _query_key_in(tool_args: dict) -> bool:
    """search_log 是否存在 query 参数。"""
    return "query" in tool_args


# 本地日志降级源目录(与 cls_server 的 runtime/log_cache 一致):模拟真实系统"日志有本地磁盘副本",
# 供 cls 服务不可达时 executor 降级读取——消除"日志查询"的单点依赖(方案 C)。
_LOG_CACHE_DIR = os.path.join("runtime", "log_cache")


def _sanitize_error(e: Exception) -> str:
    """把异常转成安全文本——只保留异常类型名，不裸露原始错误串。

    防止 403/连接串/堆栈等技术细节直接出现在诊断报告的"关键证据"里。
    """
    return type(e).__name__


def _local_log_fallback(tool_args: dict) -> str | None:
    """cls 服务不可达时,从本地日志缓存读取同 topic 的日志作为降级观测。

    Returns:
        含日志的观测文本(与 search_log 返回格式对齐,便于 llm_stub 摘要);
        无缓存返回 None。
    """
    topic_id = tool_args.get("topic_id")
    if not topic_id:
        return None
    path = os.path.join(_LOG_CACHE_DIR, f"{topic_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logs = data.get("logs", [])
        if not logs:
            return None
        # 与 search_log 返回结构对齐(ContentBlock list),llm_stub 可直接摘要
        payload = {"topic_id": topic_id, "total": len(logs), "logs": logs,
                   "took_ms": 0, "source": "local_cache(日志服务不可达,本地副本降级)"}
        return json.dumps([{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                          ensure_ascii=False)
    except Exception as e:
        logger.warning("[executor] 本地日志降级读取失败: %s", e)
        return None


def _sanitize_search_log_query(query: str) -> str:
    """过滤 search_log.query 中的裸泛词,返回净化后的词串(空串表示无可聚焦词)。

    'error OR exception OR timeout' -> ''(退化为全量检索)
    'connection refused OR oom'     -> 'connection refused OR oom'
    '5xx error rate'                -> '5xx rate'? 不:保留 5xx(应用层特征)…
    过滤仅剔除无层级区分度的裸词,保留有特征性的词。
    """
    if not query:
        return ""
    cleaned = _GENERIC_RETRIEVAL_WORDS.sub("", query)
    # 去掉过滤后残留的孤立连词/空段与多余空白
    cleaned = re.sub(r"\b(OR|AND|or|and)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,|")
    return cleaned


async def _run_single_tool(tc: dict, tool_map: dict, real_ids: str = "") -> ToolMessage:
    """执行单个工具调用(带超时保护),返回 ToolMessage。

    real_ids: _extract_real_identifiers 生成的标识符文本块（可为空）。
              用于 search_log 降级/调用前的 topic_id 对齐，修复重规划验证步骤
              的 topic 漂移（stub/LLM 对"验证 X"步骤提取不到服务名时可能生成
              默认或错误 topic）。
    """
    tool_name = tc.get("name", "")
    tool_args = dict(tc.get("args", {}) or {})
    tool_id = tc.get("id", "")
    tool = tool_map.get(tool_name)

    # topic 漂移修复: search_log 优先使用历史步骤真实返回的 topic_id,
    # 覆盖自动生成的占位/默认值(如重规划"验证 网络/连通性问题"被回退到默认 topic)。
    # 首次查询(历史无 search_log 记录)时 real_ids 无 topic_id,保持原 args 不变。
    if tool_name == "search_log" and real_ids:
        rid = _pick_real_identifier(real_ids, "topic_id")
        if rid:
            prev = tool_args.get("topic_id", "")
            tool_args["topic_id"] = rid
            if prev != rid:
                logger.info("[executor] search_log topic 对齐: '%s' -> '%s'(历史真实)", prev, rid)

    # B2 确定性检索净化(2026-08-26)：search_log 的 query 由 LLM 生成,常带回
    # 'error OR exception OR timeout' 等裸泛词——盲测端到端 202/303/606 等场景
    # 判偏(应用层/外部依赖被无差别抬升)的根因正是这些检索词让 execuutor 返回
    # 带 app 特征的日志子集。这里在**工具参数层**确定性过滤裸泛词:
    #   1) 过滤后的剩余词 >0 → 保留,检索反而更聚焦真实症状(连接失败/资源指标);
    #   2) 过滤后为空 → 退化为全量检索(等价于把"整批日志"交给裁判,与静态
    #      debug_llm_judge_miss 验证成立的"全量判定"条件一致)。
    if tool_name == "search_log" and _query_key_in(tool_args):
        raw_q = str(tool_args.get("query", ""))
        cleaned = _sanitize_search_log_query(raw_q)
        if cleaned:
            tool_args["query"] = cleaned
            logger.info("[executor] search_log query 净化: '%s' -> '%s'", raw_q[:60], cleaned[:60])
        else:
            tool_args.pop("query", None)
            logger.info("[executor] search_log query 净化后为空,退化为全量检索 (原: '%s')", raw_q[:60])

    if not tool:
        # 方案 C: 日志工具(服务)不可达时,尝试从本地日志缓存读取同 topic 日志作为降级观测。
        # 模拟真实系统"日志有本地磁盘副本",消除日志查询的单点依赖。
        if tool_name == "search_log":
            local = _local_log_fallback(tool_args)
            if local:
                content = local
                logger.info("[executor] search_log 工具不可用, 已降级读取本地日志缓存(topic=%s)", tool_args.get("topic_id"))
            else:
                content = f"工具 '{tool_name}' 不存在,跳过"
                AIOPS_TOOL_CALLS_TOTAL.labels(tool_name=tool_name, result="not_found").inc()
        else:
            content = f"工具 '{tool_name}' 不存在,跳过"
            AIOPS_TOOL_CALLS_TOTAL.labels(tool_name=tool_name, result="not_found").inc()
    else:
        try:
            result = await asyncio.wait_for(
                tool.ainvoke(tool_args),
                timeout=_TOOL_INVOKE_TIMEOUT,
            )
            content = str(result) if not isinstance(result, str) else result
            AIOPS_TOOL_CALLS_TOTAL.labels(tool_name=tool_name, result="success").inc()
        except asyncio.TimeoutError:
            content = f"工具 '{tool_name}' 调用超时(>{_TOOL_INVOKE_TIMEOUT}s)，请检查该服务是否正常运行"
            AIOPS_TOOL_CALLS_TOTAL.labels(tool_name=tool_name, result="timeout").inc()
            logger.warning("[executor] 工具 '%s' 调用超时", tool_name)
        except ConnectionError as e:
            content = f"工具 '{tool_name}' 连接失败(服务可能未启动)"
            logger.warning("[executor] 工具 '%s' 连接失败: %s", tool_name, e)
        except Exception as e:
            content = f"工具 '{tool_name}' 调用失败: {_sanitize_error(e)}"
            AIOPS_TOOL_CALLS_TOTAL.labels(tool_name=tool_name, result="failed").inc()
            logger.warning("[executor] 工具 '%s' 调用异常: %s", tool_name, e)

    logger.info(f"[executor] 工具 '{tool_name}' 调用完成,结果长度 {len(content)}")
    return ToolMessage(content=content, tool_call_id=tool_id)


async def _run_tool_calls(tool_calls: list, tool_map: dict, real_ids: str = "") -> list:
    """手动执行多个工具调用,返回 ToolMessage 列表。

    独立的工具调用之间没有依赖,并发执行可以缩短多工具诊断链路耗时。
    返回顺序与输入顺序一致,保证 LLM 回填时 tool_call_id 能对应上。
    """
    return await asyncio.gather(*(_run_single_tool(tc, tool_map, real_ids) for tc in tool_calls))


def _pick_real_identifier(real_ids: str, key: str) -> str | None:
    """从 _extract_real_identifiers 生成的文本块里按 key 取第一个真实值。"""
    if not real_ids:
        return None
    for line in real_ids.splitlines():
        line = line.strip()
        if line.startswith(f"{key} = "):
            v = line.split("=", 1)[1].strip().strip("'\"")
            if v:
                return v
    return None


async def _forced_search_log(tool_map: dict, real_ids: str, histories: list) -> str:
    """确定性兜底: 用真实 topic_id 的一段时间窗强制调一次 search_log。

    仅用于 LLM 没产出 search_log 结果、但步骤确实需要日志证据的场景。
    topic-003 演示主题不依赖时间窗,故这里的时间起点不必精确。
    """
    tool = tool_map.get("search_log")
    if not tool:
        return ""
    topic_id = _pick_real_identifier(real_ids, "topic_id")
    if not topic_id:
        return ""
    now_ms = int(time.time() * 1000)
    try:
        res = await asyncio.wait_for(
            tool.ainvoke({"topic_id": topic_id,
                          "start_time": now_ms - 10 * 60 * 1000,
                          "end_time": now_ms,
                          "query": "error OR timeout OR connection refused",
                          "limit": 50}),
            timeout=_TOOL_INVOKE_TIMEOUT,
        )
        return str(res)
    except Exception as e:
        logger.warning("[executor] 兜底调用 search_log 失败: %s", e)
        return ""


def _is_parallel_step(task: str) -> bool:
    """L4 并行观测标记：步骤文本以 [并行] 前缀开头。"""
    return task.strip().startswith("[并行]")


def _plain_label(task: str) -> str:
    """剥离 [并行] 标记，得到展示/入库用的步骤标签。"""
    return task.strip()[len("[并行]"):].strip() if _is_parallel_step(task) else task


async def _run_step(task: str, state: PlanExecuteState) -> str:
    """执行单个诊断步骤（不弹 plan），返回步骤结果文本。

    [并行] 前缀仅用于并行批调度标记，执行时剥离，不影响步骤语义。
    与原 executor 单步逻辑完全一致（回归兼容），供串行与并行批共用。
    """
    raw_task = task
    if _is_parallel_step(raw_task):
        raw_task = raw_task.strip()[len("[并行]"):].strip()

    try:
        tools, err = await _get_tools_cached()

        tool_map = _build_tool_map(tools)
        llm = create_agent_llm(temperature=0)
        llm_with_tools = llm.bind_tools(tools) if tools else llm

        # 无工具时注入数据诚实性警告
        sys_content = _EXECUTOR_SYSTEM
        if not tools:
            sys_content += _NO_TOOLS_WARNING

        # 少 tokens 压缩(2026-09-23): 历史只带最近 5 步、每条结果截 150 字符,
        # 避免随步数增长的二次方输入(LLM 只需近因标识符, 不读垃圾长文)。
        _HIST_LINES = 5
        _HIST_CHARS = 150
        history_lines = [
            f"[步骤] {s}\n[结果] {str(r)[:_HIST_CHARS]}"
            for s, r in state.get("past_steps", [])[-_HIST_LINES:]
        ]
        history = "\n\n".join(history_lines)

        real_ids = _extract_real_identifiers(state.get("past_steps", []))
        task_msg = f"请执行以下诊断步骤: {raw_task}"
        if history:
            # 把先前步骤的真实结果(尤其其工具返回的 topic_id/kb_id 等标识符)注入,
            # 使后续步骤能复用真实值而不再照抄计划里的占位示例。
            task_msg = (
                "已完成的步骤及结果(供复用其中真实标识符):\n"
                f"{history}\n\n{task_msg}"
            )
        if real_ids:
            # 确定性注入真实标识符,保证 search_log 等工具一定使用真实 topic_id,
            # 不再依赖 LLM 从长文本里自行拼凑。
            task_msg = f"{real_ids}\n\n{task_msg}"

        messages = [
            SystemMessage(content=sys_content),
            HumanMessage(content=task_msg),
        ]

        if tools:
            # 标准 ReAct 循环: 反复让 LLM 决定「继续调工具 or 出结论」。
            # 兼容"先取时间戳、拿到结果后再查日志"这类多步工具链,弥补单次回填遗漏。
            # 少 tokens(2026-09-23): 5→3 轮, 多数步骤一次调用即出结论, 减少重复往返输入。
            max_iter = 3
            result = ""
            executed: dict[str, bool] = {}
            for _ in range(max_iter):
                resp = await llm_with_tools.ainvoke(messages)
                messages.append(resp)
                tcs = getattr(resp, "tool_calls", None)
                if not tcs:
                    result = resp.content if hasattr(resp, "content") else str(resp)
                    break
                for tc in tcs:
                    executed[tc.get("name", "")] = True
                tool_msgs = await _run_tool_calls(tcs, tool_map, real_ids)
                messages.extend(tool_msgs)
            if not result:
                result = messages[-1].content if hasattr(messages[-1], "content") else ""

            # 确定性兜底: 步骤明确点名 search_log 且已拿到真实 topic_id,
            # 但 LLM 始终没产出日志结果时,强制用真实 topic_id 调一次,保证证据链不因
            # LLM 工具选择不稳而断裂。
            if (not result) and ("search_log" in raw_task) and (not executed.get("search_log")):
                fallback = await _forced_search_log(tool_map, real_ids, histories=state.get("past_steps", []))
                if fallback:
                    result = fallback
                    logger.info("[executor] 确定性兜底调用 search_log 成功,结果长度 %s", len(fallback))
        else:
            llm_no_tools = await llm_with_tools.ainvoke(messages)
            result = llm_no_tools.content if hasattr(llm_no_tools, "content") else str(llm_no_tools)

        result = result if isinstance(result, str) else str(result)
        logger.info(f"[executor] 步骤完成,结果长度 {len(result)}")
        return result

    except Exception as e:
        logger.warning("[executor] 执行步骤 '%s' 异常降级: %s", raw_task, e)
        return f"执行步骤 '{raw_task}' 时遇到异常: {_sanitize_error(e)}"


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """执行节点:执行 plan[0],结果写入 past_steps。

    L4 并行观测（settings.ENABLE_PARALLEL_OBSERVATION）：
      当 plan 前两步均为 [并行] 标记步骤时，并发执行后按序合并进 past_steps
      （状态合并保持单线程确定性；信念更新由 log-odds 批次原子保证序无关）。
    """
    logger.info("=== [role=executor] Executor:执行步骤 ===")
    plan = state.get("plan", [])
    if not plan:
        logger.info("[executor] 计划为空,跳过")
        return {}

    task = plan[0]
    logger.info(f"[executor] 当前步骤: {task}")

    try:
        # ── L4 并行批：两个独立观测步骤并发执行 ──
        if (settings.ENABLE_PARALLEL_OBSERVATION and len(plan) >= 2
                and _is_parallel_step(plan[0]) and _is_parallel_step(plan[1])):
            start_t = time.monotonic()
            r1, r2 = await asyncio.gather(
                _run_step(plan[0], state), _run_step(plan[1], state)
            )
            elapsed = time.monotonic() - start_t
            logger.info("[executor] 并行批执行 2 步完成, 耗时 %.2fs", elapsed)
            AIOPS_PARALLEL_BATCHES.labels(result="success").inc()
            done = len(state.get("past_steps", [])) + 2
            return {
                "plan": plan[2:],
                "past_steps": [(_plain_label(plan[0]), r1), (_plain_label(plan[1]), r2)],
                "_step_progress": {"done": done, "total": done + len(plan[2:])},
            }

        result = await _run_step(task, state)
        done = len(state.get("past_steps", [])) + 1
        return {
            "plan": plan[1:],
            "past_steps": [(_plain_label(task), result)],
            "_step_progress": {"done": done, "total": done + len(plan[1:])},
        }

    except Exception as e:
        logger.warning("[executor] 执行步骤 '%s' 异常降级: %s", task, e)
        done = len(state.get("past_steps", [])) + 1
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行步骤 '{task}' 时遇到异常: {_sanitize_error(e)}")],
            "_step_progress": {"done": done, "total": done + len(plan[1:])},
        }
