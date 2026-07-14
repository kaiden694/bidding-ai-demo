"""
Celery 应用：异步任务（文档解析 / LLM 调用 / 批量处理 / 资质预警）
队列划分: default / parsing / llm
"""
from celery import Celery
from celery.schedules import crontab, schedule

from app.core.config import settings

celery_app = Celery(
    "sbaw",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.parsing",
        "app.tasks.llm",
        "app.tasks.comparison_task",
        "app.tasks.contract_review_task",
        "app.tasks.qualification_alert",
        "app.tasks.llm_health_check",
        "app.tasks.todo_reminder",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "parsing": {"exchange": "parsing", "routing_key": "parsing"},
        "llm": {"exchange": "llm", "routing_key": "llm"},
    },
    task_default_queue="default",
    worker_prefetch_multiplier=1,
    # 定时任务（Celery Beat）：
    # - 资质预警：每日 09:00 扫描
    # - 待办到期提醒：每日 09:00 扫描（到期前 24h）
    # - LLM 健康检查：每 60s 并发 ping 所有 provider
    beat_schedule={
        "qualification-alert-daily": {
            "task": "qualification_alert.scan_daily",
            "schedule": crontab(hour=9, minute=0),
        },
        "todo-reminder-daily": {
            "task": "todo_reminder.scan_daily",
            "schedule": crontab(hour=9, minute=0),
        },
        "llm-health-check": {
            "task": "llm_health_check.scan",
            "schedule": schedule(run_every=60),
        },
    },
)
