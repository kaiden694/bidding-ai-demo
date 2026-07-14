"""
通知服务（Phase 3 T2）

职责：
- send_notification: 创建站内信
- send_email: 创建邮件记录 + 异步实际发送（dev 仅记录）
- notify_status_transition: 状态变更通知（给创建者发站内信 + 查 TodoRule 自动生成待办）
- list/mark_read/mark_all_read: 站内信查询与已读管理

设计要点（v1.2 §13 AI 优先）：
- 待办自动生成规则可配置（DB 存储 TodoRule），不硬编码 if-else
- 邮件发送用 asyncio.create_task 包装，不阻塞主流程
- 生产环境接 SMTP，开发环境只记录不发送
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification import (
    EmailLog,
    Notification,
    NotificationType,
    TodoTask,
    TodoStatus,
)
from app.models.project import Project, ProjectStatus
from app.models.todo_rule import TodoRule
from app.models.user import Role, User


class NotificationService:
    """站内信 + 邮件 + 待办 通知服务"""

    # ------------------------------------------------------------------
    # 站内信
    # ------------------------------------------------------------------
    async def send_notification(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        type: NotificationType,
        title: str,
        content: Optional[str] = None,
        related_project_id: Optional[uuid.UUID] = None,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[uuid.UUID] = None,
    ) -> Notification:
        """创建一条站内信"""
        notif = Notification(
            user_id=user_id,
            type=type,
            title=title,
            content=content,
            related_project_id=related_project_id,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)
        return notif

    async def get_unread_count(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        """查询用户未读站内信数量"""
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        return (await db.execute(stmt)).scalar() or 0

    async def list_notifications(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        is_read: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        """查询用户站内信列表（按时间倒序）"""
        stmt = select(Notification).where(Notification.user_id == user_id)
        if is_read is not None:
            stmt = stmt.where(Notification.is_read.is_(is_read))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def mark_read(self, db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
        """标记单条站内信为已读（仅本人）"""
        notif = await db.get(Notification, notification_id)
        if notif is None:
            raise ValueError("通知不存在")
        if notif.user_id != user_id:
            raise ValueError("无权操作他人的通知")
        notif.is_read = True
        await db.commit()
        await db.refresh(notif)
        return notif

    async def mark_all_read(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        """标记当前用户全部未读站内信为已读，返回更新条数"""
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # 邮件
    # ------------------------------------------------------------------
    async def send_email(
        self,
        db: AsyncSession,
        to_address: str,
        subject: str,
        body: Optional[str] = None,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[uuid.UUID] = None,
    ) -> EmailLog:
        """创建邮件记录 + 异步实际发送（不阻塞主流程）

        - 生产环境接 SMTP
        - 开发环境只记录不发送
        - 实际发送用 asyncio.create_task 包装，使用独立 DB 会话
        """
        log = EmailLog(
            to_address=to_address,
            subject=subject,
            body=body,
            status="pending",
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

        # 异步发送（不阻塞主流程）；失败仅记录日志
        try:
            asyncio.create_task(
                _deliver_email(log.id, to_address, subject, body)
            )
        except RuntimeError:
            # 无事件循环时降级为同步记录
            logger.debug("无事件循环，跳过异步邮件发送")
        return log

    # ------------------------------------------------------------------
    # 状态变更通知
    # ------------------------------------------------------------------
    async def notify_status_transition(
        self,
        db: AsyncSession,
        project: Project,
        from_status: ProjectStatus,
        to_status: ProjectStatus,
        user_id: Optional[uuid.UUID],
    ) -> None:
        """状态变更通知：
        1. 给项目创建者发站内信（status_changed）
        2. 查 TodoRule 自动创建待办（todo_created 通知）

        此方法不抛异常（被状态机 try/except 包裹），内部错误仅记录日志。
        """
        try:
            # 1. 给项目创建者发站内信
            if project.created_by is not None:
                await self.send_notification(
                    db,
                    user_id=project.created_by,
                    type=NotificationType.STATUS_CHANGED,
                    title=f"项目状态变更：{project.name}",
                    content=(
                        f"项目「{project.name}」状态由 "
                        f"{from_status.value} 变更为 {to_status.value}。"
                    ),
                    related_project_id=project.id,
                    related_entity_type="project_status_transition",
                )

            # 2. 查 TodoRule 自动生成待办
            await self._create_auto_todos(db, project, to_status)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"状态变更通知发送失败（不阻塞主流程）: {e}")

    async def _create_auto_todos(
        self,
        db: AsyncSession,
        project: Project,
        to_status: ProjectStatus,
    ) -> None:
        """根据 TodoRule 自动生成待办任务（trigger_status == to_status）"""
        trigger = to_status.value
        stmt = select(TodoRule).where(
            TodoRule.trigger_status == trigger,
            TodoRule.is_active.is_(True),
        )
        rules = list((await db.execute(stmt)).scalars().all())
        if not rules:
            return

        now = datetime.now(timezone.utc)
        for rule in rules:
            due_date = (now + timedelta(days=rule.due_days)) if rule.due_days else None
            # 按角色查找候选人
            assignee_id, candidate_user_ids = await self._resolve_assignee(
                db, rule.assignee_role
            )

            todo = TodoTask(
                project_id=project.id,
                title=rule.todo_title,
                description=rule.todo_description,
                assignee_id=assignee_id,
                due_date=due_date,
                status=TodoStatus.PENDING,
                source="auto",
                metadata_json={
                    "trigger_status": trigger,
                    "rule_id": str(rule.id),
                    "assignee_role": rule.assignee_role,
                },
            )
            db.add(todo)
            await db.flush()  # 拿到 todo.id

            # 给候选角色用户发 todo_created 站内信
            for uid in candidate_user_ids:
                await self.send_notification(
                    db,
                    user_id=uid,
                    type=NotificationType.TODO_CREATED,
                    title=f"新待办：{rule.todo_title}",
                    content=(
                        f"项目「{project.name}」进入状态 {trigger}，"
                        f"已自动生成待办：{rule.todo_title}。"
                        + (f" 截止时间：{due_date.isoformat()}" if due_date else "")
                    ),
                    related_project_id=project.id,
                    related_entity_type="todo",
                    related_entity_id=todo.id,
                )
        await db.commit()

    async def _resolve_assignee(
        self, db: AsyncSession, role_code: Optional[str]
    ) -> tuple[Optional[uuid.UUID], list[uuid.UUID]]:
        """按角色 code 查找候选用户

        返回 (assignee_id, [候选用户 id 列表])
        - assignee_id 取首个激活用户（无则 None）
        - 候选列表用于群发站内信
        """
        if not role_code:
            return None, []
        stmt = (
            select(User.id)
            .join(Role, User.role_id == Role.id)
            .where(
                Role.code == role_code,
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
            .order_by(User.created_at)
        )
        user_ids = [row[0] for row in (await db.execute(stmt)).all()]
        assignee_id = user_ids[0] if user_ids else None
        return assignee_id, user_ids


# ------------------------------------------------------------------
# 邮件实际投递（独立会话，避免请求会话关闭）
# ------------------------------------------------------------------
async def _deliver_email(
    email_log_id: uuid.UUID,
    to_address: str,
    subject: str,
    body: Optional[str],
) -> None:
    """后台异步投递邮件

    - 开发环境：只记录不发送，直接标记 sent
    - 生产环境：接 SMTP（如配置了 SMTP_HOST）
    """
    try:
        async with AsyncSessionLocal() as session:
            log = await session.get(EmailLog, email_log_id)
            if log is None:
                return

            # 开发环境只记录不发送
            if settings.APP_ENV != "prod":
                log.status = "sent"
                await session.commit()
                return

            # 生产环境：尝试 SMTP 发送
            smtp_host = getattr(settings, "SMTP_HOST", None)
            if not smtp_host:
                # 未配置 SMTP，降级为仅记录
                log.status = "sent"
                await session.commit()
                return

            await _smtp_send(smtp_host, getattr(settings, "SMTP_PORT", 25), to_address, subject, body)
            log.status = "sent"
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"邮件投递失败 [{to_address}] {subject}: {e}")
        # 失败标记
        try:
            async with AsyncSessionLocal() as session:
                log = await session.get(EmailLog, email_log_id)
                if log is not None:
                    log.status = "failed"
                    log.error = str(e)[:1000]
                    await session.commit()
        except Exception as inner:  # noqa: BLE001
            logger.error(f"邮件失败状态回写异常: {inner}")


async def _smtp_send(host: str, port: int, to_address: str, subject: str, body: Optional[str]) -> None:
    """同步 SMTP 发送（在线程池中执行，避免阻塞事件循环）

    使用 smtplib，发件人从 settings.SMTP_FROM 读取（缺省 noreply）。
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender = getattr(settings, "SMTP_FROM", "noreply@example.com")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_address
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _smtp_send_blocking(host, port, sender, to_address, msg.as_string()),
    )


def _smtp_send_blocking(host: str, port: int, sender: str, to_address: str, raw_msg: str) -> None:
    """阻塞式 SMTP 发送"""
    import smtplib

    with smtplib.SMTP(host, port, timeout=30) as server:
        smtp_user = getattr(settings, "SMTP_USER", None)
        smtp_password = getattr(settings, "SMTP_PASSWORD", None)
        if smtp_user and smtp_password:
            server.starttls()
            server.login(smtp_user, smtp_password)
        server.sendmail(sender, [to_address], raw_msg)


# 单例
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
