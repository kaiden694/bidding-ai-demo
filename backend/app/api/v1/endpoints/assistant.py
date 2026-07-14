"""AI 助手端点：前台/后台用户共用咨询问答"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.assistant import AssistantConversation, AssistantMessage, AssistantScope
from app.models.user import User
from app.schemas.assistant import ChatRequest, ChatResponse, ConversationOut, MessageOut
from app.services.assistant_service import get_assistant_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("assistant:chat")),
):
    """咨询问答（前台/后台共用，通过 scope 区分检索范围）"""
    service = get_assistant_service()
    result = await service.chat(
        session=db,
        conversation_id=payload.conversation_id,
        question=payload.question,
        scope=payload.scope,
        user_id=current_user.id,
    )
    return result


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    scope: Optional[AssistantScope] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("assistant:view_history")),
):
    """会话列表（用户只看自己的会话；管理员看全部）"""
    stmt = select(AssistantConversation).where(AssistantConversation.is_deleted == False)
    # 非管理员仅能查看自己的会话
    if not current_user.is_admin:
        stmt = stmt.where(AssistantConversation.user_id == current_user.id)
    if scope:
        stmt = stmt.where(AssistantConversation.scope == scope)
    stmt = stmt.order_by(AssistantConversation.updated_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("assistant:view_history")),
):
    """会话消息历史"""
    # 校验会话可见性（非管理员仅可访问自己的会话）
    conv = await db.get(AssistantConversation, uuid.UUID(conversation_id))
    if not conv:
        raise HTTPException(404, "会话不存在")
    if not current_user.is_admin and conv.user_id != current_user.id:
        raise HTTPException(403, "无权访问该会话")
    stmt = (
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == uuid.UUID(conversation_id))
        .order_by(AssistantMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()
