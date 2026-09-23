"""证据裁判：将观测文本映射为对假设的 Evidence。

两级设计：
  1. LLM 语义裁判（judge_async，首选）：理解同义词/否定句/隐含证据，
     输出结构化判定；失败或未配置 LLM 时自动降级到规则。
  2. 规则裁判（judge，确定性兜底）：关键词模式匹配。
     - 优先使用假设自身定义的 expected_findings / contradictions 模式
     - 未定义时回退到内置关键词表
     - 同一条观测中可同时产生 support 与 contradict 证据（代理上报不一致场景）
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, List, Optional

from pydantic import BaseModel, Field

from src.agent.aiops.core.hypothesis import Evidence, Hypothesis
from src.utils.logger import logger

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

# 内置 fallback 关键词表：假设名称 -> (support_keywords, contradict_keywords)
_FALLBACK_KEYWORDS: dict[str, tuple[list[str], list[str]]] = {
    "基础设施/资源瓶颈": (
        ["cpu", "memory", "disk", "load", "资源", "性能", "负载", "使用率高", "fd", "文件描述符", "inode", "句柄", "oom", "耗尽"],
        ["cpu 正常", "memory 正常", "资源充足", "负载正常", "fd 正常", "inode 充足"],
    ),
    "应用层异常": (
        ["error", "exception", "crash", "应用", "服务", "业务异常", "死锁", "deadlock", "线程", "thread", "gc", "停顿", "stw", "jstack", "rejectedexecution", "端口冲突",
         "堆栈", "线程池", "死循环", "请求超时"],
        ["app 正常", "应用正常", "无错误", "线程正常", "无死锁"],
    ),
    "网络/连通性问题": (
        ["dial tcp", "connection refused", "connection reset", "tcp connect", "handshake",
         "握手失败", "网络不可达", "路由不可达", "无法解析域名", "域名解析失败", "dns 解析",
         "防火墙", "mtu", "分片", "丢包", "重传", "拥塞", "ssl", "tls", "证书过期", "icmp",
         "网络超时", "连接超时", "连接失败", "连接中断"],
        ["网络正常", "连接正常", "无超时", "ping 正常", "路由正常"],
    ),
    "配置错误": (
        ["config", "setting", "permission", "配置", "权限", "配置项", "阈值", "threshold", "超时设置", "时钟偏移"],
        ["配置正确", "配置正常", "配置匹配", "默认配置正常"],
    ),
    "外部依赖故障": (
        ["database", "redis", "api", "外部", "依赖", "第三方", "mq", "消息队列", "kafka", "replication", "主从", "同步", "不一致", "降级", "熔断", "慢查询", "锁等待", "连接池"],
        ["依赖正常", "外部服务正常", "database 正常", "redis 正常"],
    ),
}

# ── 严重级权重（1a 机制收口）────────────────────────────────────
# 故障日志常按严重级标注 [ERROR]/[WARN]/[INFO]。主治症状以 ERROR/WARN 出现，
# 干扰/次生/噪声多为 INFO。这里按行解析严重级，对某一假设的**支持证据**按其
# 证据行的严重级加权：ERROR 主治强度保留、WARN 略降、仅来自 INFO 的干扰被压制，
# 从代码层强制"主治 > 干扰"，不依赖 LLM 是否自觉遵守 prompt。
_SEVERITY_WEIGHT = {"ERROR": 1.0, "WARN": 0.9, "INFO": 0.45}
_SEVERITY_UNKNOWN = 0.7  # 观察文本无严重级标注时给一个中性折扣

# 严重级归属用关键词：比"判定关键词"更宽，用于判断某条日志行"关系到哪个假设"，
# 从而只对确实来自 INFO 干扰行的支持证据做压制（不削弱 ERROR 主治）。
_ATTR_KEYWORDS: dict[str, list[str]] = {
    "基础设施/资源瓶颈": [k.lower() for k in _FALLBACK_KEYWORDS["基础设施/资源瓶颈"][0]]
    + ["cpu 使用", "内存使用", "线程池", "gc pause", "负载", "排队"],
    "应用层异常": ["exception", "error", "stacktrace", "堆栈", "oom", "outofmemory",
                "nullpointer", "rejected", "rejected execution", "crash", "崩溃",
                "死锁", "deadlock", "线程", "thread", "st str", "stall", "gc", "5xx"],
    "网络/连通性问题": ["connect", "timed out", "timeout", "超时", "connection",
                   "连接", "丢包", "handshake", "握手", "dial tcp", "refused",
                   "reset", "网络", "dns", "routing", "路由", "icmp", "重传", "tls", "ssl"],
    "配置错误": ["config", "配置", "阈值", "threshold", "429", "限流", "routing",
              "permission", "权限", "时钟偏移", "timeout setting", "revision", "rate limit"],
    "外部依赖故障": ["database", "redis", "mq", "kafka", "api", "503", "依赖",
                 "fallback", "降级", "熔断", "慢查询", "锁等待", "replication",
                 "主从", "cache cluster", "消息队列", "consumer", "消费", "上游"],
}

_LEVEL_TAG_RE = re.compile(r"\[(error|warn|info)\]\s*", flags=re.IGNORECASE)


def _strip_severity_tags(text: str) -> str:
    """剥离行首的严重级标记 [ERROR]/[WARN]/[INFO]。

    此类标记是日志的严重级元数据而非证据内容。关键词匹配若不剥离，会误判
    例如假设模式 `error` 命中 `[ERROR]` 行，凭空给应用层假设判出支持证据
    （303 场景误判的确定性复现根因）。严重级仍保留在原文本中被
    _severity_multiplier_for 解析使用，这里只影响 evidence 的关键词匹配。
    """
    if not text:
        return text
    return _LEVEL_TAG_RE.sub("", text)


# ── LLM 语义裁判 ──────────────────────────────────────────
# 让 LLM 理解同义词、否定句与隐含证据，输出对每个假设的判定。
_EVIDENCE_SYSTEM_PROMPT = (
    "你是故障诊断领域的证据裁判。给定一段观测文本和一组诊断假设，"
    "判断该观测对**每个**假设是 support(支持)、contradict(矛盾) 还是 neutral(无关)。\n"
    "要求：\n"
    "1. 正确理解否定句与语义（例如「cpu 高的情况并未出现」应判定基础设施为 contradict，"
    "而非把其中的『cpu 高』当成支持）；\n"
    "2. 正确识别同义表述（例如「处理器满载 / CPU 使用率接近 100%」应支持资源瓶颈）；\n"
    "3. 仅根据观测文本本身判断，不要臆测未提供的信息；\n"
    "4. strength 表示证据强度：0~1，明确命中给 0.6~1.0，弱线索给 0.3~0.5。\n"
    "5. 观测中的『未找到 / 不存在 / 无可用资源』（如未找到日志主题、无知识库、"
    "服务未注册）是环境资源缺失，**不应**据此判定为配置错误，应判 neutral 或"
    "结合上下文支持更相关的假设；指标峰值超过阈值属于资源/性能问题，"
    "不要把它解读为阈值配置错误。\n"
    "6. 因果链/级联场景中，链首的触发事件（如 DNS 解析失败、故障注入、DDoS 流量、"
    "变更/发布操作）通常是根因；后续观测多为级联症状，症状证据不应覆盖根因证据。"
    "当观测同时指向链首触发事件与级联症状时，链首对应假设必须判 support 且 strength≥0.6，"
    "级联症状对应假设判 neutral 或低强度，不得因症状证据更多/更靠后就把根因反转。\n"
    "7. 消息中间件（Kafka/MQ）的消费端问题（lag 积压、rebalance、消费者处理变慢、"
    "消费组异常）属于应用层异常；外部依赖故障仅指依赖方本身不可用或响应超时。"
    "若观测**只**提到 MQ/Kafka 消费 lag/积压/rebalance/消费者处理变慢，判应用层 support(strength≥0.6)。"
    "但若观测**同时**包含依赖方本身不可用的强证据（如第三方 API 持续 503、缓存集群节点不可达、"
    "数据库/Redis 连接失败、消息队列本身不可用、连接池耗尽），则依赖方不可用是链首根因，"
    "MQ consumer lag 只是级联次生症状——此时必须判外部依赖故障 support(strength≥0.6)、"
    "应用层判 neutral 或弱支持(strength≤0.3)，不得被 MQ lag 的主观测带偏。"
    "（遵循第 6 条因果链原则：链首触发事件优先，级联症状不覆盖根因。）\n"
    "8. 混沌工程/故障注入/人为注入造成的网络延迟、丢包属于网络问题，这是**根因锁定信号**。"
    "观测文本中只要出现『混沌/故障注入/人为注入/注入延迟/注入丢包/注入网络』等表述，"
    "**必须**将网络/连通性问题判为 support 且 strength≥0.8，这是链首触发事件，优先级最高；"
    "因延迟触发的线程池耗尽、熔断、降级失败、服务重启等是次生影响，"
    "**严禁**据此将应用层异常或配置错误判为高强度 support（只能判 neutral 或 strength≤0.3 的弱支持），"
    "不得让次生假设成为根因。"
    "『停止故障注入后恢复』、『回退注入后正常』是验证根因的手段，"
    "应进一步增强网络假设的支持（strength≥0.7），而不是转向配置或应用。\n"
    "\n"
    "示例（必须遵循）：\n"
    "观测：『混沌工程平台注入200ms网络延迟后错误率飙升，Hystrix熔断策略未生效，"
    "线程池被耗尽，停止故障注入后延迟恢复但线程池需重启』\n"
    "正确判定：网络/连通性问题 support 0.9（根因锁定）；应用层异常 neutral（线程池耗尽是次生症状）；"
    "配置错误 neutral（降级失败不是根因）；外部依赖 neutral；基础设施 neutral。\n"
    "错误判定警示：应用层异常 support 0.7（线程池耗尽）是典型的症状误判，必须避免。\n"
    "\n"
    "9. 由版本升级/回滚/降级直接触发并通过回退版本解决的问题（如 SDK 行为变更、"
    "客户端协议不兼容）属于应用层异常，而不是配置变更；『回退/回滚版本』是验证手段，"
    "不要把动作本身判为配置变更。但灰度发布/滚动发布/部署操作直接触发的故障"
    "（如部分节点配置不一致、新版本参数/环境变量错误）属于配置变更/部署问题，"
    "『回滚灰度』同样只是验证手段。区分标准：SDK/客户端/服务端软件版本的行为变更→"
    "应用层异常；发布/部署/灰度/配置动作本身导致的故障→配置变更/部署问题。\n"
    "10. 同一条观测通常只指向最相关的 1~2 个假设：只对其明确相关的假设给出"
    "support/contradict（strength≥0.5），其余假设若无明确关联判 neutral(strength=0)；"
    "避免为覆盖全部假设而对多条假设同时给出高强度判定，那会稀释证据信号。\n"
    "11. 周期性/有规律的故障（如整点、固定时间点触发）是真实故障的强信号，"
    "不应判为『无故障/监控误报』；『无故障』假设只适用于监控/告警/采集链路本身"
    "被证实有误（如误报、采集脚本 bug）的场景。『某时段指标正常』只说明故障是间歇性的，"
    "不能作为无故障的证据。\n"
    "12. 定位层级区分（重要）：『timeout / 超时 / connect / 连接失败』是**通用症状词**，"
    "出现它们**并不自动**判给网络。必须先判断故障被定位到哪一层："
    "观测明确指出链路/传输层证据（TCP 握手未完成、connection reset、dial tcp 失败、"
    "connection refused、丢包、重传、DNS 解析失败、路由/网络不可达、防火墙拦截、证书过期）"
    "才判网络/连通性问题 support；指向数据库/Redis/MQ/依赖调用超时→外部依赖或应用层；"
    "出现异常堆栈/进程/线程/队列→应用层异常；只出现资源指标波动→基础设施。"
    "示例：『请求 database 超时，SqlTimeoutException』应判外部依赖或应用层，**不是**网络；"
    "『dial tcp 10.0.4.55:443 ... handshake stalled』才是网络。\n"
    "13. 主治 vs 干扰：若观测中的多条日志带有严重级别(ERROR/WARN/INFO)，级别为 ERROR/WARN 的"
    "主治信号证据强度应**显著高于** INFO 级别的弱干扰信号；无关/弱干扰信号判 neutral 或低强度，"
    "不得让一条弱干扰推翻多条强主治。\n"
    "14. 容器层信号锁定：观测出现 kubelet / pod 驱逐(evict) / OOMKilled / CrashLoopBackOff / "
    "容器重启等容器编排层明确信号时，即使同时出现 node memory pressure / disk pressure / "
    "节点资源压力 等表述，也应判定容器问题 support(strength≥0.6)，基础设施/资源瓶颈判 neutral "
    "或弱支持(strength≤0.3)——node/disk pressure 是容器被驱逐的触发条件，属容器层现象，"
    "不是泛资源瓶颈，不得把容器场景判成基础设施/资源瓶颈。\n"
    "15. GC/内存分配阻塞属资源瓶颈（707 修复）：观测出现 GC 停顿（GC pause / gc pause / "
    "停顿 lengthening）或内存分配阻塞（blocked on allocation / allocation / 分配阻塞 / 内存分配）时，"
    "即使伴随 'threads blocked' / 'application threads' 等字样，只要上下文是 GC 或内存分配，"
    "也应判定基础设施/资源瓶颈 support(strength≥0.5)，应用层异常判 neutral 或弱支持(strength≤0.3)——"
    "GC 停顿与分配阻塞是内存压力症状，不是应用层线程逻辑问题；不得仅因 'threads blocked' 字样"
    "就把资源瓶颈场景判成应用层异常。"
)


class _EvidenceVerdict(BaseModel):
    """LLM 对单个假设的判定。"""

    target_hypothesis_id: str = Field(description="假设 ID")
    relation: str = Field(description="support / contradict / neutral")
    strength: float = Field(ge=0.0, le=1.0, description="证据强度 0~1")
    reasoning: str = Field(description="一句话判定理由")


class _EvidenceBatch(BaseModel):
    """LLM 对全部假设的批量判定。"""

    verdicts: List[_EvidenceVerdict] = Field(description="对每个假设的判定")


class EvidenceJudge:
    """两级证据裁判器：LLM 语义优先，规则关键词兜底。

    Args:
        llm: 可选 ChatOpenAI 实例。提供时 judge_async 走 LLM 语义判断；
             失败或未提供时降级到规则 judge()（同步，确定性）。
    """

    def __init__(self, llm: Optional[Any] = None) -> None:
        self._llm = llm

    async def judge_async(
        self,
        hypotheses: List[Hypothesis],
        observation: str,
        step: int = 0,
        source: str = "executor",
    ) -> List[Evidence]:
        """LLM 语义裁判；LLM 不可用或失败时降级到规则裁判。"""
        if self._llm is not None:
            try:
                return await self._judge_with_llm(hypotheses, observation, step, source)
            except Exception as e:
                logger.warning(
                    "[evidence_judge] LLM 判定失败,降级规则: %s: %s", type(e).__name__, e
                )
        return self.judge(hypotheses, observation, step, source)

    async def _judge_with_llm(
        self,
        hypotheses: List[Hypothesis],
        observation: str,
        step: int,
        source: str,
    ) -> List[Evidence]:
        """调用 LLM 结构化输出，把观测映射为对每个假设的证据。"""
        hyp_lines = "\n".join(
            f"- id={h.id} name={h.name}: "
            f"若为真,预期出现 {' / '.join(h.expected_findings[:6])};"
            f"不应出现 {' / '.join(h.contradictions[:6])}"
            for h in hypotheses
        )
        messages = [
            ("system", _EVIDENCE_SYSTEM_PROMPT),
            ("human", f"观测文本：\n{observation}\n\n假设列表：\n{hyp_lines}\n\n请为每个假设输出判定。"),
        ]

        structured = self._llm.with_structured_output(_EvidenceBatch, method="function_calling")
        result = await structured.ainvoke(messages)

        id2hyp = {h.id: h for h in hypotheses}
        evidences: List[Evidence] = []
        for v in result.verdicts:
            if v.target_hypothesis_id not in id2hyp:
                continue
            relation = v.relation if v.relation in ("support", "contradict", "neutral") else "neutral"
            evidences.append(
                Evidence(
                    source=source,
                    target_hypothesis_id=v.target_hypothesis_id,
                    relation=relation,
                    strength=min(max(v.strength, 0.0), 1.0),
                    description=f"[LLM] {v.reasoning}",
                    step=step,
                )
            )
        if not evidences:
            raise ValueError("LLM 未返回任何判定")

        # 混沌/故障注入根因锁定：即使 LLM 摇摆，也强制保证网络假设获得强支持
        evidences = self._apply_chaos_injection_override(
            hypotheses, observation, evidences, step, source
        )
        return self._apply_severity_weighting(hypotheses, observation, evidences)

    def judge(
        self,
        hypotheses: List[Hypothesis],
        observation: str,
        step: int = 0,
        source: str = "executor",
    ) -> List[Evidence]:
        """将 observation 转换为对每个假设的 Evidence 列表。"""
        text = observation.lower() if isinstance(observation, str) else str(observation).lower()
        # 关键词匹配用剥离严重级标记后的文本：`[ERROR]` 是日志的严重级元数据，
        # 不是证据内容。否则规则裁判会误以为正文出现了 "error"(303:外部依赖故障场景，
        # 应用层假设被 [ERROR] 标记本身命中 `error` 判出 spurious 支持 0.55)。
        # 严重级仍保留在原 observation 中，供 _apply_severity_weighting 加权。
        match_text = _strip_severity_tags(text)
        evidences: List[Evidence] = []

        # 混沌/故障注入优先规则：只要观测包含注入关键词，直接锁定网络假设为根因，
        # 并跳过其他假设的详细关键词匹配，避免线程池耗尽/熔断等次生症状误判为应用/配置问题。
        if self._contains_injection_keyword(text):
            for h in hypotheses:
                if "网络" in h.name or "连通性" in h.name:
                    evidences.append(
                        Evidence(
                            source=source,
                            target_hypothesis_id=h.id,
                            relation="support",
                            strength=0.9,
                            description="[规则兜底] 观测包含混沌/故障注入关键词，根因锁定为网络问题",
                            step=step,
                        )
                    )
                else:
                    evidences.append(
                        Evidence(
                            source=source,
                            target_hypothesis_id=h.id,
                            relation="neutral",
                            strength=0.0,
                            description="[规则兜底] 混沌/故障注入场景下，其他假设为次生症状或无关",
                            step=step,
                        )
                    )
            return evidences

        for h in hypotheses:
            support_patterns = h.expected_findings or []
            contradict_patterns = h.contradictions or []

            # 若假设没有显式模式，使用 fallback 关键词
            if not support_patterns and not contradict_patterns:
                support_patterns, contradict_patterns = self._fallback_patterns(h.name)

            support_hits = [p for p in support_patterns if p.lower() in match_text]
            contradict_hits = [p for p in contradict_patterns if p.lower() in match_text]

            if support_hits:
                evidences.append(
                    Evidence(
                        source=source,
                        target_hypothesis_id=h.id,
                        relation="support",
                        strength=self._compute_strength(support_hits, support_patterns),
                        description=f"观测命中支持模式: {', '.join(support_hits)}",
                        step=step,
                    )
                )

            if contradict_hits:
                evidences.append(
                    Evidence(
                        source=source,
                        target_hypothesis_id=h.id,
                        relation="contradict",
                        strength=self._compute_strength(contradict_hits, contradict_patterns),
                        description=f"观测命中矛盾模式: {', '.join(contradict_hits)}",
                        step=step,
                    )
                )

            # 没有任何命中时，生成一条 neutral 证据占位，便于追踪
            if not support_hits and not contradict_hits:
                evidences.append(
                    Evidence(
                        source=source,
                        target_hypothesis_id=h.id,
                        relation="neutral",
                        strength=0.0,
                        description="观测与假设模式无匹配",
                        step=step,
                    )
                )

        return self._apply_severity_weighting(hypotheses, observation, evidences)

    @staticmethod
    def _fallback_patterns(name: str) -> tuple[list[str], list[str]]:
        """按假设名称返回内置关键词兜底。"""
        for key, (support, contradict) in _FALLBACK_KEYWORDS.items():
            if key in name or name in key:
                return support, contradict
        return [], []

    @staticmethod
    def _severity_multiplier_for(observation: str, hypothesis_name: str) -> float:
        """按观测中"归属于某假设"的日志行的最高严重级，返回支持证据强度乘子。

        归属判定用 _ATTR_KEYWORDS(比判定关键词更宽)。只有该假设有带严重级标注
        [ERROR]/[WARN]/[INFO] 的归属行时才加权，否则不改变原强度：
          - ERROR 主治 → 乘子 1.0(保留)
          - WARN       → 0.9
          - INFO 干扰  → 0.45(被系统性压制)
        从代码层实现「ERROR 主治 > INFO 干扰」，不依赖 LLM 是否自觉遵守 prompt。
        """
        attrs = _ATTR_KEYWORDS.get(hypothesis_name, [])
        if not attrs:
            return 1.0
        if not isinstance(observation, str):
            observation = str(observation)
        found = False
        best = 0.0
        for line in observation.split("\n"):
            m = re.search(r"\[(ERROR|WARN|INFO)\]", line, flags=re.IGNORECASE)
            if not m:
                continue
            low = line.lower()
            if any(kw in low for kw in attrs):
                found = True
                best = max(best, _SEVERITY_WEIGHT[m.group(1).upper()])
        return best if found else 1.0

    @classmethod
    def _apply_severity_weighting(
        cls,
        hypotheses: List[Hypothesis],
        observation: str,
        evidences: List[Evidence],
    ) -> List[Evidence]:
        """仅对**支持证据**按其证据行严重级加权。

        矛盾证据不参与(矛盾任何级别都是强负面信号)；无归属/无严重级标注时保持原强度。
        """
        name_by_id = {h.id: h.name for h in hypotheses}
        adjusted: List[Evidence] = []
        for ev in evidences:
            if ev.relation != "support":
                adjusted.append(ev)
                continue
            w = cls._severity_multiplier_for(observation, name_by_id.get(ev.target_hypothesis_id, ""))
            if w < 1.0:
                ev = ev.model_copy(update={"strength": round(min(ev.strength * w, 1.0), 3)})
            adjusted.append(ev)
        return adjusted

    @staticmethod
    def _compute_strength(hits: list[str], patterns: list[str]) -> float:
        """命中越多强度越高，上限 1.0。不受 patterns 总数稀释。"""
        if not patterns:
            return 0.5
        # 前 3 个 hit 分别贡献 0.35, 0.25, 0.20，后续每个 0.10；保底 +0.20
        tiers = [0.35, 0.25, 0.20]
        base = sum(tiers[: len(hits)]) + 0.10 * max(0, len(hits) - 3) + 0.20
        return min(round(base, 2), 1.0)

    @staticmethod
    def _contains_injection_keyword(text: str) -> bool:
        """判断观测是否包含混沌/故障注入类关键词。"""
        injection_keywords = [
            "混沌", "故障注入", "人为注入", "注入延迟", "注入丢包",
            "注入网络", "chaos", "injection", "inject",
        ]
        return any(kw in text for kw in injection_keywords)

    @classmethod
    def _apply_chaos_injection_override(
        cls,
        hypotheses: List[Hypothesis],
        observation: str,
        evidences: List[Evidence],
        step: int,
        source: str,
    ) -> List[Evidence]:
        """对包含混沌/注入关键词的观测进行根因锁定修正。

        如果 LLM 未给网络假设足够强度的 support，强制提升；
        同时将应用层/配置层因次生症状（线程池耗尽、熔断、降级失败等）
        给出的高强度 support 压制为 neutral 或弱支持。
        """
        text = observation.lower() if isinstance(observation, str) else str(observation).lower()
        if not cls._contains_injection_keyword(text):
            return evidences

        # 找到网络假设和相关次生假设的 ID
        net_ids = {h.id for h in hypotheses if "网络" in h.name or "连通性" in h.name}
        secondary_ids = {h.id for h in hypotheses if h.name in {"应用层异常", "配置错误"}}

        result: List[Evidence] = []
        net_max_strength = 0.0
        for ev in evidences:
            if ev.target_hypothesis_id in net_ids and ev.relation == "support":
                net_max_strength = max(net_max_strength, ev.strength)

        # 如果网络假设没有足够强支持，追加一条强支持证据
        if net_max_strength < 0.8:
            for hid in net_ids:
                result.append(
                    Evidence(
                        source=source,
                        target_hypothesis_id=hid,
                        relation="support",
                        strength=0.85,
                        description="[根因锁定] 观测包含混沌/故障注入，强制提升网络假设支持",
                        step=step,
                    )
                )

        for ev in evidences:
            # 对次生假设因线程池耗尽/熔断/降级失败等给出的 support 进行压制
            if (
                ev.target_hypothesis_id in secondary_ids
                and ev.relation == "support"
                and ev.strength > 0.3
                and any(kw in text for kw in ["线程池", "熔断", "降级", "重启", "hystrix"])
            ):
                ev = ev.model_copy(update={"strength": 0.3, "relation": "neutral"})
            result.append(ev)

        return result
