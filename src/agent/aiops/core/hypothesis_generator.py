"""动态假设孵化器：当现有假设无法解释观测时，孵化隐藏故障假设。

触发场景（spec §7.3）：
  1. 当前最大假设概率过低（< 阈值），说明 5 条通用根因都解释不了观测；
  2. 输入/观测中包含未被任何现有假设覆盖的领域线索。

实现：
  - 规则式线索库（确定性、可测试）：内置运维常见隐藏故障线索
    （缓存键冲突、定时任务重叠、依赖版本回退、时钟漂移、监控采集异常、
    数据一致性、资源泄漏等）；
  - 新假设默认获得保护期，避免刚孵化就被误杀。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from src.agent.aiops.core.hypothesis import Hypothesis


class HiddenFaultClue(BaseModel):
    """一条隐藏故障线索：命中关键词即孵化对应假设。"""

    id: str = Field(description="线索唯一 ID")
    name: str = Field(description="孵化出的假设名称")
    description: str = Field(default="", description="假设描述")
    keywords: List[str] = Field(description="触发关键词（命中即线索）")
    min_hits: int = Field(default=1, description="最少命中关键词数")
    expected_findings: List[str] = Field(default_factory=list, description="孵化假设的预期证据")
    contradictions: List[str] = Field(default_factory=list, description="孵化假设的矛盾证据")


# ── 内置隐藏故障线索库 ────────────────────────────────────
_HIDDEN_FAULT_CATALOG: List[HiddenFaultClue] = [
    HiddenFaultClue(
        id="cache_key",
        name="缓存键冲突/缓存击穿",
        description="缓存 key 命名冲突或热点 key 失效导致击穿，症状类似资源/依赖故障",
        keywords=["缓存key", "缓存 key", "key 冲突", "缓存键", "缓存击穿", "热点key", "热点 key", "key 失效"],
        expected_findings=["缓存命中率下降", "缓存key", "key 冲突", "热点", "穿透", "击穿"],
        contradictions=["缓存正常", "命中率正常"],
    ),
    HiddenFaultClue(
        id="cron_overlap",
        name="定时任务时间窗口重叠",
        description="定时任务/批量任务时间窗口重叠导致资源竞争与锁等待",
        # 收紧线索关键词(505 误孵化根因)：旧值含裸泛词 "时间窗口"/"调度"/"重叠"/"归档"，
        # 会被 executor 步骤文本/计划回显误命中(如"构造最近 15 分钟的**时间窗口**"、
        # "用于后续日志查询的**时间范围**")，在第 2 步尚无任何证据时就凭空孵化隐藏假设，
        # 随后"验证 定时任务时间窗口重叠"步骤自证自答、一路涨到 76%。改用复合症状词，
        # 只有真实"任务/窗口重叠"语义才命中；裸 "整点" 保留(周期性故障强信号,spec prompt 第 11 条)。
        keywords=["定时任务", "cron", "整点", "批量任务", "任务重叠", "时间窗口重叠",
                  "调度重叠", "归档任务", "任务堆叠", "批量任务重叠"],
        expected_findings=["定时任务", "cron", "锁等待", "慢查询", "整点", "并发执行", "重叠"],
        contradictions=["任务正常", "无并发冲突"],
    ),
    HiddenFaultClue(
        id="version_compat",
        name="依赖版本兼容性",
        description="依赖/客户端版本升级或回退引发的协议或行为不兼容",
        keywords=["版本升级", "版本回退", "回退版本", "降级版本", "sdk升级", "sdk 升级", "客户端升级", "版本变更"],
        expected_findings=["版本", "sdk", "客户端", "协议", "兼容", "升级", "回退"],
        contradictions=["版本正常", "无变更"],
    ),
    HiddenFaultClue(
        id="clock_skew",
        name="时钟同步异常",
        description="NTP 同步失败导致节点间时间偏移，触发分布式事务/证书/日志时间错乱",
        keywords=["时钟漂移", "ntp", "时间同步", "chronyd", "时钟偏移", "时间偏差", "时间不同步"],
        expected_findings=["ntp", "时钟", "时间同步", "时间偏差", "偏移"],
        contradictions=["时间同步正常"],
    ),
    HiddenFaultClue(
        id="monitor_fault",
        name="监控采集链路异常",
        description="监控 Agent/采集脚本故障导致指标失真或误报，根因不在业务侧",
        keywords=["监控agent", "监控 agent", "采集脚本", "采集器", "agent bug", "监控误报", "采集异常", "采集失败"],
        expected_findings=["监控", "采集", "agent", "指标异常", "误报", "数据缺失"],
        contradictions=["监控正常", "采集正常"],
    ),
    HiddenFaultClue(
        id="data_consistency",
        name="数据一致性/主从延迟",
        description="主从同步延迟或数据不一致，读到的数据滞后或相互矛盾",
        keywords=["主从延迟", "数据不一致", "binlog", "seconds_behind", "replication lag", "同步延迟", "读写不一致"],
        expected_findings=["主从", "延迟", "同步", "不一致", "binlog", "滞后"],
        contradictions=["数据一致", "同步正常"],
    ),
    HiddenFaultClue(
        id="resource_leak",
        name="资源泄漏",
        description="连接/线程/文件句柄等资源缓慢泄漏，随运行时间累积恶化",
        keywords=["连接泄漏", "线程泄漏", "句柄泄漏", "fd泄漏", "fd 泄漏", "连接数持续增长", "句柄数增长", "资源泄漏"],
        expected_findings=["连接数", "线程数", "句柄", "fd", "泄漏", "持续增长", "缓慢上升"],
        contradictions=["资源回收正常", "无泄漏"],
    ),
]


class HypothesisGenerator:
    """动态假设孵化器（规则式，确定性）。

    Args:
        catalog: 隐藏故障线索库；不传使用内置库。
        protection_rounds: 新假设的保护轮数。
        default_probability: 新假设的初始概率。
    """

    def __init__(
        self,
        catalog: List[HiddenFaultClue] | None = None,
        protection_rounds: int = 2,
        default_probability: float = 0.18,
    ) -> None:
        self.catalog = catalog or _HIDDEN_FAULT_CATALOG
        self.protection_rounds = protection_rounds
        self.default_probability = default_probability

    def generate(
        self,
        hypotheses: List[Hypothesis],
        observations: List[str],
        input_text: str = "",
        birth_step: int = 0,
    ) -> List[Hypothesis]:
        """根据输入与观测，返回尚未覆盖的隐藏故障假设。

        返回的新假设为独立副本，调用方负责 add 到 HypothesisManager。
        """
        existing_names = {h.name for h in hypotheses}
        existing_ids = {h.id for h in hypotheses}
        text = f"{input_text} {' '.join(observations)}".lower()

        spawned: List[Hypothesis] = []
        for clue in self.catalog:
            if clue.name in existing_names or f"h_{clue.id}" in existing_ids:
                continue
            hits = sum(1 for kw in clue.keywords if kw in text)
            if hits >= clue.min_hits:
                spawned.append(
                    Hypothesis(
                        id=f"h_{clue.id}",
                        name=clue.name,
                        description=clue.description,
                        expected_findings=clue.expected_findings,
                        contradictions=clue.contradictions,
                        probability=self.default_probability,
                        birth_step=birth_step,
                        protection_rounds=self.protection_rounds,
                    )
                )
        return spawned
