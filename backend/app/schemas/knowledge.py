"""知识库 Schema（历史知识库 CRUD + 进度查询 + 标签管理）"""
import uuid
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None  # 标书/合同/经验/范本
    version: str = "1.0"
    is_active: bool = True
    tags: Optional[List[Any]] = None


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[Any]] = None


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    category: Optional[str]
    version: str
    is_active: bool
    tags: Optional[List[Any]] = None
    metadata_json: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeChunkOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: Optional[uuid.UUID]
    title: Optional[str]
    content: str
    category: Optional[str]
    tags: Optional[dict] = None
    page_number: Optional[int]
    chunk_type: Optional[str]
    metadata_json: Optional[dict] = None

    class Config:
        from_attributes = True


class UpdateChunkTagsRequest(BaseModel):
    """更新切块标签（tags 为业务自定义结构，存入 metadata_json.tags）"""
    tags: dict


class FilterChunksRequest(BaseModel):
    tag_key: str
    tag_value: str
    limit: int = 100


class SwitchVersionRequest(BaseModel):
    is_general: bool = False
