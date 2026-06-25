from fastapi import APIRouter, Depends
from celery.result import AsyncResult
from src.worker.celery_app import celery_app

router = APIRouter()

@router.get("/{task_id}")
def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery_app)
    result = {
        "task_id": task_id,
        "status": task_result.status,
        "result": task_result.result
    }
    return result
