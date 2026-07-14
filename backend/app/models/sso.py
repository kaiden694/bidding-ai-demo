"""
SSO/OIDC 模型（Phase 3 T5：单点登录对接）

设计要点：
- SSOConfig 存储 OIDC 提供商配置（issuer/client_id/client_secret 等）
- client_secret 在生产环境应加密存储（此处保留明文列以便开发期快速调试）
- UserSSOLink 关联本地用户与 IdP 用户（基于 OIDC sub 字段），一个用户可关联多个 IdP
- (provider_name, sub) 联合唯一，确保同一 IdP 用户只能映射到单个本地用户
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class SSOConfig(Base, UUIDPKMixin, TimestampMixin):
    """SSO/OIDC 提供商配置"""
    __tablename__ = "sso_config"

    # 唯一标识（如 keycloak/azuread）
    provider_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 显示名称（前端展示用）
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # OIDC issuer URL
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(256), nullable=False)
    # 客户端密钥（生产应加密）
    client_secret: Mapped[str] = mapped_column(String(512), nullable=False)
    # 默认 ["openid", "profile", "email"]
    scopes: Mapped[Optional[list]] = mapped_column(JSON)
    # 回调地址
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # OIDC 端点（从 discovery 获取或手动配置）
    authorization_endpoint: Mapped[Optional[str]] = mapped_column(String(512))
    token_endpoint: Mapped[Optional[str]] = mapped_column(String(512))
    userinfo_endpoint: Mapped[Optional[str]] = mapped_column(String(512))

    # 自动创建用户配置
    auto_create_user: Mapped[bool] = mapped_column(Boolean, default=True)
    # 新用户默认角色 code
    default_role_code: Mapped[Optional[str]] = mapped_column(String(64))

    # OIDC discovery 文档缓存
    discovery_cache: Mapped[Optional[dict]] = mapped_column(JSON)
    discovery_cached_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class UserSSOLink(Base, UUIDPKMixin, TimestampMixin):
    """用户-SSO 关联（一个用户可关联多个 IdP）"""
    __tablename__ = "user_sso_link"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # OIDC sub（IdP 中的唯一用户标识）
    sub: Mapped[str] = mapped_column(String(256), nullable=False)

    user = relationship("User")

    __table_args__ = (
        # (provider_name, sub) 联合唯一：同一 IdP 中同一用户只能映射到一个本地用户
        Index("ux_user_sso_link_provider_sub", "provider_name", "sub", unique=True),
    )
