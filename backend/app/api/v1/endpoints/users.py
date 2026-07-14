"""用户管理端点"""
import csv
import io
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import (
    UserCreate, UserUpdate, UserOut, PasswordReset,
)

router = APIRouter()


@router.get("", response_model=list[UserOut], dependencies=[Depends(require_permission("user:view"))])
async def list_users(
    skip: int = 0,
    limit: int = 20,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """用户列表（分页 + 关键词搜索）"""
    stmt = select(User).where(User.is_deleted == False).offset(skip).limit(limit)  # noqa: E712
    if keyword:
        stmt = stmt.where(User.username.ilike(f"%{keyword}%") | User.full_name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(User.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=UserOut, status_code=201, dependencies=[Depends(require_permission("user:create"))])
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """创建用户"""
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        email=payload.email,
        phone=payload.phone,
        full_name=payload.full_name,
        role_id=payload.role_id,
        organization_id=payload.organization_id,
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut, dependencies=[Depends(require_permission("user:view"))])
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    return user


@router.put("/{user_id}", response_model=UserOut, dependencies=[Depends(require_permission("user:update"))])
async def update_user(user_id: uuid.UUID, payload: UserUpdate, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", dependencies=[Depends(require_permission("user:delete"))])
async def disable_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """禁用用户（软删除）"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.is_active = False
    user.is_deleted = True
    await db.commit()
    return {"message": "用户已禁用"}


@router.post("/{user_id}/reset-password", dependencies=[Depends(require_permission("user:reset_password"))])
async def reset_password(user_id: uuid.UUID, payload: PasswordReset, db: AsyncSession = Depends(get_db)):
    """重置密码"""
    user = await db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    user.hashed_password = hash_password(payload.new_password)
    await db.commit()
    return {"message": "密码已重置"}


@router.post("/batch-import", dependencies=[Depends(require_permission("user:create"))])
async def batch_import_users(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """CSV 批量导入用户
    CSV 格式：username,password,email,phone,full_name
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "仅支持 CSV 文件")
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    success, failed = 0, []
    for row in reader:
        try:
            existing = await db.execute(select(User).where(User.username == row["username"]))
            if existing.scalar_one_or_none():
                failed.append({"username": row["username"], "reason": "用户名已存在"})
                continue
            user = User(
                username=row["username"],
                hashed_password=hash_password(row["password"]),
                email=row.get("email"),
                phone=row.get("phone"),
                full_name=row.get("full_name"),
                is_active=True,
                is_admin=False,
            )
            db.add(user)
            success += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"username": row.get("username", "?"), "reason": str(e)})
    await db.commit()
    return {"success": success, "failed": failed}
