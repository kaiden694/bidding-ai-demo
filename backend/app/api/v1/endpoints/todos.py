"""待办任务端点（Phase 3 T2）

路由（与 project_state.py 一致采用全路径，prefix=""）：
- GET /todos: 当前用户待办列表（按 assignee 过滤）
- POST /todos: 创建待办
- PUT /todos/{id}: 更新待办（含状态变更）
- GET /projects/{id}/todos: 项目待办列表
- GET /admin/todo-rules: 查询待办自动生成规则（管理员）
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, require_admin
from app.core.database import get_db
from app.models.notification import TodoStatus, TodoTask
from app.models.project import Project
from app.models.todo_rule import TodoRule
from app.models.user import User
from app.schemas.notification import (
    TodoRuleOut,
    TodoTaskCreate,
    TodoTaskOut,
    TodoTaskUpdate,
)

router = APIRouter()


@router.get("/todos", response_model=list[TodoTaskOut])
async def list_todos(
    status: Optional[TodoStatus] = Query(None, description="按状态过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("todo:view")),
):
    """查询当前用户待办列表（按 assignee 过滤，按到期时间升序）"""
    stmt = select(TodoTask).where(TodoTask.assignee_id == current_user.id)
    if status is not None:
        stmt = stmt.where(TodoTask.status == status)
    stmt = stmt.order_by(TodoTask.due_date.asc().nullslast(), TodoTask.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/todos", response_model=TodoTaskOut, status_code=201)
async def create_todo(
    payload: TodoTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("todo:create")),
):
    """创建待办任务（手动，source=manual）"""
    # 校验项目存在
    if payload.project_id is not None:
        project = await db.get(Project, payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
    todo = TodoTask(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
        status=payload.status or TodoStatus.PENDING,
        source="manual",
        metadata_json=payload.metadata_json,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return todo


@router.put("/todos/{todo_id}", response_model=TodoTaskOut)
async def update_todo(
    todo_id: uuid.UUID,
    payload: TodoTaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("todo:create")),
):
    """更新待办任务（含状态变更）

    管理员可更新任意待办；非管理员仅可更新分配给自己的待办。
    """
    todo = await db.get(TodoTask, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    if not current_user.is_admin and todo.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作他人的待办")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(todo, field, value)
    await db.commit()
    await db.refresh(todo)
    return todo


@router.get("/projects/{project_id}/todos", response_model=list[TodoTaskOut])
async def list_project_todos(
    project_id: uuid.UUID,
    status: Optional[TodoStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("todo:view")),
):
    """查询项目待办列表"""
    # 校验项目存在
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    stmt = select(TodoTask).where(TodoTask.project_id == project_id)
    if status is not None:
        stmt = stmt.where(TodoTask.status == status)
    stmt = stmt.order_by(TodoTask.due_date.asc().nullslast(), TodoTask.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/admin/todo-rules", response_model=list[TodoRuleOut])
async def list_todo_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """查询全部待办自动生成规则（管理员）"""
    stmt = select(TodoRule).order_by(TodoRule.trigger_status)
    result = await db.execute(stmt)
    return list(result.scalars().all())
