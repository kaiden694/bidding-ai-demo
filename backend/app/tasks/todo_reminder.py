"""待办到期提醒 Celery 定时任务（Phase 3 T2）

每日 09:00 扫描待办：
- 状态 IN (pending, in_progress) 且 due_date <= now + 24h 的待办
- 给 assignee 发站内信（todo_due_reminder）
- 若 assignee 有邮箱，发邮件提醒

设计要点：
- 仅做"到期时间"这一确定性事实判断，不进入 LLM 语义层
- 同一待办当日仅提醒一次（按 notification.metadata_json.todo_id + 当日去重）
"""
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, and_

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.notification import (
    Notification,
    NotificationType,
    TodoStatus,
    TodoTask,
)
from app.models.project import Project
from app.models.user import User
from app.services.notification_service import get_notification_service

# 到期前提醒阈值（小时）
_REMIND_HOURS = 24


@celery_app.task(name="todo_reminder.scan_daily", queue="default")
def scan_todo_reminders_daily():
    """每日 09:00 扫描即将到期待办，发送提醒（站内信 + 邮件）"""
    logger.info("[Celery] 开始待办到期提醒扫描")
    try:
        stats = asyncio.run(_scan_async())
        logger.info(f"[Celery] 待办到期提醒扫描完成: {stats}")
        return stats
    except Exception as e:
        logger.error(f"[Celery] 待办到期提醒扫描失败: {e}")
        raise


async def _scan_async() -> dict:
    """异步扫描：查询即将到期待办 → 给 assignee 发站内信 + 邮件"""
    stats = {"total": 0, "reminded": 0, "skipped": 0}
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=_REMIND_HOURS)
    today_str = now.strftime("%Y-%m-%d")

    service = get_notification_service()

    async with AsyncSessionLocal() as session:
        # 查询 pending/in_progress 且 due_date <= now+24h 的待办
        stmt = select(TodoTask).where(
            TodoTask.status.in_([TodoStatus.PENDING, TodoStatus.IN_PROGRESS]),
            TodoTask.due_date.is_not(None),
            TodoTask.due_date <= threshold,
            TodoTask.assignee_id.is_not(None),
        )
        todos = list((await session.execute(stmt)).scalars().all())
        stats["total"] = len(todos)

        for todo in todos:
            # 幂等：同一待办当日仅提醒一次（按当日已有的 todo_due_reminder 通知判断）
            dup_stmt = select(Notification).where(
                and_(
                    Notification.user_id == todo.assignee_id,
                    Notification.type == NotificationType.TODO_DUE_REMINDER,
                    Notification.related_entity_type == "todo",
                    Notification.related_entity_id == todo.id,
                    Notification.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
                )
            )
            existing = (await session.execute(dup_stmt)).scalars().first()
            if existing:
                stats["skipped"] += 1
                continue

            assignee = await session.get(User, todo.assignee_id)
            if assignee is None or not assignee.is_active or assignee.is_deleted:
                stats["skipped"] += 1
                continue

            # 查询关联项目（用于通知标题）
            project_name = ""
            if todo.project_id is not None:
                project = await session.get(Project, todo.project_id)
                if project is not None:
                    project_name = project.name

            due_str = todo.due_date.strftime("%Y-%m-%d %H:%M") if todo.due_date else ""
            title = f"待办即将到期：{todo.title}"
            content = (
                f"待办「{todo.title}」将于 {due_str} 到期。"
                + (f" 所属项目：{project_name}。" if project_name else "")
                + "请尽快处理。"
            )

            # 站内信
            await service.send_notification(
                session,
                user_id=assignee.id,
                type=NotificationType.TODO_DUE_REMINDER,
                title=title,
                content=content,
                related_project_id=todo.project_id,
                related_entity_type="todo",
                related_entity_id=todo.id,
            )

            # 邮件提醒（有邮箱才发）
            if assignee.email:
                await service.send_email(
                    session,
                    to_address=assignee.email,
                    subject=title,
                    body=content,
                    related_entity_type="todo",
                    related_entity_id=todo.id,
                )

            stats["reminded"] += 1
            logger.debug(
                f"待办到期提醒: todo={todo.id} assignee={assignee.username} "
                f"due={due_str} day={today_str}"
            )

    return stats
