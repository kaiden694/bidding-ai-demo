"""
用户与权限模型：组织/用户/角色/权限
Phase 1 仅基础结构，Phase 2 接入 Casbin 策略与组织树
"""
import uuid
from typing import List, Optional

from sqlalchemy import String, Boolean, ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin


# 角色-权限 多对多
role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("role.id"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permission.id"), primary_key=True),
)


class Organization(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """组织（树形结构，自引用）"""
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(default=0)

    parent = relationship("Organization", remote_side="Organization.id", back_populates="children")
    children = relationship("Organization", back_populates="parent", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organization")


class Permission(Base, UUIDPKMixin, TimestampMixin):
    """权限点（如 project:create / contract:review）"""
    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)  # project / contract / qualification...
    description: Mapped[Optional[str]] = mapped_column(String(256))


class Role(Base, UUIDPKMixin, TimestampMixin):
    """角色（售前/法务/采购/项目经理/合规审核/管理员）"""
    __tablename__ = "role"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(256))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[List["Permission"]] = relationship(secondary=role_permission, lazy="selectin")
    users = relationship("User", back_populates="role")


class User(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """用户"""
    __tablename__ = "user"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True)

    role = relationship("Role", back_populates="users", lazy="selectin")
    organization = relationship("Organization", back_populates="users")
