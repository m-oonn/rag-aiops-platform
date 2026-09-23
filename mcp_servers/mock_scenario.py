"""统一 MCP mock 剧本(多根因演示)。

service_name → 场景映射,让 demo 按症状可复现多种根因剧情:
  data-sync-service     infra_cpu   指标爬升(CPU 冲到 96% / 内存 85%),日志全 INFO——
                                    即现有"指标异常 + 日志干净"的**矛盾触发 replan** 剧本
  api-gateway-service   network     指标正常,日志里 dial tcp ... connection refused
  auth-service          config      指标正常,日志里 config mismatch / 配置缺失
  order-service         app_oom     内存缓涨不上告警,日志里 OOM / NullPointer 堆栈(应用证据在日志)
  payment-service       dependency  指标正常,日志里 redis/mysql 连接池耗尽
  billing-service       complex_overload  多症状叠加:CPU 偏高不上告警,日志同时含 OOM 堆栈(应用强特征)
                                   与"请求超时"(通用症状词)——检验裁判不被超时带偏到网络/依赖
  inventory-service     cascade_dependency 级联故障:日志同时含 503/缓存不可达(链首根因)
                                   与 MQ lag/线程池积压(级联次生症状)——检验因果链优先
  其他服务名           infra_cpu   默认回退(向后兼容历史行为)

真实化替换策略: 保持 Agent 侧契约(工具名/参数)不变,只替换本模块的取数逻辑为
Prometheus/CLS 查询,agent 代码零改动 —— 这是"先 Mock 后真实"架构的地基。
"""

import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# 场景 → 默认服务名(供模糊匹配)
SCENARIO_SERVICES = {
    "infra_cpu": "data-sync-service",
    "network": "api-gateway-service",
    "config": "auth-service",
    "app_oom": "order-service",
    "dependency": "payment-service",
    "complex_overload": "billing-service",
    "cascade_dependency": "inventory-service",
    # 6 类运维故障覆盖补充: 容器(驱逐/OOMKilled) + 服务接口(超时/熔断)
    "container": "container-service",
    "service_api": "order-api-service",
}

# 每个场景的指标曲线 shape: (曲线形状, 基线, 每步爬升, 封顶)
#   rising: 前 3 点平稳 → 线性爬升(指标必然冲高,触发告警)
#   flat:   基线附近纯抖动(指标正常,不触发告警)
#   slight: 平缓爬升(有一定趋势但不剧烈,配合日志定位应用异常)
_METRIC_SHAPES: Dict[str, Dict[str, Tuple[str, float, float, float]]] = {
    "infra_cpu": {"cpu": ("rising", 10.0, 8.5, 96.0), "memory": ("rising", 30.0, 5.5, 85.0)},
    "network": {"cpu": ("flat", 22.0, 0.0, 40.0), "memory": ("flat", 48.0, 0.0, 60.0)},
    "config": {"cpu": ("flat", 18.0, 0.0, 35.0), "memory": ("flat", 44.0, 0.0, 58.0)},
    # OOM 场景:内存缓涨但不上告警阈值,避免"内存异常"把根因引向基础设施——OOM 的鉴别证据应是日志堆栈
    "app_oom": {"cpu": ("slight", 25.0, 1.2, 60.0), "memory": ("slight", 50.0, 2.5, 68.0)},
    "dependency": {"cpu": ("flat", 20.0, 0.0, 38.0), "memory": ("flat", 46.0, 0.0, 60.0)},
    # 多症状叠加:CPU 偏高(峰值<80 不告警) + 内存缓涨——指标不制造"资源告警"假象,
    # 根因鉴别完全靠日志里的应用堆栈 vs 通用超时词
    "complex_overload": {"cpu": ("slight", 40.0, 3.0, 75.0), "memory": ("slight", 52.0, 1.8, 66.0)},
    # 级联故障:指标完全正常(依赖方不可用的证据在日志侧)
    "cascade_dependency": {"cpu": ("flat", 22.0, 0.0, 40.0), "memory": ("flat", 46.0, 0.0, 60.0)},
    # 容器问题:内存缓涨不上告警(OOMKilled 的鉴别证据在日志的 kubelet/驱逐记录)
    "container": {"cpu": ("flat", 24.0, 0.0, 42.0), "memory": ("slight", 55.0, 2.0, 72.0)},
    # 服务接口:指标正常(接口错误率/耗时的证据在日志)
    "service_api": {"cpu": ("flat", 26.0, 0.0, 44.0), "memory": ("flat", 48.0, 0.0, 60.0)},
}

