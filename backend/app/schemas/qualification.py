"""资质台账 Schema"""
import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel

from app.models.qualification import QualificationType


class QualificationCreate(BaseModel):
    name: str
    qual_type: QualificationType = QualificationType.ENTERPRISE
    cert_number: Optional[str] = None
    issuer: Optional[str] = None
    scope: Optional[str] = None
    issue_date: Optional[date] = None
    expire_date: Optional[date] = None
    company_id: Optional[uuid.UUID] = None  # 所属公司（多公司管理）
    owner: Optional[str] = None
    supplier_name: Optional[str] = None
    document_id: Optional[uuid.UUID] = None
    is_valid: bool = True


class QualificationUpdate(BaseModel):
    name: Optional[str] = None
    qual_type: Optional[QualificationType] = None
    cert_number: Optional[str] = None
    issuer: Optional[str] = None
    scope: Optional[str] = None
    issue_date: Optional[date] = None
    expire_date: Optional[date] = None
    company_id: Optional[uuid.UUID] = None  # 所属公司（多公司管理）
    owner: Optional[str] = None
    supplier_name: Optional[str] = None
    document_id: Optional[uuid.UUID] = None
    is_valid: Optional[bool] = None


class QualificationOut(BaseModel):
    id: uuid.UUID
    name: str
    qual_type: QualificationType
    cert_number: Optional[str]
    issuer: Optional[str]
    scope: Optional[str]
    issue_date: Optional[date]
    expire_date: Optional[date]
    company_id: Optional[uuid.UUID] = None     # 所属公司 ID
    company_name: Optional[str] = None          # 公司名称（联表查询后填充）
    company_type: Optional[str] = None          # 公司类型（联表查询后填充）
    owner: Optional[str]
    supplier_name: Optional[str]
    document_id: Optional[uuid.UUID]
    is_valid: bool
    metadata_json: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class QualificationAlertOut(BaseModel):
    """资质预警输出"""
    id: uuid.UUID
    qualification_id: uuid.UUID
    alert_date: date
    expire_date: Optional[date]
    days_remaining: int
    severity: str  # warning / critical / expired
    notified: bool

    class Config:
        from_attributes = True
