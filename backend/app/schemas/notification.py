"""站内信 + 待办任务 Schema（Phase 3 T2）"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.notification import NotificationType, TodoStatus


# ---------- 站内信 ----------
class NotificationOut(BaseModel):
    """站内信输出"""
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    content: Optional[str] = None
    is_read: bool
    related_project_id: Optional[uuid.UUID] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[uuid.UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """站内信列表（含未读数）"""
    items: list[NotificationOut]
    total: int
    unread_count: int


# ---------- 待办任务 ----------
class TodoTaskCreate(BaseModel):
    """创建/更新待办任务"""
    project_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    status: Optional[TodoStatus] = None
    metadata_json: Optional[dict] = None


class TodoTaskUpdate(BaseModel):
    """更新待办任务（所有字段可选）"""
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    status: Optional[TodoStatus] = None
    metadata_json: Optional[dict] = None


class TodoTaskOut(BaseModel):
    """待办任务输出"""
    id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    status: TodoStatus
    source: str
    metadata_json: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- 待办自动生成规则（admin 查看）----------
class TodoRuleOut(BaseModel):
    """待办规则输出"""
    id: uuid.UUID
    trigger_status: str
    todo_title: str
    todo_description: Optional[str] = None
    assignee_role: Optional[str] = None
    due_days: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