# 每条日志间隔 1 分钟(毫秒)
LOG_STEP_MS = 60 * 1000

# 场景日志内容:对齐 dynamic_classification 的证据关键词,让各根因可被鉴别
_LOG_MESSAGES: Dict[str, List[Tuple[str, str]]] = {
    # infra:日志干净,是"指标异常 + 日志正常"矛盾剧本的另一半
    "infra_cpu": [
        ("INFO", "正在同步元数据……"),
        ("INFO", "批处理任务心跳正常"),
    ],
    # 网络:只用传输/链路层独有特征(dial tcp / connection refused / reset by peer)
    "network": [
        ("ERROR", "upstream dial tcp 127.0.0.1:3306: connection refused"),
        ("ERROR", "dial tcp 127.0.0.1:3306: connect: connection refused (retry 3/5)"),
        ("ERROR", "http: proxy error: read tcp 10.0.3.21:8080->10.0.4.55:443: read: connection reset by peer"),
    ],
    # 配置:真实 Spring Boot 启动失败格式 + config mismatch 特征
    "config": [
        ("ERROR", "config mismatch: missing property 'auth.token.ttl' in application.yaml"),
        ("ERROR", "APPLICATION FAILED TO START - Property 'spring.datasource.url' is required but not set"),
        ("ERROR", "invalid configuration, fallback to default profile"),
    ],
    # 应用:真实生产 OOM 堆栈(阿里巴巴/Doris 案例: copyOf/grow + heap dump + -XX:OnOutOfMemoryError kill -9)
    "app_oom": [
        ("ERROR", "Exception in thread \"order-worker-7\" java.lang.OutOfMemoryError: Java heap space"),
        ("ERROR", "at java.util.Arrays.copyOf(Arrays.java:3210) at java.util.ArrayList.grow(ArrayList.java:267)"),
        ("ERROR", "Dumping heap to /opt/order-service/heapdump.hprof, -XX:OnOutOfMemoryError=\"kill -9 %p\""),
    ],
    # 依赖:真实 Jedis 连接池耗尽异常(生产高频故障,接口超时率飙升/部分请求 10s+)
    "dependency": [
        ("ERROR", "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool"),
        ("ERROR", "java.util.NoSuchElementException: Timeout waiting for idle object, 连接池耗尽(active=198/maxTotal=200, meanReturnTime 3.2s)"),
        ("INFO", "redis-cli ping 正常, Redis 服务端可达"),
    ],
    # 多症状叠加:应用层强特征(OOM 堆栈)与通用症状词(请求超时)混杂。
    # 检验点:超时是通用症状词(无链路层证据),不应把根因带偏到网络/外部依赖;
    # 应用堆栈应成为主导证据 → 收敛到应用层异常。
    "complex_overload": [
        ("ERROR", "java.lang.OutOfMemoryError: Java heap space"),
        ("ERROR", "java.lang.NullPointerException at com.example.billing.BillingService.checkout(BillingService.java:112)"),
        ("ERROR", "Stacktrace: at com.example.billing.BillingService.lambda$process(BillingService.java:45)"),
        ("WARN", "request read-timeout: client wait 3.2s"),
        ("INFO", "request served normally, latency within SLO"),
    ],
    # 级联故障:链首根因(依赖方不可用)与级联次生症状(MQ lag/线程池积压)混杂。
    # 检验点:503/缓存不可达是链首,不能被 MQ lag 或线程池积压带偏 → 收敛到外部依赖故障。
    "cascade_dependency": [
        ("ERROR", "redis cache cluster one node unreachable, partial misses increasing"),
        ("ERROR", "upstream third-party API returning 503 consistently"),
        ("ERROR", "MQ consumer lag growing, messages accumulating on topic"),
        ("WARN", "thread pool queue backlog due to slow upstream"),
        ("INFO", "request served normally, latency within SLO"),
    ],
    # 容器问题:OOMKilled/驱逐/CrashLoopBackOff——多命中 h_container(oomkilled/evicted/
    # kubelet/被驱逐/重启循环),h_infra 仅能靠 "oom" 单命中,收敛到容器问题。
    "container": [
        ("WARN", "kubelet: Pod order-pod-7 内存使用超过 limit, 触发 OOMKilled"),
        ("ERROR", "Pod order-pod-7 被驱逐 (Evicted), 节点内存不足 (MemoryPressure)"),
        ("ERROR", "CrashLoopBackOff: order-pod-7 反复重启 (LastExitCode=137, OOMKilled)"),
        ("WARN", "容器 order-pod-7 重启 3 次, restart count 持续上升"),
        ("INFO", "Node 内存回收后重新调度, Pod 恢复运行"),
    ],
    # 服务接口异常:错误率飙升/P99 超 SLO/熔断降级/fallback 启用。
    # 检验点:5xx/熔断/降级同时命中 h_app(5xx)与 h_dep(熔断/降级),但矛盾侧
    # (接口恢复/错误率回落)与 h_api 多命中(接口平均/错误率飙升/p99/fallback)压过它们。
    "service_api": [
        ("WARN", "接口 /api/orders 平均耗时 3.2s, P99 达到 5.2s 超过 SLO"),
        ("ERROR", "接口 /api/orders 错误率飙升 12%, 大量 5xx 返回"),
        ("ERROR", "Hystrix 熔断触发: /api/orders 服务降级, fallback 启用"),
        ("WARN", "接口 /api/payments 超时率上升, 客户端等待 3s+"),
        ("INFO", "接口恢复后错误率回落, 熔断关闭"),
    ],
}


