"""文档相关 Schema"""
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.document import DocumentType, DocParseStatus


class DocumentCreate(BaseModel):
    name: str
    doc_type: DocumentType = DocumentType.OTHER
    project_id: Optional[uuid.UUID] = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    doc_type: DocumentType
    project_id: Optional[uuid.UUID]
    file_size: Optional[int]
    page_count: Optional[int]
    parse_status: DocParseStatus
    created_at: datetime

    class Config:
        from_attributes = True
