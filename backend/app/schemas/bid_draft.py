"""标书起草辅助 Schema（Phase 3 T4）"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel

from app.models.bid_draft import BidTemplateCategory, BidDraftStatus


# ============================================================
# 模板
# ============================================================

class TemplateVariable(BaseModel):
    """模板变量定义"""
    name: str
    description: Optional[str] = None
    default: Optional[Any] = None


class BidTemplateCreate(BaseModel):
    """创建标书模板"""
    name: str
    category: BidTemplateCategory = BidTemplateCategory.OTHER
    description: Optional[str] = None
    content: str
    variables: Optional[List[TemplateVariable]] = None
    is_active: bool = True
    industry: Optional[str] = None


class BidTemplateUpdate(BaseModel):
    """更新标书模板"""
    name: Optional[str] = None
    category: Optional[BidTemplateCategory] = None
    description: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[TemplateVariable]] = None
    is_active: Optional[bool] = None
    industry: Optional[str] = None


class BidTemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    category: BidTemplateCategory
    description: Optional[str]
    content: str
    variables: Optional[List[TemplateVariable]] = None
    is_active: bool
    industry: Optional[str]
    created_by: Optional[uuid.UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 草稿
# ============================================================

class DraftSection(BaseModel):
    """草稿章节"""
    title: str
    content: str
    ai_generated: bool = False
    source_chunks: Optional[List[Dict[str, Any]]] = None


class BidDraftCreate(BaseModel):
    """创建标书草稿"""
    title: str
    template_id: Optional[uuid.UUID] = None
    sections: Optional[List[DraftSection]] = None
    metadata_json: Optional[Dict[str, Any]] = None


class BidDraftUpdate(BaseModel):
    """更新标书草稿"""
    title: Optional[str] = None
    template_id: Optional[uuid.UUID] = None
    status: Optional[BidDraftStatus] = None
    sections: Optional[List[DraftSection]] = None
    metadata_json: Optional[Dict[str, Any]] = None


class BidDraftOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    template_id: Optional[uuid.UUID]
    title: str
    status: BidDraftStatus
    sections: Optional[List[DraftSection]] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# AI 生成
# ============================================================

class GenerateSectionRequest(BaseModel):
    """AI 生成章节请求"""
    section_title: str
    category: Optional[BidTemplateCategory] = None
    context: Optional[str] = None  # 章节上下文/特殊要求


class GenerateSectionResponse(BaseModel):
    """AI 生成章节响应"""
    content: str
    source_chunks: List[Dict[str, Any]] = []
    confidence: float


# ============================================================
# 模板填充
# ============================================================

class FillTemplateRequest(BaseModel):
    """模板填充请求"""
    template_id: uuid.UUID
    variables: Dict[str, Any] = {}


class FillTemplateResponse(BaseModel):
    """模板填充响应"""
    content: str
    filled_variables: List[str]
    missing_variables: List[str]
