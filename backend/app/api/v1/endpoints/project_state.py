"""项目状态机端点（Phase 3 T1）

- POST /projects/{id}/transition: 状态流转
- GET /projects/{id}/transitions: 状态变更历史
- GET /projects/{id}/next-statuses: 允许的下一状态
- GET /projects/{id}/recommend-next-status: AI 辅助推荐下一状态
- GET /admin/status-rules: 查询全部状态规则
- PUT /admin/status-rules: 批量更新状态规则（管理员）
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.project_state import (
    NextStatusesResponse,
    RecommendNextStatusResponse,
    StatusRuleOut,
    StatusRuleUpdate,
    TransitionOut,
    TransitionRequest,
)
from app.services.project_state_machine import get_project_state_machine

router = APIRouter()


@router.post(
    "/projects/{project_id}/transition",
    response_model=TransitionOut,
)
async def transition_project(
    project_id: uuid.UUID,
    payload: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:transition")),
):
    """流转项目状态

    - 硬规则校验：必须在 ProjectStatusRule 矩阵中
    - 失败抛 400（含可用下一状态列表）
    - 落审计记录（transition_by = 当前用户）
    """
    service = get_project_state_machine()
    try:
        record = await service.transition(
            db,
            project_id=project_id,
            to_status=payload.to_status,
            user_id=current_user.id,
            reason=payload.reason,
            ai_suggestion=payload.ai_suggestion,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return record


@router.get(
    "/projects/{project_id}/transitions",
    response_model=list[TransitionOut],
)
async def list_transitions(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
):
    """查询项目状态变更历史（按时间倒序）"""
    service = get_project_state_machine()
    return await service.get_transition_history(db, project_id)


@router.get(
    "/projects/{project_id}/next-statuses",
    response_model=NextStatusesResponse,
)
async def get_next_statuses(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
):
    """查询项目当前状态允许的下一状态"""
    service = get_project_state_machine()
    try:
        next_statuses = await service.get_next_statuses(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # 查询当前状态
    from app.models.project import Project
    project = await db.get(Project, project_id)
    return NextStatusesResponse(
        current_status=project.status,
        next_statuses=next_statuses,
    )


@router.get(
    "/projects/{project_id}/recommend-next-status",
    response_model=RecommendNextStatusResponse,
)
async def recommend_next_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
):
    """AI 辅助推荐下一状态（非强制，可降级返回 null）"""
    service = get_project_state_machine()
    try:
        result = await service.recommend_next_status(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.get(
    "/admin/status-rules",
    response_model=list[StatusRuleOut],
)
async def list_status_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:view")),
):
    """查询全部状态转移规则"""
    service = get_project_state_machine()
    return await service.list_rules(db)


@router.put(
    "/admin/status-rules",
    response_model=list[StatusRuleOut],
)
async def update_status_rules(
    payload: StatusRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project:manage_rules")),
):
    """批量更新状态转移规则（管理员）

    - upsert：已存在的规则更新 is_active/description，不存在的规则新增
    - 返回更新后的全部规则
    """
    service = get_project_state_machine()
    rules = [r.model_dump() for r in payload.rules]
    return await service.upsert_rules(db, rules)
