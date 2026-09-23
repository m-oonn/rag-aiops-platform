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
