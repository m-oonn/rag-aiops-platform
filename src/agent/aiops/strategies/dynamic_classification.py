"""动态分类 Replan 策略：旁开式动态分类故障诊断机制实现。

核心组件：
  - HypothesisManager: 维护假设空间，执行 log-odds 信念更新与保护期
  - EvidenceJudge: 将 executor 观测映射为 Evidence（支持/矛盾/中性）
  - DynamicClassificationStrategy: 在 LangGraph replanner 节点中做决策

决策规则：
  1. 步数上限或计划为空 → respond（兜底报告）
  2. 最高假设概率 ≥ respond 阈值且与次选拉开差距 → respond
  3. 对领先假设出现强矛盾证据 → replan（旁开）
  4. 概率分布显著跃迁 → replan
  5. 默认 → continue

设计约束：
  - 不改动图结构（planner/executor/replanner 拓扑不变）
  - 可回退到 DefaultReplanStrategy（通过 AIOpsService 注入）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.agent.aiops.core.evidence_judge import EvidenceJudge
from src.agent.aiops.core.hypothesis import Evidence, Hypothesis, HypothesisManager
from src.agent.aiops.core.hypothesis_generator import HypothesisGenerator
from src.agent.aiops.core.hypothesis_reinterpreter import HypothesisReinterpreter
from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.base import BaseReplanStrategy
from src.agent.aiops.strategies.sidebar import SidebarBranch, SidebarEngine
from src.settings import settings
from src.utils.logger import logger


# ── 决策阈值 ──────────────────────────────────────────────
_RESPOND_THRESHOLD = 0.70
_RESPOND_CONFIDENCE_FLOOR = 0.50
_MIN_GAP_FOR_RESPOND = 0.20
# 修复(对抗测试 early_respond)：respond 前次选假设必须已被充分排除（绝对概率低于该值），
# 否则即使 top 概率高、gap 大，也可能是在"症状"层面（如资源指标）过早收敛，
# 忽略了真正的根因（如 app bug 导致的 CPU 高）。
_RUNNER_UP_EXCLUDED_THRESHOLD = 0.30
_REPLAN_TRIGGER_DELTA = 0.20
# 步数上限：配合 planner 的 6 步计划上限，为 replan 换向（验证/深入排查步骤）
# 预留空间；执行完计划后走"计划完毕 → respond"，上限只作绝对兜底。
_MAX_STEPS = 12
_NO_REPLAN_AFTER = 5
# 旁开合并后的计划上限（与 planner 计划上限一致）
_SIDEBAR_PLAN_CAP = 6
# 隐藏假设孵化触发条件：至少执行 2 步且 top 概率低于阈值
_INCUBATE_AFTER_STEPS = 2
_INCUBATE_TOP_THRESHOLD = 0.35


# ── 默认假设模板 ──────────────────────────────────────────
_DEFAULT_HYPOTHESES: List[Hypothesis] = [
    Hypothesis(
        id="h_infra",
        name="基础设施/资源瓶颈",
        description="CPU、内存、磁盘、fd、inode 或网络带宽成为瓶颈",
        expected_findings=[
            "cpu 高", "memory 高", "disk 高", "load 高", "资源不足",
            "fd", "文件描述符", "inode", "句柄", "oom", "耗尽", "使用率高",
            # 英文实证症状(与盲测主治对齐; 修复规则裁判"英文主治不命中→偏应用层"):
            "worker pool", "gc pause", "out of memory", "hard limit",
            "memory usage climbing", "load average", "file descriptor",
        ],
        contradictions=[
            "cpu 正常", "memory 正常", "资源充足", "fd 正常", "inode 充足",
            # 症状-根因降级：观测已明确指向应用层根因(死循环/死锁)时,
            # CPU/内存高只是**次生症状**, 不再作为独立根因证据(late_surge 对抗场景)。
            "死循环", "死锁",
            # 容器层明确信号(kubelet/驱逐/OOMKilled/Pod)出现时, 不是泛资源瓶颈
            "kubelet", "evicted", "oomkilled", "被驱逐", "驱逐", "容器", "pod",
            # 容器驱逐触发条件(node/disk/memory pressure)属容器层现象, 非泛资源瓶颈
            # (修复 909 盲测: LLM/规则裁判曾把 "node memory pressure" 当资源瓶颈支持)
            "memory pressure", "disk pressure", "node pressure",
            # 接口层症状(p99/fallback/错误率)→ 非资源瓶颈(单观测下压先验优势)
            "p99", "fallback", "错误率",
        ],
        probability=0.20,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_app",
        name="应用层异常",
        description="应用程序代码异常、服务崩溃、死锁、线程池耗尽或 GC 停顿",
        expected_findings=[
            "exception", "crash", "服务异常",
            "死锁", "deadlock", "线程", "停顿", "stw",
            "jstack", "端口冲突",
            # 收紧与基础设施主治的重叠词(修复 202/707 盲测): 裸 "gc"/"thread" 会同时命中
            # infra 主治 "GC pause lengthening, application threads blocked" 与
            # 级联干扰 "queue of HTTP requests growing due to slow processing thread",
            # 给应用层凭空累积支持。改为复合信号: 仅线程转储等明确应用层证据命中。
            "thread dump",
            # 收紧极泛词子串污染: bare "error" 会被基线日志 "no errors"/"Connection timed out"
            # 命中, 无差别把应用层抬到主治之上(规则裁判偏应用层根因之一)。改用具体应用层信号:
            "outofmemory", "out of memory", "oom", "5xx", "nullpointer",
            "stacktrace", "rejected execution",
            # 具体应用层特征词(中文侧)：堆栈/线程池耗尽/死循环/请求超时,
            # 修复 e2e 与对抗场景"app 证据不足"——这些词在依赖或网络故障日志中不出现。
            "堆栈", "线程池", "死循环", "请求超时",
        ],
        contradictions=["app 正常", "应用正常", "无错误", "线程正常", "无死锁",
                        # 接口场景旁证: 熔断/降级/接口恢复 → 接口层而非应用代码异常
                        "熔断", "降级", "fallback", "接口正常", "接口恢复", "错误率回落",
                        # 容器层明确信号 → 非应用代码异常(防 crash 单命中抢容器场景)
                        "kubelet", "evicted", "oomkilled", "被驱逐", "驱逐", "容器", "pod",
                        # GC/内存分配阻塞 → 资源瓶颈而非应用层线程问题(707 修复, 2026-09-16)
                        "gc pause", "blocked on allocation"],
        probability=0.20,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_net",
        name="网络/连通性问题",
        description="节点间或外部依赖连接超时、丢包、防火墙拦截、证书过期或 DNS 失败",
        # 仅在"链路/传输层"出现**明确连接失败**时才命中：刻意只用复合的连接失败词(connection
        # refused/reset、tcp connect、handshake、connection timed out、connect timeout、read timeout、
        # reset by peer)，而**不用**裸 timeout/connect/超时/连接——后者在应用层异常与外部依赖
        # 故障日志里同样常见(SQL 查询超时、依赖调用超时)，一带而过判网络会掩盖真正根因。
        # (505:应用层异常被误判为网络的历史教训; 参见 evidence_judge prompt 第12条定位层级)
        expected_findings=[
            "dial tcp", "connection refused", "connection reset", "tcp connect",
            "handshake", "握手失败", "握手未完成", "tcp握手",
            "网络不可达", "路由不可达", "无法解析域名", "域名解析失败", "dns 解析",
            "firewall", "防火墙", "mtu", "分片", "丢包", "重传", "拥塞",
            "ssl", "tls", "证书过期", "icmp",
            # 精确复合的连接失败信号(不带裸 timeout 以保护 505):
            "connection timed out", "connect timeout", "read timeout",
            "retry storm", "reset by peer",
            # 中文网络症状词(修复 e2e_net/firewall 场景):
            "网络超时", "连接超时", "连接失败", "连接中断",
        ],
        contradictions=["网络正常", "连接正常", "无超时",
                        # 接口层症状 → 非链路/传输层问题
                        "p99", "fallback", "错误率"],
        probability=0.20,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_config",
        name="配置错误",
        description="阈值、权限、路由、限流或时钟等配置不匹配",
        expected_findings=[
            "配置不匹配",
            "配置项错误",
            "阈值过低",
            "阈值设置",
            "timeout 日志",
            "配置问题",
            "回滚后恢复",
            "回退后恢复",
            "调整后恢复",
            "调整超时阈值",
            "恢复后正常",
            "回滚配置",
            "配置恢复",
            "略低",
            "限流",
            "时钟偏移",
            # 英文实证症状(与盲测主治对齐; 修复规则裁判"英文主治不命中→被泛词带走"):
            "config revision", "config mismatch", "rate limit",
            "timeout setting", "throttl",
        ],
        contradictions=["配置正确", "配置匹配", "阈值合理", "无明显异常",
                        # 接口层症状 → 非配置错误
                        "p99", "fallback", "错误率"],
        probability=0.20,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_dep",
        name="外部依赖故障",
        description="数据库、Redis、MQ、缓存集群、第三方 API、主从同步等外部依赖异常",
        expected_findings=[
            "database", "redis", "依赖超时", "依赖不可用", "上游不可用",
            "mq", "消息队列", "kafka", "replication", "主从", "consumer",
            "消费", "lag", "积压", "消息堆积", "缓存集群", "cache cluster",
            "不可达", "unreachable", "unavailable", "503",
            # 收紧裸泛词(404 误判根因):原含裸 "upstream"，配置主治日志
            # "timeout setting seems too aggressive for slow **upstream**" 同时命中它，
            # 给外部依赖凭空累积支持，压过真正的配置根因。改为复合信号，
            # 仅在"上游本身不可用/故障"的语义下命中(303 的 "upstream third-party ... 503"
            # 仍由 api/503/upstream third-party 命中，回归不受影响)。
            "upstream unavail", "upstream 不可用", "upstream api", "upstream third-party",
            "上游",
            "不一致", "降级", "熔断", "慢查询", "锁等待", "连接池",
            # 同步类仅"同步失败/延迟"语义命中,防 data-sync 等含"同步"业务词的
            # 正常日志被裸词误抬(infra_cpu 剧本 CPU 飙升被误判外部依赖的根因):
            "主从同步", "同步失败", "同步延迟", "同步中断", "sync fail", "sync lag",
        ],
        contradictions=[
            "依赖正常", "外部服务正常", "database 正常", "redis 正常",
            # 否定/正常语境脱敏：裸词 database/redis/api/锁等待/降级 会被
            # "查询正常/响应正常/无锁等待/无降级" 等**正常信号**命中误判支持
            # (thread_pool/gc_pause 场景依赖被无脑抬升的历史根因)。补矛盾侧:
            "查询正常", "响应正常", "无慢查询", "无锁等待", "无降级", "无异常",
            # 接口场景旁证: 接口已恢复/错误率回落 → 不是依赖持续故障
            "接口正常", "接口恢复", "错误率回落",
            # 接口层症状词 → 非外部依赖故障(服务自身接口熔断/降级 ≠ 依赖故障):
            "p99", "fallback", "接口 错误率", "接口 耗时", "接口 平均", "错误率",
        ],
        probability=0.20,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_container",
        name="容器问题",
        description="容器 OOMKilled、Pod 被驱逐、CrashLoopBackOff、节点资源压力等容器编排层异常",
        # 与 h_infra 竞合: 容器日志的 OOMKilled 也含 "oom"(h_infra 单命中),
        # 但 kubelet/evicted/pod 被驱逐/重启循环等多命中给 h_container 更高强度,
        # softmax 竞争收敛到容器问题而非泛资源瓶颈。
        expected_findings=[
            "oomkilled", "evicted", "kubelet", "container", "pod",
            "crashloopbackoff", "memorypressure", "node pressure", "节点压力",
            "容器 重启", "被驱逐", "驱逐", "重启 循环", "重新调度",
            "last exit code", "restart count", "退出码 137",
            "节点 内存不足", "limit 超限", "超过 limit",
        ],
        contradictions=["容器正常", "pod 正常", "无重启", "运行稳定", "无驱逐"],
        # 先验 0.10(2026-09-15 修复): 0.05 过低导致即使容器证据最强(support 1.0)也
        # 在 softmax 竞争后不敌先验 0.20 的基础设施/其他假设(909 盲测误判根因)。
        # 仍显著低于 0.20 主类别, 无容器证据时不会参与竞争稀释。
        probability=0.10,
        protection_rounds=2,
    ),
    Hypothesis(
        id="h_api",
        name="服务接口异常",
        description="接口错误率/耗时上升、P99 超 SLO、熔断降级、fallback 启用等服务接口层异常",
        # 与 h_app(5xx/请求超时/线程池) 与 h_dep(熔断/降级) 竞合:
        # 用复合接口词(接口错误率/耗时/p99/fallback)多命中压过单命中。
        expected_findings=[
            "接口 错误率", "接口 耗时", "接口 平均", "接口 超时", "接口 变慢",
            "接口 不可用", "接口 失败",
            "错误率 飙升", "错误率 上升", "错误率 12", "p99", "endpoint",
            "circuit", "熔断", "fallback", "服务 降级", "服务降级",
            "5xx 返回", "5xx 错误", "大量 5xx",
        ],
        contradictions=["接口正常", "接口 稳定", "无熔断",
                        # "fallback to default profile" 是配置回退语义, 非接口降级:
                        # 与 support 裸词 "fallback" 净抵消(修复 config 场景回归, 2026-09-15)
                        "fallback to"],
        # 先验 0.10(2026-09-15 修复): 与 h_container 对称。0.05 过低导致 1010 盲测中
        # api 主治(support 1.0)在 softmax 竞争后不敌先验 0.10 的容器干扰(pod 级联行)。
        probability=0.10,
        protection_rounds=2,
    ),
]


_XML_TAG_RE = __import__("re").compile(r"<[^<>]{0,40}>")  # 剥离工具返回的 XML/HTML 标签
_CTRL_RE = __import__("re").compile(r"[\x00-\x1f\x7f]+")


def _clean_step_result(text: str, max_len: int = 240) -> str:
    """清理单步诊断结果：剥离 XML 标签、控制符，压缩空白，按句号边界截断。

    工具(MCP)返回的原始内容常是 <result><description>… 这类 XML，直接展示既
    不美观也难读；这里在报告渲染层做可读化清洗，不影响 executor 存的原始证据。
    """
    if not text:
        return ""
    cleaned = _CTRL_RE.sub(" ", str(text))
    cleaned = _XML_TAG_RE.sub("", cleaned)
    cleaned = cleaned.replace("\\n", "\n").replace("\\t", " ")
    # 折叠多行/空白
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    collapsed = " ".join(lines)
    collapsed = __import__("re").sub(r"\s{2,}", " ", collapsed)
    if len(collapsed) <= max_len:
        return collapsed
    # 在最近一个句号边界截断，避免从半句话中间切开
    head = collapsed[: max_len + 1]
    boundary = max(head.rfind("。"), head.rfind("！"), head.rfind("？"),
                   head.rfind("."), head.rfind("；"))
    if boundary >= max_len // 2:
        return collapsed[: boundary + 1] + "…"
    return collapsed[:max_len] + "…"


def _evidence_sufficiency_problem(past_steps: list) -> str | None:
    """检测关键证据源的状态: 整体缺失 或 降级来源(工具故障但已本地兜底)。

    返回的说明分两类(供 _local_respond 标注):
      - "缺失": 日志步骤被跳过(工具不存在/服务不可达)且无本地兜底 → 观测无鉴别力;
      - "降级": 日志步骤实际由本地缓存副本提供(日志服务不可达,已降级) → 证据真实但来源降级,
        报告应透明标注"日志证据来自本地副本", 供可审计而非否定结论。
    判定依据: 观测文本中的标记词。
    """
    degraded = False
    for step, result in past_steps:
        low_step = str(step).lower()
        if "log" in low_step or "日志" in str(step) or "search_log" in low_step:
            text = str(result)
            # 方案 C: search_log 不可用时 executor 从本地日志缓存降级读取,文本含本来源标记
            if "本地副本降级" in text or "local_cache" in text or "日志服务不可达" in text:
                degraded = True
                continue
            if any(kw in text for kw in ("不存在", "跳过", "缺失", "服务可能未启动", "连接失败", "无法获取")):
                return f"日志证据缺失(检索工具不可用), {len(past_steps)} 步观测中日志步骤无法取证"
    if degraded:
        return f"日志证据来自本地降级副本(日志服务不可达), {len(past_steps)} 步观测中日志步骤已本地兜底"
    return None


def _local_respond(
    state: PlanExecuteState, hypothesis_space: List[dict] | None = None,
    sufficiency_note: str | None = None,
) -> Dict[str, Any]:
    """兜底响应生成：不调 LLM，基于假设空间与已执行步骤拼接结构化 Markdown 报告。

    报告结构：结论(根因+置信度) → 关键证据(清洗后的步骤摘要) → 候选根因。
    相比旧版直接倾倒原始步骤串，可读性更好，也更贴近"诊断报告"而非"执行日志"。

    证据充分性门控(sufficiency_note 非空):
      当关键证据源(日志)整体缺失、观测无鉴别力时, 即使 top 假设概率 >=0.50
      也**不输出确定性结论行**, 改为显式标注"证据不足, 结论为推测"——
      避免把"信息不足以决策"伪装成"已锁定根因"(cls 停服场景的诚实性修复)。
    """
    input_text = state.get("input", "")
    past_steps = state.get("past_steps", [])

    # 证据状态判定: 降级(本地副本兜底,证据真实) vs 缺失(观测空洞,真不足)
    is_degraded = bool(sufficiency_note) and ("降级" in sufficiency_note or "本地副本" in sufficiency_note)
    has_sufficiency_issue = bool(sufficiency_note) and not is_degraded

    # 结论判定优先复用:提前计算 top 假设,供报告正文与结构化元数据共用
    ranked = sorted(hypothesis_space, key=lambda h: h["probability"], reverse=True) if hypothesis_space else []
    top = ranked[0] if ranked else None

    # 结构化元数据(供程序消费,不渲染): 证据充分性状态 + 结论类型 + 判定结果。
    # 以 Markdown HTML 注释块嵌入报告头部,人类阅读不受影响,程序可用正则/JSON 提取。
    if top is None:
        conclusion_state = "no_hypothesis"
    elif has_sufficiency_issue:
        conclusion_state = ("insufficient" if top["probability"] < _RESPOND_CONFIDENCE_FLOOR
                            else "conclusive_uncertain")
    elif is_degraded:
        conclusion_state = ("degraded_conclusive" if top["probability"] >= _RESPOND_CONFIDENCE_FLOOR
                            else "uncertain")
    else:
        conclusion_state = "conclusive" if top["probability"] >= _RESPOND_CONFIDENCE_FLOOR else "uncertain"
    diag_meta = {
        "evidence_sufficiency": "degraded" if is_degraded else ("missing" if has_sufficiency_issue else "ok"),
        "note": sufficiency_note or "",
        "conclusion_state": conclusion_state,
        "top_hypothesis": top["name"] if top else None,
        "top_probability": round(top["probability"], 4) if top else None,
    }
    report = (
        f"# 诊断结果\n\n"
        f"<!-- diagnostic_meta: {json.dumps(diag_meta, ensure_ascii=False)} -->\n\n"
        f"## 原始任务\n{input_text}\n\n"
    )

    # 结论：优先给出根因判定与置信度，避免只给步骤清单不给结论
    if hypothesis_space:
        if top and top["probability"] >= _RESPOND_CONFIDENCE_FLOOR and not has_sufficiency_issue:
            # 正常或"降级但证据充分":都输出结论;降级时附加可审计标注
            if is_degraded:
                report += (
                    f"## 结论\n"
                    f"最可能的根因是 **{top['name']}**，置信度 **{top['probability']:.0%}**。\n\n"
                    f"> ⚠️ {sufficiency_note}。日志证据为本地副本,非实时采集,"
                    f"结论基于该降级来源仍成立,建议日志服务恢复后复核。\n\n"
                )
            else:
                report += (
                    f"## 结论\n"
                    f"最可能的根因是 **{top['name']}**，置信度 **{top['probability']:.0%}**。\n\n"
                )
        elif top and top["probability"] >= _RESPOND_CONFIDENCE_FLOOR and has_sufficiency_issue:
            # 证据缺失但概率已达阈值:不伪装确定,如实标注为推测
            report += (
                f"## 结论(推测)\n"
                f"**{top['name']}** 概率 **{top['probability']:.0%}**，"
                f"但 {sufficiency_note}，结论置信度有限，需补齐观测后复核。\n\n"
            )
        elif top and not has_sufficiency_issue and top["probability"] < _RESPOND_CONFIDENCE_FLOOR:
            # 降级但 top 未达阈值:标注来源 + 未锁定根因
            degraded_note = f"（{sufficiency_note}）" if is_degraded else ""
            report += (
                f"## 结论\n"
                f"未锁定根因：**{top['name']}** 置信度仅 **{top['probability']:.0%}**{degraded_note}，"
                f"证据不足以区分候选假设。\n\n"
            )
        elif top and has_sufficiency_issue:
            report += (
                f"## 结论(证据不足)\n"
                f"无法定位根因：{sufficiency_note}，假设空间无鉴别性观测，"
                f"置信度最佳为 **{top['probability']:.0%}**（并列候选，非确定结论）。\n\n"
            )

    # 关键证据：清洗后的步骤摘要
    if past_steps:
        steps_md = "\n".join(
            f"- **{s}**: {_clean_step_result(r)}" for s, r in past_steps
        )
        report += f"## 关键证据\n{steps_md}\n\n"

    # 候选根因及置信度
    if hypothesis_space:
        top3 = sorted(hypothesis_space, key=lambda h: h["probability"], reverse=True)[:3]
        if top3:
            lines = "\n".join(
                f"- **{h['name']}** ({h['probability']:.0%})" for h in top3
            )
            report += f"## 候选根因\n{lines}\n\n"
    report += "_系统已收集足够信息，诊断完成。_"
    return {"response": report}


def _maybe_create_judge_llm() -> Any | None:
    """按 settings 创建证据裁判用的 LLM；未开启或缺失 key 时返回 None（走规则）。"""
    if not settings.ENABLE_LLM_EVIDENCE_JUDGE:
        return None
    if not settings.DASHSCOPE_API_KEY:
        logger.warning("[dynamic_class] 未配置 DASHSCOPE_API_KEY，LLM 证据裁判禁用，回退规则")
        return None
    try:
        from src.agent.aiops_llm import create_agent_llm

        return create_agent_llm(model=settings.EVIDENCE_LLM_MODEL, temperature=0)
    except Exception:
        logger.exception("[dynamic_class] 创建证据裁判 LLM 失败，回退规则")
        return None


class DynamicClassificationStrategy(BaseReplanStrategy):
    """旁开式动态分类 Replanner 策略。

    维护显式假设空间，每步根据证据更新信念，矛盾触发旁开式 replan。

    Args:
        judge: 可注入 EvidenceJudge（如带 mock LLM 的测试实例）；
               不传则按 settings.ENABLE_LLM_EVIDENCE_JUDGE 决定是否启用 LLM 语义裁判。
    """

    def __init__(self, judge: Optional[EvidenceJudge] = None) -> None:
        self.manager = HypothesisManager(
            support_strength=1.5,
            contradiction_strength=2.5,
            strong_contradiction_threshold=0.7,
        )
        self.judge = judge or EvidenceJudge(llm=_maybe_create_judge_llm())
        self._step_count = 0
        self._last_top_prob: float | None = None
        self.sidebar_engine = SidebarEngine()
        self._sidebar_branches: List[SidebarBranch] = []
        self.hypothesis_generator = HypothesisGenerator()
        self.reinterpreter = HypothesisReinterpreter()
        self._belief_history: List[dict] = []
        # 是否已观测到非中性证据(孵化门控依据,见 _incubate_allowed)
        self._evidence_seen = False

    def reset(self) -> None:
        """清空策略内部状态，供每次新诊断前复用同一实例。"""
        self.manager = HypothesisManager(
            support_strength=1.5,
            contradiction_strength=2.5,
            strong_contradiction_threshold=0.7,
        )
        self._step_count = 0
        self._last_top_prob = None
        self._sidebar_branches = []
        self._belief_history = []
        self._evidence_seen = False

    async def decide(self, state: PlanExecuteState) -> Dict[str, Any]:
        logger.info("=== [role=replanner] DynamicClassificationStrategy:评估 ===")

        input_text = state.get("input", "")
        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])
        self._step_count = len(past_steps)

        # 1. 初始化假设空间（首步或需要快照时）
        if not self.manager.get_active_hypotheses():
            self._init_hypotheses(input_text, state)
            logger.info("[dynamic_class] 初始化 %d 条假设", len(self.manager.get_active_hypotheses()))

        # 2. 将最新步骤结果转换为证据并更新信念
        latest_contradiction = False
        if past_steps:
            latest_step, latest_result = past_steps[-1]
            # 修复(时序 bug)：必须在信念更新**前**记录当前领先假设。
            # 若在 update_beliefs 后再查 top，矛盾证据已把原 top 压下去，
            # 导致"领先假设被矛盾 → 旁开 replan"永远检测不到（test_contradiction_triggers_replan）。
            pre_top = self.manager.get_top_hypotheses(k=1)
            pre_top_id = pre_top[0].id if pre_top else None

            evidences = await self.judge.judge_async(
                self.manager.get_active_hypotheses(),
                latest_result,
                step=self._step_count,
                source=latest_step,
            )
            # 记录是否观测到真实证据(孵化门控依据)。505 误孵化根因:前几步观测全 neutral
            # (步骤文本/时间戳/错误回显), top 停在先验 0.20 < 0.35 就触发孵化,凭空扩展
            # 假设空间——必须等默认假设被真实证据检验过才允许"现有假设解释不了"的判断。
            if any(ev.relation != "neutral" for ev in evidences):
                self._evidence_seen = True
            self.manager.update_beliefs(evidences)
            self._incubate_weak_signals(evidences)
            latest_contradiction = self._hypothesis_contradicted(pre_top_id, evidences)

        # 3. 获取当前领先假设
        top_list = self.manager.get_top_hypotheses(k=2)
        top = top_list[0] if top_list else None
        runner_up = top_list[1] if len(top_list) > 1 else None
        current_top_prob = top.probability if top else 0.0

        logger.info(
            "[dynamic_class] top=%s(%.3f) runner=%s contradiction=%s plan_remain=%d",
            top.name if top else "N/A",
            current_top_prob,
            runner_up.name if runner_up else "N/A",
            latest_contradiction,
            len(plan),
        )

        # 快照必须在信念更新后计算，确保返回的假设空间反映最新证据
        snapshot = self._snapshot()
        # 记录本轮信念分布，供可视化假设信念变化曲线
        self._record_belief()

        # 证据充分性门控: 关键证据源(日志)整体缺失(工具故障/服务不可达)时记下说明,
        # 供 _local_respond 在报告中诚实标注"证据不足", 不把并列猜测伪装成锁定根因。
        sufficiency_note = _evidence_sufficiency_problem(past_steps)

        # 4. 决策
        # 4.0 步数上限 → respond
        if self._step_count >= _MAX_STEPS:
            logger.warning("[dynamic_class] 已达步数上限, 强制 respond")
            return {
                **_local_respond(state, snapshot, sufficiency_note),
                "hypothesis_space": snapshot,
                "belief_history": self._belief_history,
            }

        # 4.1 深度回溯重解释：已淘汰假设在后续观测中出现净支持证据时复活。
        # 置于"计划执行完毕/高置信 respond"之前——否则原计划耗尽的那一轮，
        # 回溯信号会被 4.x 的出报告分支吞掉，漏掉被错杀的真根因。
        reactivated = self._maybe_reactivate_hypotheses(past_steps)
        if reactivated:
            snapshot = self._snapshot()  # 复活后重新快照，包含被激活假设
            self._last_top_prob = current_top_prob  # 防跃迁检测失效
            logger.info(
                "[dynamic_class] 深度回溯重解释 → replan: %s",
                [h.name for h in reactivated],
            )
            return self._build_replan_with_reactivated(
                past_steps, plan, snapshot, latest_contradiction, reactivated
            )

        # 4.2 计划执行完毕 → respond
        if not plan and past_steps:
            logger.info("[dynamic_class] 计划执行完毕, 出报告")
            return {
                **_local_respond(state, snapshot, sufficiency_note),
                "hypothesis_space": snapshot,
                "belief_history": self._belief_history,
            }

        # 4.2 高置信度 → respond
        if top and current_top_prob >= _RESPOND_THRESHOLD and current_top_prob >= _RESPOND_CONFIDENCE_FLOOR:
            runner_gap = current_top_prob - (runner_up.probability if runner_up else 0.0)
            # 修复(对抗测试 early_respond)：仅 gap 大还不够——次选假设必须已被充分排除
            # （绝对概率低于阈值），否则继续收集证据，避免在"症状"层过早收敛。
            runner_up_excluded = (
                runner_up is None or runner_up.probability < _RUNNER_UP_EXCLUDED_THRESHOLD
            )
            # 修复(对抗测试 late_surge)：剩余计划还有 >=2 步时，即使次选暂时被排除
            # 也不提前 respond——后续步骤可能带来翻转证据（如 app 日志 NullPointerException）。
            # 再收紧(对抗测试 early_respond)：**至少 3 轮独立观测**且在计划收尾
            # (剩 <=1 步) 时才允许高置信提前 respond；仅 2 步资源证据不足以盖棺
            # (len(plan)==1 时 step_count<3 不得 respond)，避免在"症状"层过早收敛
            # 而漏掉真根因(app 死循环导致的 CPU 高)。step_count>=4 兜底另见下方。
            plan_almost_done = len(plan) <= 1 and self._step_count >= 3
            if (
                runner_gap >= _MIN_GAP_FOR_RESPOND
                and runner_up_excluded
                and plan_almost_done
            ) or self._step_count >= 4:
                logger.info(
                    "[dynamic_class] 高置信度(%.3f), gap=%.3f, runner_up_excluded=%s, plan_remain=%d → respond",
                    current_top_prob, runner_gap, runner_up_excluded, len(plan),
                )
                return {
                    **_local_respond(state, snapshot, sufficiency_note),
                    "hypothesis_space": snapshot,
                    "belief_history": self._belief_history,
                }

        # 4.3 对领先假设的强矛盾 → replan（旁开）
        if latest_contradiction and self._step_count < _NO_REPLAN_AFTER:
            logger.info("[dynamic_class] 矛盾触发 → replan")
            # 记录当前 top，供下一轮概率跃迁检测使用（否则矛盾 replan 后
            # _last_top_prob 保持 None，跃迁检测永久失效）
            self._last_top_prob = current_top_prob
            return self._build_replan_with_sidebar(past_steps, plan, snapshot, latest_contradiction)

        # 4.4 概率显著跃迁 → replan
        if self._significant_shift(current_top_prob):
            logger.info("[dynamic_class] 概率显著变化 → replan")
            return self._build_replan_with_sidebar(past_steps, plan, snapshot, latest_contradiction)

        # 4.5 隐藏假设孵化：top 持续偏低且已有证据积累 → 可能存在未覆盖的隐藏根因。
        # 门控:无任何非中性证据(所有观测全 neutral, top 停在先验)且输入也未携带隐藏线索时
        # 不孵化——此时只是"默认假设还没被检验",不是"默认假设解释不了观测"。
        if (
            self._step_count >= _INCUBATE_AFTER_STEPS
            and current_top_prob < _INCUBATE_TOP_THRESHOLD
            and self._incubate_allowed(input_text)
        ):
            spawned = self._maybe_spawn_hypotheses(input_text, past_steps)
            if spawned:
                snapshot = self._snapshot()  # 孵化后重新快照，包含新假设
                logger.info(
                    "[dynamic_class] 孵化隐藏假设 → replan: %s",
                    [h.name for h in spawned],
                )
                return self._build_replan_with_spawned(
                    past_steps, plan, snapshot, latest_contradiction, spawned
                )

        # 4.7 默认继续
        logger.info("[dynamic_class] 继续执行")
        self._last_top_prob = current_top_prob
        return {"hypothesis_space": snapshot, "belief_history": self._belief_history}

    def _snapshot(self) -> List[dict]:
        """返回当前假设空间的可序列化快照。"""
        return [h.model_dump() for h in self.manager.get_active_hypotheses()]

    def _record_belief(self) -> None:
        """记录当前轮各假设概率，供可视化信念变化曲线。"""
        self._belief_history.append(
            {
                "step": self._step_count,
                "probabilities": {
                    h.id: h.probability for h in self.manager.get_active_hypotheses()
                },
            }
        )

    def _init_hypotheses(self, input_text: str, state: PlanExecuteState) -> None:
        """从输入和初始计划生成默认假设列表，并根据输入关键词微调先验。"""
        hypotheses = [h.model_copy(deep=True) for h in _DEFAULT_HYPOTHESES]
        text = input_text.lower()
        for h in hypotheses:
            hits = sum(1 for p in h.expected_findings if p.lower() in text)
            if hits:
                # 输入中提及相关线索时，给该假设一个微弱的先验抬头
                boost = min(0.08 * hits, 0.16)
                h.probability = max(0.01, min(h.probability + boost, 0.50))
        self.manager.add_hypotheses(hypotheses)

    def _incubate_weak_signals(self, evidences: List[Evidence]) -> None:
        """弱信号孵化：对获得支持但概率仍偏低的假设给予小幅鼓励。

        避免简单假设因先验低、证据弱而被过早淘汰，体现"旁开式"策略中对
        弱信号的容忍与孵化。
        """
        for ev in evidences:
            if ev.relation != "support":
                continue
            h = self.manager.get_hypothesis(ev.target_hypothesis_id)
            if h is None or h.status != "active":
                continue
            if h.probability < 0.35:
                # 小幅抬升，避免一步登天；上限 0.35 防止过度自信
                h.probability = max(0.01, min(h.probability + 0.06, 0.35))

    def _hypothesis_contradicted(
        self, hypothesis_id: str | None, evidences: List[Evidence]
    ) -> bool:
        """判断最新证据是否对指定假设构成矛盾。"""
        if not hypothesis_id:
            return False
        return any(
            ev.target_hypothesis_id == hypothesis_id and ev.relation == "contradict"
            for ev in evidences
        )

    def _significant_shift(self, current_top_prob: float) -> bool:
        """与上一步最高概率比较，判断是否有显著跃迁。"""
        if self._last_top_prob is None:
            self._last_top_prob = current_top_prob
            return False
        shifted = abs(current_top_prob - self._last_top_prob) >= _REPLAN_TRIGGER_DELTA
        self._last_top_prob = current_top_prob
        return shifted

    def _build_replan(self, past_steps: list, current_plan: List[str]) -> List[str]:
        """基于当前假设排序生成验证计划。"""
        done = {s for s, _ in past_steps}
        candidates: List[str] = []
        for h in self.manager.get_top_hypotheses(k=3):
            if h.probability < 0.10 or h.status == "falsified":
                continue
            verify = f"验证 {h.name}"
            if verify not in done:
                candidates.append(verify)
            detail = f"深入排查 {h.name}"
            if detail not in done:
                candidates.append(detail)
        if not candidates:
            candidates = ["收集更多诊断信息", "交叉验证当前假设"]
        # 保留原 plan 中未执行的步骤作为补充，但不超过 4 步
        for step in current_plan:
            if step not in done and step not in candidates:
                candidates.append(step)
        return candidates[:4]

    def _build_replan_with_sidebar(
        self,
        past_steps: list,
        current_plan: List[str],
        snapshot: List[dict],
        latest_contradiction: bool,
    ) -> Dict[str, Any]:
        """构建 replan 计划，并按需开辟旁开验证支线（伪并行）。

        旁开验证步骤优先执行，执行后产生的观测与其他观测一样进入证据裁判与
        信念更新（全局证据池共享 = 合并）；分支状态在后续 decide 中更新。
        """
        done = {s for s, _ in past_steps}
        SidebarEngine.update_branch_status(self._sidebar_branches, done)

        base = self._build_replan(past_steps, current_plan)
        decision = self.sidebar_engine.decide(
            self.manager.get_active_hypotheses(),
            step_count=self._step_count,
            latest_contradiction=latest_contradiction,
            existing_branches=self._sidebar_branches,
        )

        plan = base
        if decision.should_sidebar:
            self._sidebar_branches.append(
                SidebarBranch(
                    id=f"sb-{self._step_count}-{decision.target_hypothesis_id}",
                    target_hypothesis_id=decision.target_hypothesis_id,
                    target_hypothesis_name=decision.target_hypothesis_name,
                    plan=decision.verification_steps,
                    status="running",
                    trigger_reason=decision.trigger_reason,
                    created_step=self._step_count,
                )
            )
            logger.info(
                "[dynamic_class] 旁开支线 → %s (原因: %s)",
                decision.target_hypothesis_name,
                decision.trigger_reason,
            )
            extra = [s for s in decision.verification_steps if s not in done]
            plan = (extra + base)[: _SIDEBAR_PLAN_CAP]

        return {
            "plan": plan,
            "hypothesis_space": snapshot,
            "sidebar_branches": [b.model_dump() for b in self._sidebar_branches],
            "belief_history": self._belief_history,
        }

    def _incubate_allowed(self, input_text: str) -> bool:
        """孵化门控：只有"默认假设确实被检验过仍解释不了"才允许孵化隐藏假设。

        判断条件(满足其一)：
          - 已观测到至少一条非中性证据：说明默认假设被真实证据检验过，
            top 仍低 → "现有假设解释不了观测"的孵化前提成立；
          - 输入文本本身携带隐藏故障线索：用户原始诉求直接点名
            (如"定时任务重叠导致卡顿")，此时无需等证据即可信任该线索。

        不加门控的后果(505 误孵化根因)：executor 步骤文本/计划回显常含泛词
        (如"构造最近 15 分钟的**时间窗口**"、"**调度**范围")，前几步观测全会被
        判成 neutral，top 停在先验 0.20(< 0.35)直接触发孵化，凭空扩展假设空间；
        孵化出的假设随后被"验证 <假设名>"步骤自证自答，盖过真实根因。
        """
        if self._evidence_seen:
            return True
        text = (input_text or "").lower()
        return any(
            kw in text
            for clue in self.hypothesis_generator.catalog
            for kw in clue.keywords
        )

    def _maybe_spawn_hypotheses(self, input_text: str, past_steps: list) -> List[Hypothesis]:
        """检测并孵化隐藏故障假设，返回新假设（已加入假设空间）。"""
        observations = [r for _, r in past_steps]
        spawned = self.hypothesis_generator.generate(
            self.manager.get_active_hypotheses(),
            observations,
            input_text=input_text,
            birth_step=self._step_count,
        )
        if spawned:
            self.manager.add_hypotheses(spawned)
        return spawned

    def _maybe_reactivate_hypotheses(self, past_steps: list) -> List[Hypothesis]:
        """深度回溯复查：对已淘汰假设在后续证据支持下重新激活。"""
        reactivated = []
        for h in self.reinterpreter.examine(
            self.manager.get_all_hypotheses(),
            past_steps,
            current_step=self._step_count,
        ):
            restored = self.manager.reactivate(
                h.id,
                new_probability=self.reinterpreter.revival_probability,
                protection_rounds=self.reinterpreter.revival_protection_rounds,
            )
            if restored is not None:
                reactivated.append(restored)
        return reactivated

    def _build_replan_with_reactivated(
        self,
        past_steps: list,
        current_plan: List[str],
        snapshot: List[dict],
        latest_contradiction: bool,
        reactivated: List[Hypothesis],
    ) -> Dict[str, Any]:
        """在旁开 replan 基础上，把复活假设的验证步骤置顶。"""
        result = self._build_replan_with_sidebar(
            past_steps, current_plan, snapshot, latest_contradiction
        )
        done = {s for s, _ in past_steps}
        names = [h.name for h in reactivated]
        result["plan"] = _prepend_verification(result["plan"], names, done)
        return result

    def _build_replan_with_spawned(
        self,
        past_steps: list,
        current_plan: List[str],
        snapshot: List[dict],
        latest_contradiction: bool,
        spawned: List[Hypothesis],
    ) -> Dict[str, Any]:
        """在旁开 replan 基础上，把新孵化假设的验证步骤置顶。"""
        result = self._build_replan_with_sidebar(
            past_steps, current_plan, snapshot, latest_contradiction
        )
        done = {s for s, _ in past_steps}
        names = [h.name for h in spawned]
        result["plan"] = _prepend_verification(result["plan"], names, done)
        return result


def _prepend_verification(
    plan: List[str], names: List[str], done: set
) -> List[str]:
    """把指定假设的验证步骤置顶（未执行过），总长不超过计划上限。"""
    extra = [f"验证 {name}" for name in names if f"验证 {name}" not in done]
    return (extra + plan)[: _SIDEBAR_PLAN_CAP]
