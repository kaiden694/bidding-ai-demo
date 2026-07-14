"""
产品中心模型
- 产品分类（树形）
- 产品（含技术参数表 + 向量库 + 关联资质 + 检测报告）
- 可作为参数偏离比对的产品选型来源
"""
import enum
import uuid
from typing import Optional, List

from sqlalchemy import String, Text, ForeignKey, Enum, JSON, Float, Boolean, Integer, Table, Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from pgvector.sqlalchemy import Vector
from app.core.config import settings


# 产品-资质 多对多
product_qualification = Table(
    "product_qualification",
    Base.metadata,
    Column("product_id", UUID(as_uuid=True), ForeignKey("product.id"), primary_key=True),
    Column("qualification_id", UUID(as_uuid=True), ForeignKey("qualification.id"), primary_key=True),
)


# 产品-检测报告 多对多
product_test_report = Table(
    "product_test_report",
    Base.metadata,
    Column("product_id", UUID(as_uuid=True), ForeignKey("product.id"), primary_key=True),
    Column("document_id", UUID(as_uuid=True), ForeignKey("document.id"), primary_key=True),
)


class ProductCategory(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """产品分类（树形结构）"""
    __tablename__ = "product_category"

    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_category.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)

    parent = relationship("ProductCategory", remote_side="ProductCategory.id", back_populates="children")
    children = relationship("ProductCategory", back_populates="parent", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="category")


class Product(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """企业产品
    - 技术参数表（JSON）可作为参数偏离比对的选型来源
    - 切块向量化入库，支持产品检索
    - 关联企业资质证书与检测报告
    """
    __tablename__ = "product"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_category.id"), index=True
    )
    # 所属公司（多公司管理：自营/合作/竞品）
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id"), index=True, nullable=True
    )
    model: Mapped[Optional[str]] = mapped_column(String(128))              # 产品型号
    brand: Mapped[Optional[str]] = mapped_column(String(128))               # 品牌
    manufacturer: Mapped[Optional[str]] = mapped_column(String(256))        # 生产厂家（保留兼容）
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 技术参数表：[{name, value, unit, tolerance, remarks}]
    specs: Mapped[Optional[List[dict]]] = mapped_column(JSON)
    # 产品资料文档 ID（说明书/白皮书等）
    intro_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # 是否上架
    sort_order: Mapped[int] = mapped_column(default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    category = relationship("ProductCategory", back_populates="products", lazy="selectin")
    company = relationship("Company", lazy="selectin")
    qualifications = relationship("Qualification", secondary=product_qualification, lazy="selectin")
    test_reports = relationship("Document", secondary=product_test_report, lazy="selectin")
    chunks = relationship("ProductChunk", back_populates="product", cascade="all, delete-orphan")


class ProductChunk(Base, UUIDPKMixin, TimestampMixin):
    """产品资料切块（向量化，支持产品技术资料语义检索）"""
    __tablename__ = "product_chunk"

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product.id"), nullable=False, index=True)
    source_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(256))
    table_ref: Mapped[Optional[str]] = mapped_column(String(128))
    chunk_type: Mapped[Optional[str]] = mapped_column(String(32))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # 向量列
    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBEDDING_DIM))

    product = relationship("Product", back_populates="chunks")
