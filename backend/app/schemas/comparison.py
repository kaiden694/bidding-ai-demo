"""参数偏离比对 Schema"""
import uuid
from typing import Optional, List
from pydantic import BaseModel

from app.models.comparison import ComparisonVerdict
from app.schemas.common import EvidenceRef


class ComparisonCreate(BaseModel):
    """创建比对任务
    - 方式 A: tender_doc_id + spec_doc_id（招标文件 vs 规格书文档）
    - 方式 B: tender_doc_id + product_id（招标文件 vs 产品中心选型产品 specs）
    二选一即可
    """
    project_id: Optional[uuid.UUID] = None
    tender_doc_id: uuid.UUID
    spec_doc_id: Optional[uuid.UUID] = None
    product_id: Optional[uuid.UUID] = None   # 产品选型：直接用产品 specs 作为响应方


class ComparisonResultOut(BaseModel):
    id: uuid.UUID
    param_name: str
    tender_value: Optional[str]
    spec_value: Optional[str]
    verdict: ComparisonVerdict
    confidence: Optional[float]
    reason: Optional[str]
    tender_evidence: Optional[List[EvidenceRef]] = None
    spec_evidence: Optional[List[EvidenceRef]] = None

    class Config:
        from_attributes = True


class ComparisonTaskOut(BaseModel):
    id: uuid.UUID
    project_id: Optional[uuid.UUID]
    tender_doc_id: Optional[uuid.UUID]
    spec_doc_id: Optional[uuid.UUID]
    product_id: Optional[uuid.UUID] = None
    status: str
    progress: Optional[float]
    summary: Optional[dict]

    class Config:
        from_attributes = True
