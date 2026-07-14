"""通用知识库 Schema"""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

from app.models.general_knowledge import GeneralDocCategory


class GeneralKnowledgeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: GeneralDocCategory = GeneralDocCategory.OTHER
    source_doc_id: Optional[uuid.UUID] = None
    visibility: str = "all"   # front / back / all
    tags: Optional[List[str]] = None


class GeneralKnowledgeOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    category: GeneralDocCategory
    visibility: str
    tags: Optional[List[str]] = None
    version: str
    is_published: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GeneralSearchRequest(BaseModel):
    query: str
    category: Optional[GeneralDocCategory] = None
    visibility: Optional[str] = None  # 按用户身份过滤
    top_k: int = 5
