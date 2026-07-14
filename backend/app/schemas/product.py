"""产品中心 Schema"""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ProductCategoryCreate(BaseModel):
    name: str
    code: str
    parent_id: Optional[uuid.UUID] = None
    description: Optional[str] = None


class ProductCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    parent_id: Optional[uuid.UUID]
    description: Optional[str]

    class Config:
        from_attributes = True


class SpecItem(BaseModel):
    """技术参数项"""
    name: str
    value: Optional[str] = None
    unit: Optional[str] = None
    tolerance: Optional[str] = None
    remarks: Optional[str] = None


class ProductCreate(BaseModel):
    name: str
    code: Optional[str] = None
    category_id: Optional[uuid.UUID] = None
    company_id: Optional[uuid.UUID] = None  # 所属公司（多公司管理）
    model: Optional[str] = None
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    specs: Optional[List[SpecItem]] = None
    intro_doc_id: Optional[uuid.UUID] = None
    qualification_ids: Optional[List[uuid.UUID]] = None
    test_report_ids: Optional[List[uuid.UUID]] = None


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    code: Optional[str]
    category_id: Optional[uuid.UUID]
    company_id: Optional[uuid.UUID] = None  # 所属公司 ID
    company_name: Optional[str] = None       # 公司名称（联表查询后填充）
    company_type: Optional[str] = None       # 公司类型（联表查询后填充）
    model: Optional[str]
    brand: Optional[str]
    manufacturer: Optional[str]
    description: Optional[str]
    specs: Optional[List[dict]] = None
    is_published: bool
    created_at: datetime

    class Config:
        from_attributes = True
