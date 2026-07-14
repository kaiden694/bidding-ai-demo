"""协作评论 Schema（Phase 3 T6）"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.comment import CommentEntityType


# ---------- 评论 ----------
class CommentCreate(BaseModel):
    """创建评论"""
    entity_type: CommentEntityType
    entity_id: uuid.UUID
    content: str = Field(..., min_length=1, max_length=10000)
    parent_id: Optional[uuid.UUID] = None


class CommentUpdate(BaseModel):
    """更新评论内容"""
    content: str = Field(..., min_length=1, max_length=10000)


class CommentOut(BaseModel):
    """评论输出（含作者名 + 回复数 + AI 分析结果）"""
    id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    entity_type: CommentEntityType
    entity_id: uuid.UUID
    author_id: uuid.UUID
    author_name: Optional[str] = None  # User.username / full_name
    content: str
    parent_id: Optional[uuid.UUID] = None
    ai_sentiment: Optional[str] = None
    ai_keywords: Optional[list] = None
    replies_count: int = 0  # 一级回复数
    metadata_json: Optional[dict] = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommentListResponse(BaseModel):
    """评论列表响应"""
    items: list[CommentOut]
    total: int


# ---------- @提及 ----------
class MentionOut(BaseModel):
    """@提及记录输出"""
    id: uuid.UUID
    comment_id: uuid.UUID
    mentioned_user_id: uuid.UUID
    is_notified: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- AI 分析 ----------
class CommentAnalyzeResponse(BaseModel):
    """AI 分析评论结果"""
    comment_id: uuid.UUID
    ai_sentiment: Optional[str] = None
    ai_keywords: Optional[list] = None
