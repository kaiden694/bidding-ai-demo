"""合同风险扫描 Schema"""
import uuid
from datetime import date
from typing import Optional, List
from pydantic import BaseModel

from app.models.contract import RiskLevel, ReviewStatus
from app.schemas.common import EvidenceRef


class ContractCreate(BaseModel):
    """创建合同"""
    title: str
    project_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    counterparty: Optional[str] = None
    sign_date: Optional[date] = None
    effective_date: Optional[date] = None
    expire_date: Optional[date] = None
    amount: Optional[float] = None


class ContractOut(BaseModel):
    id: uuid.UUID
    project_id: Optional[uuid.UUID]
    document_id: Optional[uuid.UUID]
    title: str
    counterparty: Optional[str]
    sign_date: Optional[date]
    effective_date: Optional[date]
    expire_date: Optional[date]
    amount: Optional[float]
    review_status: ReviewStatus

    class Config:
        from_attributes = True


class ContractReviewCreate(BaseModel):
    """创建合同审查任务"""
    contract_id: uuid.UUID


class ContractRiskOut(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    rule_code: Optional[str]
    category: Optional[str]
    level: RiskLevel
    title: str
    description: Optional[str]
    suggestion: Optional[str]
    confidence: Optional[float]
    evidence: Optional[List[EvidenceRef]] = None
    is_confirmed: bool

    class Config:
        from_attributes = True
