from fastapi import APIRouter
from src.worker.celery_app import celery_app

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

@router.get("/queues")
async def get_queue_stats():
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
