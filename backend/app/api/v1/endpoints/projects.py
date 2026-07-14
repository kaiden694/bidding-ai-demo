"""招投标项目端点"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, get_project_scope
from app.core.database import get_db
from app.models.project import Project, ProjectStatus
from app.models.user import User

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    code: Optional[str] = None
    client: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    code: Optional[str]
    client: Optional[str]
    status: ProjectStatus
    industry: Optional[str]

    class Config:
        from_attributes = True


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:create")),
):
    project = Project(**payload.model_dump(), created_by=current_user.id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
    allowed_project_ids: list[uuid.UUID] | None = Depends(get_project_scope),
):
    """项目列表（应用项目级数据隔离）"""
    stmt = select(Project).where(Project.is_deleted == False)
    if allowed_project_ids is not None:
        stmt = stmt.where(
            (Project.created_by == current_user.id) | (Project.id.in_(allowed_project_ids))
        )
    stmt = stmt.order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
):
    project = await db.get(Project, uuid.UUID(project_id))
    if not project:
        raise HTTPException(404, "项目不存在")
    return project
