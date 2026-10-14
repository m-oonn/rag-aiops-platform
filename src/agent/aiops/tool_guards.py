"""工具调用守卫层（ToolGuard）——LLM 提议 → 确定性净化 → MCP 执行。

设计来源：借鉴 2026 头部 Agent Harness（pi, earendil-works）的"副作用边界"：
模型只"提议"工具调用，真正执行前由**本地守卫链**做确定性改写/净化，
保证"LLM 生成的参数瑕疵"（占位 topic_id、裸泛词、漂移时间窗）不会污染证据链。

本模块集中承载原先内联在 executor._run_single_tool 中的四类参数纠偏：
  1. TopicAlignmentGuard    —— search_log 的 topic_id 用历史真实值覆盖占位/默认值
  2. GenericWordFilterGuard —— search_log.query 过滤裸泛词（空则退化为全量检索）
  3. MetricTimeAnchorGuard  —— 指标查询时间窗确定为"贴近现在"
  4. ChangeTimeAnchorGuard  —— 变更查询时间窗确定为"贴近现在"（毫秒戳）

行为政策（与搬迁前一致）：
  - 纠偏函数体原样搬运（签名不变），仅日志前缀随模块归属改为 [tool_guards]；
  - 守卫返回 None 表示"本守卫不适用/无改写"，返回 dict 表示"已改写"；
  - 单个守卫可用 settings.DISABLED_TOOL_GUARDS 按名称停用（论文消融实验用）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from src.settings import settings
from src.utils.logger import logger

# ═══════════════════════════════════════════════════════════════
# 常量与确定性纠偏函数（原样搬迁自 executor.py）
# ═══════════════════════════════════════════════════════════════

# 需要剔除的裸泛词:与"具体层"词(connection refused / oom / gc pause / 令牌过期)区分开,
# 这些词在 505(应用层 SQL 超时)等多场景日志里同样出现,无层级区分度。
_GENERIC_RETRIEVAL_WORDS = re.compile(
    r"\b(error|errors|exception|exceptions|timeout|timed out|failed|fail|失败的?|错误|异常|故障)\b",
    flags=re.IGNORECASE,
)

# 字段限定子句(ES query_string 的 field:value,如 level:ERROR、log.level:WARN)。
# 这类子句的"值"是查询语法的一部分,不能被泛词过滤削掉 —— 否则 level:ERROR 会被
# 削成非法语法 level:,ES 直接 400(实测:level: → search_phase_execution_exception)。
_FIELD_SCOPED_CLAUSE = re.compile(r"^[A-Za-z_][\w.]*:")

# 指标工具:时间窗必须贴近"现在"。LLM 会自行推算绝对时间(实测给过比当前早 2h40m 的
# 窗口 09:48~10:48),而 Prometheus 只保留近期数据 → "最近一段时间"反而全空。
_METRIC_TIME_TOOLS = ("query_cpu_metrics", "query_memory_metrics")
_METRIC_TIME_FMT = "%Y-%m-%d %H:%M:%S"

# 变更工具:时间窗同样必须贴近"现在"。与指标同因(LLM 自行推算绝对时间会偏离当前),
# 但参数是毫秒时间戳(int),且"故障时间 ↔ 变更时间"对齐是变更证据成立的前提 ——
# 窗口错位会查成"窗口内无变更",进而误判 h_change 矛盾,把结论从变更根因上带反。
_CHANGE_TIME_TOOLS = ("search_changes",)
_CHANGE_DEFAULT_DUR_MS = 3600 * 1000  # 1 小时,与 search_changes 自身默认口径一致


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


def _sanitize_search_log_query(query: str) -> str:
    """过滤 search_log.query 中的裸泛词,返回净化后的词串(空串表示无可聚焦词)。

    'error OR exception OR timeout' -> ''(退化为全量检索)
    'connection refused OR oom'     -> 'connection refused OR oom'
    'level:ERROR'                   -> 'level:ERROR'(字段限定子句整体保留,不削值)
    'level:ERROR OR level:WARN'     -> 'level:ERROR OR level:WARN'
    """
    if not query:
        return ""
    # 归一化 "field: value" → "field:value",避免字段限定被空格拆散成 level: + ERROR
    normalized = re.sub(r"\b([A-Za-z_][\w.]*):\s+", r"\1:", query)
    kept: list[str] = []
    for tok in normalized.split():
        if _FIELD_SCOPED_CLAUSE.match(tok):
            if tok.endswith(":"):
                continue  # 字段后为空是非法语法(如 level:),丢弃整段
            kept.append(tok)
            continue
        if _GENERIC_RETRIEVAL_WORDS.search(tok):
            continue
        kept.append(tok)
    # 清理因剔除而变孤立的连词(前导/连续/结尾),保留两个有效词之间的 OR/AND
    final: list[str] = []
    for tok in kept:
        if tok.upper() in ("OR", "AND"):
            if not final or final[-1].upper() in ("OR", "AND"):
                continue
            final.append(tok)
        else:
            final.append(tok)
    while final and final[-1].upper() in ("OR", "AND"):
        final.pop()
    return " ".join(final).strip(" ,|")


def _reanchor_metric_time_window(tool_name: str, tool_args: dict) -> None:
    """把指标查询的时间窗确定性地锚定到"现在",只保留 LLM 想查的时长。

    与 search_log 的 topic_id/query 纠偏同属"工具参数层确定性纠偏":
      - 窗口右端已贴近当前(15 分钟内)则原样保留;
      - 否则右端对齐 now,左端按原窗口时长前推(缺失/非法/超长时用 1 小时),
        与工具自身默认口径(-1h~now)一致。修正会打日志,不静默篡改。
    """
    now = datetime.now()
    dur = timedelta(hours=1)
    raw_s = str(tool_args.get("start_time") or "")
    raw_e = str(tool_args.get("end_time") or "")
    try:
        s = datetime.strptime(raw_s, _METRIC_TIME_FMT)
        e = datetime.strptime(raw_e, _METRIC_TIME_FMT)
        if e > s and timedelta(minutes=1) <= (e - s) <= timedelta(hours=24):
            dur = e - s
    except (ValueError, TypeError):
        pass
    if raw_e:
        try:
            if datetime.strptime(raw_e, _METRIC_TIME_FMT) >= now - timedelta(minutes=15):
                return  # 窗口本身就贴近当前,不动
        except ValueError:
            pass
    new_s = (now - dur).strftime(_METRIC_TIME_FMT)
    new_e = now.strftime(_METRIC_TIME_FMT)
    tool_args["start_time"] = new_s
    tool_args["end_time"] = new_e
    logger.info("[tool_guards] %s 时间窗锚定到当前: '%s~%s' -> '%s~%s'",
                tool_name, raw_s or "-", raw_e or "-", new_s, new_e)


def _reanchor_change_time_window(tool_name: str, tool_args: dict) -> None:
    """把变更查询的时间窗确定性地锚定到"现在"(毫秒时间戳),只保留 LLM 想查的时长。

    与 _reanchor_metric_time_window 同属"工具参数层确定性纠偏":
      - 窗口右端已贴近当前(15 分钟内)则原样保留;
      - 否则右端对齐 now,左端按原窗口时长前推(缺失/非法/超长时用 1 小时)。
    修正会打日志,不静默篡改。
    """
    now_ms = int(datetime.now().timestamp() * 1000)
    dur_ms = _CHANGE_DEFAULT_DUR_MS

    def _to_ms(v: Any) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    raw_s = _to_ms(tool_args.get("start_time"))
    raw_e = _to_ms(tool_args.get("end_time"))
    if raw_s > 0 and raw_e > raw_s and (raw_e - raw_s) <= 24 * 3600 * 1000:
        dur_ms = raw_e - raw_s
    if raw_e > 0 and raw_e >= now_ms - 15 * 60 * 1000:
        return  # 窗口本身就贴近当前,不动
    new_s = now_ms - dur_ms
    new_e = now_ms
    tool_args["start_time"] = new_s
    tool_args["end_time"] = new_e
    logger.info("[tool_guards] %s 时间窗锚定到当前: '%s~%s' -> '%s~%s'",
                tool_name, raw_s or "-", raw_e or "-", new_s, new_e)


# ═══════════════════════════════════════════════════════════════
# 守卫数据契约
# ═══════════════════════════════════════════════════════════════


@dataclass
class GuardContext:
    """守卫链的上下文（对守卫只读）。

    real_ids: _extract_real_identifiers 产出的"可用真实标识符"文本块（可为空）。
    """

    real_ids: str = ""


@dataclass(frozen=True)
class GuardResult:
    """一次工具调用的守卫结果。

    original:  守卫前的原始参数（浅拷贝）
    rewritten: 守卫链跑完后的最终参数（无改写时与 original 等值）
    guards_applied: 实际发生改写的守卫名（顺序=执行顺序），供审计/消融统计
    action:    "pass"（无改写）/ "rewrite"（有改写）；"block" 预留（当前无拦截用例）
    """

    tool_name: str
    original: dict
    rewritten: dict
    guards_applied: tuple = ()
    action: str = "pass"


# ═══════════════════════════════════════════════════════════════
# 守卫实现
# ═══════════════════════════════════════════════════════════════


class TopicAlignmentGuard:
    """search_log 的 topic_id 对齐：用历史真实返回覆盖 LLM 生成的占位/默认值。

    背景: 重规划"验证 X"步骤时,LLM 对服务名提取不稳,可能生成默认/错误 topic,
    导致日志查询打到错误的主题上（topic 漂移）。历史步骤的真实 topic_id 优先。
    """

    name = "topic_alignment"

    def apply(self, tool_name: str, args: dict, ctx: GuardContext) -> Optional[dict]:
        if tool_name != "search_log" or not ctx.real_ids:
            return None
        rid = _pick_real_identifier(ctx.real_ids, "topic_id")
        if not rid:
            return None
        prev = args.get("topic_id", "")
        if prev == rid:
            return None
        new_args = dict(args)
        new_args["topic_id"] = rid
        logger.info("[tool_guards] search_log topic 对齐: '%s' -> '%s'(历史真实)", prev, rid)
        return new_args


class GenericWordFilterGuard:
    """search_log.query 的裸泛词净化（确定性）。

    背景: LLM 生成的检索词常用裸泛词(error/exception/timeout/失败/异常),
    这类词在应用层/依赖/网络日志里都常见,检索结果的子集天然偏"含 app 字样"的行,
    是盲测端到端 202/303/606 判偏(应用层/外部依赖被无差别抬升)的输入侧根因。
    过滤后余词聚焦真实症状词(connection refused、oom、gc pause 等对假设有区分度的词);
    余词为空则删掉 query 退化为全量检索,让裁判看到整批日志。
    """

    name = "generic_filter"

    def apply(self, tool_name: str, args: dict, ctx: GuardContext) -> Optional[dict]:
        if tool_name != "search_log" or "query" not in args:
            return None
        raw_q = str(args.get("query", ""))
        cleaned = _sanitize_search_log_query(raw_q)
        new_args = dict(args)
        if cleaned:
            if cleaned == raw_q:
                return None  # 本身就干净,不产生改写
            new_args["query"] = cleaned
            logger.info("[tool_guards] search_log query 净化: '%s' -> '%s'", raw_q[:60], cleaned[:60])
        else:
            new_args.pop("query", None)
            logger.info("[tool_guards] search_log query 净化后为空,退化为全量检索 (原: '%s')", raw_q[:60])
        return new_args


class MetricTimeAnchorGuard:
    """指标查询时间窗锚定（贴近"现在"；函数体见 _reanchor_metric_time_window）。"""

    name = "metric_time_anchor"

    def apply(self, tool_name: str, args: dict, ctx: GuardContext) -> Optional[dict]:
        if tool_name not in _METRIC_TIME_TOOLS:
            return None
        before = dict(args)
        _reanchor_metric_time_window(tool_name, args)  # 原地改写（行为与搬迁前一致）
        if args == before:
            return None
        return args


class ChangeTimeAnchorGuard:
    """变更查询时间窗锚定（贴近"现在"，毫秒戳；见 _reanchor_change_time_window）。"""

    name = "change_time_anchor"

    def apply(self, tool_name: str, args: dict, ctx: GuardContext) -> Optional[dict]:
        if tool_name not in _CHANGE_TIME_TOOLS:
            return None
        before = dict(args)
        _reanchor_change_time_window(tool_name, args)  # 原地改写（行为与搬迁前一致）
        if args == before:
            return None
        return args


# 守卫链（顺序=执行顺序；与搬迁前内联顺序一致）
GUARDS: tuple = (
    TopicAlignmentGuard(),
    GenericWordFilterGuard(),
    MetricTimeAnchorGuard(),
    ChangeTimeAnchorGuard(),
)


# ═══════════════════════════════════════════════════════════════
# 守卫链执行入口
# ═══════════════════════════════════════════════════════════════


def _disabled_guard_names() -> set:
    """读取 settings.DISABLED_TOOL_GUARDS（逗号分隔的守卫名停用列表）。"""
    raw = getattr(settings, "DISABLED_TOOL_GUARDS", "") or ""
    return {x.strip() for x in str(raw).split(",") if x.strip()}


def run_guards(tool_name: str, args: dict, ctx: Optional[GuardContext] = None) -> GuardResult:
    """对一次工具调用的参数跑完整守卫链，返回 GuardResult。

    - 每个守卫返回 None 表示"不适用/无改写"；返回 dict 表示"已改写"（链内继续传递）；
    - 有改写时追加一条汇总审计日志（工具名 + 命中守卫列表）；
    - 守卫执行异常不在此捕获（与搬迁前内联版行为一致，异常照常向上冒泡）。
    """
    ctx = ctx or GuardContext()
    original = dict(args)
    current = dict(args)
    applied: list = []
    disabled = _disabled_guard_names()
    for guard in GUARDS:
        if guard.name in disabled:
            continue
        out = guard.apply(tool_name, current, ctx)
        if out is not None:
            current = out
            applied.append(guard.name)
    if applied:
        logger.info("[tool_guards] %s 守卫命中: %s", tool_name, ", ".join(applied))
    return GuardResult(
        tool_name=tool_name,
        original=original,
        rewritten=current,
        guards_applied=tuple(applied),
        action="rewrite" if applied else "pass",
    )
