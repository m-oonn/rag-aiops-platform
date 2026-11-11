import asyncio

import aiohttp
from fastapi import APIRouter, Depends

from src.settings import settings
from src.worker.celery_app import celery_app
from src.api.dependencies import get_current_user
from src.database.models import User

router = APIRouter()


@router.get("")
async def health_check():
    """健康检查。挂载前缀是 `/api/v1/health`，故实际路径为 `GET /api/v1/health`。

    历史上这里写成 `"/health"`，与挂载前缀叠成了 `/api/v1/health/health`，
    与 README 记的 `GET /health` 也不一致。下面的 `/health` 作为兼容别名保留，
    避免已经按旧路径配置的外部探活立刻 404。
    """
    return {"status": "ok", "version": "1.0.0"}


@router.get("/health", include_in_schema=False)
async def health_check_legacy():
    """兼容别名：等价于 `GET /api/v1/health`，新接入请用后者。"""
    return await health_check()


def _broker_error() -> str | None:
    """探测消息中间件（RabbitMQ）是否可达；可达返回 None，否则返回原因。

    区分这件事之前是做不到的：`inspect()` 在两种情况下都返回空，
    于是"中间件挂了"与"队列是空的"在响应里长得一模一样。
    """
    try:
        conn = celery_app.connection_for_read()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.release()
        return None
    except Exception as e:  # kombu 的 OperationalError 等
        return f"{type(e).__name__}: {e}"[:120]


@router.get("/queues")
async def get_queue_stats(current_user: User = Depends(get_current_user)):
    """安全最佳实践: /queues 暴露 Celery 任务详情，需认证。

    三种情况必须能分清，否则前端只能把三者都画成 0：
    - `unavailable` 中间件不可达（连 RabbitMQ 都连不上）；
    - `degraded`     中间件正常但没有在线 Worker（任务会堆积、不会被消费）；
    - `ok`          有 Worker 在线，计数可直接读。
    """
    broker_error = _broker_error()
    if broker_error:
        return {
            "status": "unavailable",
            "message": "任务队列中间件（RabbitMQ）不可达，队列统计不可用",
            "detail": broker_error,
        }

    try:
        # 先 ping：没有 Worker 时立即返回，避免下面四次广播各等一个超时（原来约 4 秒）
        workers = celery_app.control.ping(timeout=1.0) or []
        if not workers:
            return {
                "status": "degraded",
                "message": "消息中间件正常，但没有在线 Worker：新任务只会堆积，不会被处理",
                "summary": {"active_tasks": 0, "reserved_tasks": 0, "scheduled_tasks": 0},
                "details": {"active": {}, "reserved": {}, "scheduled": {}, "worker_stats": {}},
            }

        i = celery_app.control.inspect()
        if not i:
            return {"status": "unavailable", "message": "无法连接 Celery inspector"}

        active = i.active() or {}
        reserved = i.reserved() or {}
        scheduled = i.scheduled() or {}
        stats = i.stats() or {}

        # Calculate total counts
        total_active = sum(len(tasks) for tasks in active.values())
        total_reserved = sum(len(tasks) for tasks in reserved.values())
        total_scheduled = sum(len(tasks) for tasks in scheduled.values())

        return {
            "status": "ok",
            "summary": {
                "active_tasks": total_active,
                "reserved_tasks": total_reserved,
                "scheduled_tasks": total_scheduled,
                "workers": len(workers),
            },
            "details": {
                "active": active,
                "reserved": reserved,
                "scheduled": scheduled,
                "worker_stats": stats
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ──────────────────────────────────────────────
#  依赖健康检查（异步并发，整体 < 6 秒）
# ──────────────────────────────────────────────

async def _check_http(name: str, url: str, timeout: float = 3) -> dict:
    """检测 HTTP 服务是否可达（任何 HTTP 响应都算可达，不要求 200）。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                # 只要有响应就算服务可达（MCP 服务可能返回 404）
                return {"status": "ok", "error": None}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


async def _check_rabbitmq() -> dict:
    """检测 RabbitMQ 是否可达。"""
    def _sync():
        import pika
        credentials = pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD)
        params = pika.ConnectionParameters(
            host=settings.RABBITMQ_HOST,
            port=settings.RABBITMQ_PORT,
            credentials=credentials,
            socket_timeout=3,
        )
        conn = pika.BlockingConnection(params)
        conn.close()
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(loop.run_in_executor(None, _sync), timeout=3)
        return {"status": "ok", "error": None}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


async def _check_redis() -> dict:
    """检测 Redis 是否可达。"""
    try:
        import redis.asyncio as redis_async
        r = redis_async.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        await asyncio.wait_for(r.ping(), timeout=3)
        await r.aclose()
        return {"status": "ok", "error": None}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


async def _check_milvus() -> dict:
    """检测 Milvus 是否可达。"""
    def _sync():
        from pymilvus import connections
        connections.connect(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT, timeout=3)
        connections.disconnect("default")
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(loop.run_in_executor(None, _sync), timeout=3)
        return {"status": "ok", "error": None}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


async def _check_minio() -> dict:
    """检测 MinIO 是否可达。"""
    def _sync():
        from minio import Minio
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.bucket_exists(settings.MINIO_BUCKET_NAME)
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(loop.run_in_executor(None, _sync), timeout=3)
        return {"status": "ok", "error": None}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


async def _check_llm() -> dict:
    """检测 LLM API 是否可达（供应商无关，跟随 RESOLVED_LLM_* 配置）。"""
    try:
        llm_url = f"{settings.RESOLVED_LLM_API_BASE}/models"
        headers = {}
        if settings.RESOLVED_LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.RESOLVED_LLM_API_KEY}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                llm_url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return {"status": "ok", "error": None}
                return {"status": "unavailable", "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


@router.get("/dependencies")
async def check_dependencies(current_user: User = Depends(get_current_user)):
    """并发检查所有依赖服务的可用性。

    安全最佳实践: 暴露内网服务状态，需认证。
    """
    results = await asyncio.gather(
        _check_http("mcp_monitor", settings.MCP_MONITOR_URL.replace("/mcp", "/health")),
        _check_http("mcp_cls", settings.MCP_CLS_URL.replace("/mcp", "/health")),
        _check_rabbitmq(),
        _check_redis(),
        _check_milvus(),
        _check_minio(),
        _check_llm(),
    )
    names = ["mcp_monitor", "mcp_cls", "rabbitmq", "redis", "milvus", "minio", "llm"]
    services = dict(zip(names, results))
    overall = "ok" if all(s["status"] == "ok" for s in services.values()) else "degraded"
    return {"services": services, "overall": overall}


@router.get("/models")
async def list_models():
    """返回前端模型选择器可用的模型列表。

    从 settings.AVAILABLE_MODELS / MODEL_DISPLAY_NAMES 读取，
    格式: [{"id": "deepseek-v4.1-flash", "name": "DeepSeek-V4.1-Flash"}, ...]
    """
    model_ids = [m.strip() for m in settings.AVAILABLE_MODELS.split(",") if m.strip()]
    display_names = [n.strip() for n in settings.MODEL_DISPLAY_NAMES.split(",")]

    # 补齐：如果 display_names 比 model_ids 少，用 model_id 作 name
    while len(display_names) < len(model_ids):
        display_names.append(model_ids[len(display_names)])

    models = [
        {"id": mid, "name": name}
        for mid, name in zip(model_ids, display_names)
    ]
    return {
        "models": models,
        "default_model": settings.LLM_MODEL,
    }