def scenario_for_service(service_name: Optional[str]) -> str:
    """按服务名解析场景;未命中(含 None/空)回退 infra_cpu 保持向后兼容。"""
    name = (service_name or "").strip().lower()
    for scenario, svc in SCENARIO_SERVICES.items():
        if svc in name or name in svc:
            return scenario
    return "infra_cpu"


def build_points(
    scenario: str,
    metric: str,
    start: datetime,
    end: datetime,
    interval_min: int,
    jitter: float = 2.0,
) -> List[Dict[str, Any]]:
    """按场景生成指标曲线点列表 [{timestamp: HH:MM, value: float}]。"""
    shape, base, climb, ceiling = _METRIC_SHAPES.get(
        scenario, _METRIC_SHAPES["infra_cpu"]
    )[metric]

    points = []
    current, idx = start, 0
    while current <= end:
        if shape == "flat":
            value = base + random.uniform(-jitter, jitter)
        elif shape == "slight":
            value = min(base + idx * climb, ceiling)
        else:  # rising:前 3 点平稳,之后线性爬升封顶
            if idx < 3:
                value = base + idx * 0.5
            else:
                value = min(base + (idx - 2) * climb, ceiling)
        value = max(0.0, min(100.0, round(value + random.uniform(-jitter, jitter), 1)))
        points.append({"timestamp": current.strftime("%H:%M"), "value": value})
        current += timedelta(minutes=interval_min)
        idx += 1
    return points


def log_lines(scenario: str, start_time: int, end_time: int, limit: int = 100) -> List[Dict[str, Any]]:
    """按场景生成日志行 [{timestamp, level, message}]。"""
    messages = _LOG_MESSAGES.get(scenario, _LOG_MESSAGES["infra_cpu"])
    logs = []
    current = start_time
    idx = 0
    while current <= end_time and len(logs) < limit:
        level, msg = messages[idx % len(messages)]
        logs.append({
            "timestamp": datetime.fromtimestamp(current / 1000).strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": msg,
        })
        current += LOG_STEP_MS
        idx += 1
    return logs
