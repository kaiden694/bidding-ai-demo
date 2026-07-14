"""用户/角色/权限/组织 Schema"""
import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ---------- 用户 ----------
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role_id: Optional[uuid.UUID] = None
    organization_id: Optional[uuid.UUID] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role_id: Optional[uuid.UUID] = None
    organization_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool
    is_admin: bool
    role_id: Optional[uuid.UUID] = None
    organization_id: Optional[uuid.UUID] = None
    created_at: datetime


class UserBatchImport(BaseModel):
    """CSV 批量导入用户（每行一条）"""
    users: List[UserCreate]


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


# ---------- 角色 ----------
class RoleBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    is_system: bool
    created_at: datetime


class RolePermissionsUpdate(BaseModel):
    """角色-权限分配"""
    permission_ids: List[uuid.UUID]


# ---------- 权限 ----------
class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    module: str
    description: Optional[str] = None


class PermissionGrouped(BaseModel):
    """按模块分组的权限"""
    module: str
    permissions: List[PermissionOut]


# ---------- 组织 ----------
class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=64)
    parent_id: Optional[uuid.UUID] = None
    sort_order: int = 0
    description: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None
    sort_order: Optional[int] = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    code: str
    parent_id: Optional[uuid.UUID] = None
    sort_order: int
    created_at: datetime


class OrganizationTreeNode(OrganizationOut):
    """组织树节点（含子节点）"""
    children: List["OrganizationTreeNode"] = []


OrganizationTreeNode.model_rebuild()


# ---------- 认证响应 ----------
class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """登录响应（含权限点）"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    full_name: Optional[str] = None
    is_admin: bool = False
    permissions: List[str] = []


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfoResponse(BaseModel):
    """当前用户信息（含权限点）"""
    user_id: str
    username: str
    full_name: Optional[str] = None
    is_admin: bool
    role_id: Optional[str] = None
    organization_id: Optional[str] = None
    permissions: List[str] = []
