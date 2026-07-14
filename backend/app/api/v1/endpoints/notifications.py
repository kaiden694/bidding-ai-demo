"""站内信端点（Phase 3 T2）

- GET /notifications: 当前用户站内信列表（支持 is_read 过滤）
- GET /notifications/unread-count: 未读数量
- POST /notifications/{id}/read: 标记单条已读
- POST /notifications/read-all: 标记全部已读
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationOut,
)
from app.services.notification_service import get_notification_service

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    is_read: Optional[bool] = Query(None, description="按已读状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notification:view")),
):
    """查询当前用户站内信列表（按时间倒序）"""
    service = get_notification_service()
    items = await service.list_notifications(
        db, current_user.id, is_read=is_read, limit=limit, offset=offset
    )
    unread_count = await service.get_unread_count(db, current_user.id)
    return NotificationListResponse(
        items=[NotificationOut.model_validate(n) for n in items],
        total=len(items),
        unread_count=unread_count,
    )


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notification:view")),
):
    """查询当前用户未读站内信数量"""
    service = get_notification_service()
    count = await service.get_unread_count(db, current_user.id)
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notification:view")),
):
    """标记单条站内信为已读"""
    service = get_notification_service()
    try:
        notif = await service.mark_read(db, notification_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return notif


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notification:view")),
):
    """标记当前用户全部未读站内信为已读"""
    service = get_notification_service()
    updated = await service.mark_all_read(db, current_user.id)
    return {"updated": updated}
