"""公司主数据 Schema"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.company import CompanyType


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256, description="公司名称")
    short_name: Optional[str] = Field(None, max_length=128, description="简称")
    code: Optional[str] = Field(None, max_length=64, description="唯一编码")
    company_type: CompanyType = Field(CompanyType.OTHER, description="公司类型")
    description: Optional[str] = None
    metadata_json: Optional[dict] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("公司名称不能为空")
        return v.strip()


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    short_name: Optional[str] = Field(None, max_length=128)
    code: Optional[str] = Field(None, max_length=64)
    company_type: Optional[CompanyType] = None
    description: Optional[str] = None
    metadata_json: Optional[dict] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("公司名称不能为空")
        return v.strip() if v is not None else v


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    short_name: Optional[str]
    code: Optional[str]
    company_type: CompanyType
    company_type_label: Optional[str] = None  # 前端友好的中文标签
    description: Optional[str]
    metadata_json: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CompanyBriefOut(BaseModel):
    """精简版（用于下拉选择器）"""
    id: uuid.UUID
    name: str
    short_name: Optional[str] = None
    company_type: CompanyType

    class Config:
        from_attributes = True
