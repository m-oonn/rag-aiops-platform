"""诊断技能卡路由（B2b——借鉴 pi Skill 懒加载设计）。

背景：planner prompt 原先**每次规划都全量注入** 9 类"主诊断路径"（约占 prompt
一半篇幅）。本模块把 9 类路径提炼为独立"技能卡"（DiagnosisSkill），按输入征兆
关键词做懒加载路由：

  - ENABLE_SKILL_ROUTING=True 且命中征兆 → 只注入 Top-k 命中卡（省 tokens）;
  - 关闭 / 零命中 → 注入全量 9 卡（**兜底 = 旧行为,零风险演进**）。

保真红线：9 张卡的 guidance 与迁移前 planner_prompt 原文**逐字一致**
（验证脚本 verify 见提交说明）；路由只决定"注入哪些卡",不改卡内容。
"""

from dataclasses import dataclass
from typing import List

# 默认注入的命中卡上限（多征兆场景允许 Top-2）
DEFAULT_TOP_K = 2


@dataclass(frozen=True)
class DiagnosisSkill:
    """一张诊断技能卡（guidance 为原 planner prompt 中对应路径段落）。"""

    id: str
    name: str
    symptom_keywords: tuple
    guidance: str


SKILLS: tuple = (
    DiagnosisSkill(
        id="skill.net",
        name="网络/连通性",
        symptom_keywords=("延迟", "丢包", "连接超时", "网络", "dns", "解析失败",
                          "连通性", "网络超时", "tcp", "ping"),
        guidance=(
            "- 网络/连通性:延迟、丢包、连接超时、连通性错误、DNS 解析失败等 → 优先查\n"
            "  网络/连通性指标与日志中的网络错误;若观测含混沌/故障注入,根因锁定为网络;"
        ),
    ),
    DiagnosisSkill(
        id="skill.site",
        name="网址/网站健康检查",
        symptom_keywords=("网址", "url", "网站", "http://", "https://", "能否访问",
                          "打开", "首页"),
        guidance=(
            "- 网址/网站健康检查:**用户直接给出网址(URL)**、或要求检查某网站能否访问\n"
            "  → 通常**一步完成**:实际访问该网站检查能否正常打开,并逐个检查首页里的\n"
            "  链接和图片资源是否正常(一步即可覆盖全面检查,不必拆成两步);\n"
            "  按探测结果给出结论;**如实报告**:网站正常就写\"网站正常\"(可附状态码/耗时),\n"
            "  访问不了就报告具体错误类型;**严禁**臆造不存在的故障;"
        ),
    ),
    DiagnosisSkill(
        id="skill.biz",
        name="页面能打开但功能/任务异常",
        symptom_keywords=("页面能打开", "能打开", "但点", "点击", "提交没反应",
                          "一直不返回", "卡住", "功能报错", "功能异常", "没反应"),
        guidance=(
            "- 页面能打开但功能/任务异常(**重要,别漏**):用户说\"网页能打开,但点某功能\n"
            "  报错/提交没反应/任务一直不返回/审校卡住\"这类\"页面好、服务坏\"的故障 →\n"
            "  页面检查看不出来,**必须下沉到业务层**:规划成\"检查该服务的健康端点/业务\n"
            "  接口是否正常(状态码、是否超时、返回内容)\",必要时再查后台日志;\n"
            "  **不要把结论停在\"网站正常\"**,也不要把根因直接归到\"资源耗尽\"——\n"
            "  页面正常不等于后台服务正常;"
        ),
    ),
    DiagnosisSkill(
        id="skill.port",
        name="服务未启动 / 端口不通",
        symptom_keywords=("端口", "未启动", "没起来", "启动失败", "连接被拒绝",
                          "服务没起", "监听"),
        guidance=(
            "- 服务未启动 / 端口不通:用户给出 `主机:端口`、或怀疑\"某个服务没起来\" →\n"
            "  规划成\"探测该主机的端口是否有服务在监听\";**同机/同网段**下端口\"连接被拒绝\"\n"
            "  说明服务未启动,端口\"连接超时\"只能说明网络层不可达(不能据此断定服务状态);"
        ),
    ),
    DiagnosisSkill(
        id="skill.infra",
        name="基础设施/资源瓶颈",
        symptom_keywords=("cpu", "内存", "磁盘", "连接池", "线程", "资源", "慢查询",
                          "堆积", "超载", "耗尽", "使用率", "卡顿"),
        guidance=(
            "- 基础设施/资源瓶颈:CPU/内存/连接池/线程/IO 等资源耗尽、慢查询、任务堆积\n"
            "  超载 → 优先查资源类指标、连接数、进程/线程状态、队列长度;"
        ),
    ),
    DiagnosisSkill(
        id="skill.app",
        name="应用层异常",
        symptom_keywords=("崩溃", "5xx", "堆栈", "异常堆栈", "服务挂", "挂掉", "重启"),
        guidance=(
            "- 应用层异常:服务崩溃、5xx、接口超时、错误堆栈、近期发布/回滚、SDK/依赖\n"
            "  行为变更 → 优先查应用日志、错误堆栈、发布记录;"
        ),
    ),
    DiagnosisSkill(
        id="skill.config",
        name="配置错误",
        symptom_keywords=("配置", "阈值", "参数", "下发", "限流"),
        guidance=(
            "- 配置错误:配置下发、参数/阈值/超时设置不合理 → 优先核对配置变更时间线,\n"
            "  并结合日志中配置相关报错;"
        ),
    ),
    DiagnosisSkill(
        id="skill.change",
        name="变更/发布引入",
        symptom_keywords=("发布", "部署", "上线", "发版", "灰度", "回滚", "变更",
                          "刚改", "改过配置", "升级"),
        guidance=(
            "- 变更/发布引入(重要,别漏):故障时间点与发布、部署、配置变更、灰度或回滚\n"
            "  高度吻合(如\"刚上线/刚发版/刚改过配置就出问题\")→ 规划一步\"查该服务近期的\n"
            "  变更/发布记录\",把变更时间与故障发生时间对齐;排查资源/应用/配置类故障时,\n"
            "  若怀疑与近期改动相关,也应补一步变更核对(变更与指标/日志是相互独立的证据);"
        ),
    ),
    DiagnosisSkill(
        id="skill.dep",
        name="外部依赖故障",
        symptom_keywords=("数据库", "消息队列", "缓存", "mq", "redis", "mysql",
                          "依赖", "积压", "消费", "连接失败", "不可用"),
        guidance=(
            "- 外部依赖:数据库/消息队列/缓存等依赖不可用、连接失败、MQ 堆积 → 优先查\n"
            "  依赖可用性、连接错误、消费端 lag/积压。"
        ),
    ),
)


def route_skills(input_text: str, *, top_k: int = DEFAULT_TOP_K) -> List[DiagnosisSkill]:
    """按征兆关键词命中计数路由技能卡。

    - 空输入 / 零命中 → 返回全部（兜底=旧行为）；
    - 有命中 → 取命中数最高的 Top-k（多征兆场景允许多卡）。
    """
    if not input_text:
        return list(SKILLS)
    text = input_text.lower()
    scored = []
    for sk in SKILLS:
        hits = sum(1 for kw in sk.symptom_keywords if kw.lower() in text)
        if hits > 0:
            scored.append((hits, sk))
    if not scored:
        return list(SKILLS)
    scored.sort(key=lambda t: (-t[0], t[1].id))  # 命中数降序；同分按 id 稳定序
    return [sk for _, sk in scored[:top_k]]


def render_skills_block(skills: List[DiagnosisSkill]) -> str:
    """把技能卡渲染为可注入 planner prompt 的文本块（卡间以换行拼接）。"""
    return "\n".join(sk.guidance for sk in skills)
