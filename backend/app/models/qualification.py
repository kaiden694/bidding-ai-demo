"""
资质台账模型（企业证书 + 供应商资质）
"""
import enum
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import String, Text, Date, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from app.core.database import Base


class QualificationType(str, enum.Enum):
    """资质类型"""
    ENTERPRISE = "enterprise"        # 企业资质
    SUPPLIER = "supplier"            # 供应商资质
    PRODUCT = "product"              # 产品认证
    PERSONNEL = "personnel"          # 人员资质


class Qualification(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """资质台账"""
    __tablename__ = "qualification"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    qual_type: Mapped[QualificationType] = mapped_column(
        Enum(QualificationType, name="qualification_type"), default=QualificationType.ENTERPRISE, index=True
    )
    cert_number: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    issuer: Mapped[Optional[str]] = mapped_column(String(128))  # 发证机构
    scope: Mapped[Optional[str]] = mapped_column(Text)  # 资质范围
    issue_date: Mapped[Optional[date]] = mapped_column(Date)
    expire_date: Mapped[Optional[date]] = mapped_column(Date, index=True)  # 预警依据
    # 所属公司（多公司管理：自营/合作/竞品）
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id"), index=True, nullable=True
    )
    owner: Mapped[Optional[str]] = mapped_column(String(128))  # 持有方（保留兼容）
    supplier_name: Mapped[Optional[str]] = mapped_column(String(128), index=True)  # 供应商资质时使用（保留兼容）
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    company = relationship("Company", lazy="selectin")
