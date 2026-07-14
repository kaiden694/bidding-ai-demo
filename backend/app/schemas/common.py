"""通用响应与分页"""
from typing import Generic, TypeVar, Optional, List
from pydantic import BaseModel

T = TypeVar("T")


class ResponseBase(BaseModel):
    """统一响应包装"""
    code: int = 0
    message: str = "ok"
    data: Optional[dict] = None


class PageResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int


class EvidenceRef(BaseModel):
    """证据引用（每条结论绑定）"""
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    content: Optional[str] = None
    page_number: Optional[int] = None
    section: Optional[str] = None
    table_ref: Optional[str] = None
