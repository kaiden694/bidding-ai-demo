"""AI 助手 Schema"""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

from app.models.assistant import AssistantScope
from app.schemas.common import EvidenceRef


class ChatRequest(BaseModel):
    """咨询问答请求"""
    question: str
    conversation_id: Optional[str] = None
    scope: AssistantScope = AssistantScope.ALL


class ChatResponse(BaseModel):
    """咨询问答响应"""
    answer: str
    conversation_id: str
    evidence: List[dict] = []


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    scope: AssistantScope
    message_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    evidence: Optional[List[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True
