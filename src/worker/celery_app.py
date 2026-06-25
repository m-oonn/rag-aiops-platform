from celery import Celery
from src.settings import settings

# Initialize Celery
# Broker URL: amqp://user:password@host:port//
broker_url = f"amqp://{settings.RABBITMQ_USER}:{settings.RABBITMQ_PASSWORD}@{settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}//"

celery_app = Celery(
    "rag_worker",
    broker=broker_url,
    backend=settings.REDIS_URL,
    include=["src.worker.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=600,  # 10 minutes timeout per task
    worker_prefetch_multiplier=1, # One task at a time per worker process for fairness
    task_acks_late=True, # Retry if worker crashes
)
