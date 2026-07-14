"""
公司主数据模型

支持产品中心、资质台账的多公司管理场景：
- SELF       本公司（自营产品 / 自有资质）
- PARTNER    合作公司（供应商 / 合作伙伴）
- COMPETITOR 竞品公司
- OTHER      其他

Product 通过 company_id 关联生产厂家；Qualification 通过 company_id 关联持有方。
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Enum, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from app.core.database import Base


class CompanyType(str, enum.Enum):
    """公司类型（确定性分类，用枚举）"""
    SELF = "self"           # 本公司
    PARTNER = "partner"     # 合作公司
    COMPETITOR = "competitor"  # 竞品公司
    OTHER = "other"         # 其他


class Company(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """公司主数据（产品 / 资质共用）

    - 同一公司可被多个产品 / 资质引用
    - company_type 用于快速筛选"自营 / 合作 / 竞品"
    - code 全局唯一，便于外部系统对接
    """
    __tablename__ = "company"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)
    company_type: Mapped[CompanyType] = mapped_column(
        Enum(CompanyType, name="company_type_enum"),
        default=CompanyType.OTHER,
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Company {self.name} ({self.company_type.value})>"
