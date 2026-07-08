import asyncio

import aiohttp
from fastapi import APIRouter, Depends

from src.settings import settings
from src.worker.celery_app import celery_app
from src.api.dependencies import get_current_user
from src.database.models import User

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


@router.get("/queues")
async def get_queue_stats(current_user: User = Depends(get_current_user)):
    """安全最佳实践: /queues 暴露 Celery 任务详情，需认证。"""
    try:
        i = celery_app.control.inspect()
        if not i:
            return {"error": "Could not connect to Celery inspector"}
            
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
                "scheduled_tasks": total_scheduled
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
    """检测 LLM API 是否可达。"""
    try:
        llm_url = f"{settings.DASHSCOPE_API_BASE}/models"
        headers = {}
        if settings.DASHSCOPE_API_KEY:
            headers["Authorization"] = f"Bearer {settings.DASHSCOPE_API_KEY}"
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
    格式: [{"id": "qwen-max", "name": "Qwen-Max (旗舰)"}, ...]
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
