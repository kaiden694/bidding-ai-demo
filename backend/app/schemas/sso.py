"""SSO/OIDC Schema（Phase 3 T5）"""
import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ---------- client_secret 脱敏 ----------
def _mask_secret(value: str) -> str:
    """脱敏 client_secret：仅保留前 4 与后 4 位，中间用 **** 替代"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


# ---------- SSO 配置 CRUD ----------
class SSOConfigCreate(BaseModel):
    """创建 SSO 配置"""
    provider_name: str = Field(..., min_length=1, max_length=64, description="唯一标识")
    display_name: str = Field(..., min_length=1, max_length=128)
    issuer: str = Field(..., min_length=1, max_length=512)
    client_id: str = Field(..., min_length=1, max_length=256)
    client_secret: str = Field(..., min_length=1, max_length=512)
    scopes: Optional[List[str]] = Field(default=None, description="默认 [openid, profile, email]")
    redirect_uri: str = Field(..., min_length=1, max_length=512)
    is_active: bool = True
    # OIDC 端点（可选；不填则自动 discovery）
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    auto_create_user: bool = True
    default_role_code: Optional[str] = Field(None, max_length=64)


class SSOConfigUpdate(BaseModel):
    """更新 SSO 配置（部分字段）"""
    display_name: Optional[str] = Field(None, max_length=128)
    issuer: Optional[str] = Field(None, max_length=512)
    client_id: Optional[str] = Field(None, max_length=256)
    client_secret: Optional[str] = Field(None, max_length=512)
    scopes: Optional[List[str]] = None
    redirect_uri: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    auto_create_user: Optional[bool] = None
    default_role_code: Optional[str] = Field(None, max_length=64)


class SSOConfigOut(BaseModel):
    """SSO 配置输出（client_secret 脱敏）"""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    provider_name: str
    display_name: str
    issuer: str
    client_id: str
    client_secret: str  # 脱敏后输出
    scopes: Optional[List[str]] = None
    redirect_uri: str
    is_active: bool
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    auto_create_user: bool
    default_role_code: Optional[str] = None
    discovery_cached_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_serializer("client_secret")
    def _serialize_client_secret(self, value: str) -> str:
        return _mask_secret(value) if value else value


class SSOProviderPublic(BaseModel):
    """SSO 提供商公开信息（无需认证可访问）"""
    provider_name: str
    display_name: str


# ---------- SSO 登录流程 ----------
class SSOLoginResponse(BaseModel):
    """SSO 登录响应：返回 IdP authorization URL"""
    authorization_url: str
    state: str
    provider_name: str


class SSOCallbackRequest(BaseModel):
    """OIDC 回调请求（code + state）"""
    code: str
    state: str
    provider_name: Optional[str] = None  # 可选：若 state 不含 provider 则需提供


# ---------- SSO Token 响应 ----------
class SSOTokenResponse(BaseModel):
    """SSO 登录成功响应（与本地 /auth/login 一致）"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    full_name: Optional[str] = None
    is_admin: bool = False
    permissions: List[str] = []


# ---------- 手动 discovery 结果 ----------
class SSODiscoverResult(BaseModel):
    """手动触发 OIDC discovery 结果"""
    provider_name: str
    issuer: str
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    success: bool
    error: Optional[str] = None
