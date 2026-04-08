#celery_app.py
from celery import Celery
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "marketscope",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.analysis_tasks"  # Явно указываем модуль с задачами
    ]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=120,
    task_soft_time_limit=100,
    # Логирование
    worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
    worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s",
    # Production настройки
    task_track_started=True,
    result_expires=3600,  # Результаты хранятся 1 час
)


# Health check task
@celery_app.task(name="celery.health_check")
def health_check():
    """Health check task for monitoring."""
    return {"status": "healthy"}