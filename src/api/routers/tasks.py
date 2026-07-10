from fastapi import APIRouter, Depends
from celery.result import AsyncResult
from src.worker.celery_app import celery_app
from src.api.dependencies import get_current_user
from src.database.models import User

router = APIRouter()

@router.get("/{task_id}")
def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """安全最佳实践: 需认证才能查询 Celery 任务状态，防止未认证访问。"""
    task_result = AsyncResult(task_id, app=celery_app)
    result = {
        "task_id": task_id,
        "status": task_result.status,
        "result": task_result.result
    }
    return result
