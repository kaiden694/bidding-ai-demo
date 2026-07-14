"""标书起草辅助端点（Phase 3 T4）

路由设计：
- /bid-templates: 模板 CRUD
- /bid-templates/{id}/fill: 模板变量填充
- /projects/{id}/bid-draft: 草稿 CRUD（按项目维度）
- /projects/{id}/bid-draft/generate: AI 生成章节
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.bid_draft import BidTemplateCategory
from app.models.user import User
from app.schemas.bid_draft import (
    BidDraftCreate,
    BidDraftOut,
    BidDraftUpdate,
    BidTemplateCreate,
    BidTemplateOut,
    BidTemplateUpdate,
    FillTemplateRequest,
    FillTemplateResponse,
    GenerateSectionRequest,
    GenerateSectionResponse,
)
from app.services.bid_draft_service import get_bid_draft_service

router = APIRouter()


# ============================================================
# 标书模板
# ============================================================

@router.get(
    "/bid-templates",
    response_model=list[BidTemplateOut],
)
async def list_bid_templates(
    category: Optional[BidTemplateCategory] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:view")),
):
    """标书模板列表（支持按分类/启用状态过滤）"""
    service = get_bid_draft_service()
    return await service.list_templates(db, category=category, is_active=is_active)


@router.post(
    "/bid-templates",
    response_model=BidTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bid_template(
    payload: BidTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """创建标书模板"""
    service = get_bid_draft_service()
    data = payload.model_dump(exclude_unset=True)
    # 将 variables 中的对象转为 dict 便于 JSON 存储
    if data.get("variables") is not None:
        data["variables"] = [v.model_dump() if hasattr(v, "model_dump") else v for v in data["variables"]]
    return await service.create_template(db, data, current_user.id)


@router.get(
    "/bid-templates/{template_id}",
    response_model=BidTemplateOut,
)
async def get_bid_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:view")),
):
    """获取标书模板详情"""
    service = get_bid_draft_service()
    try:
        return await service.get_template(db, template_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put(
    "/bid-templates/{template_id}",
    response_model=BidTemplateOut,
)
async def update_bid_template(
    template_id: uuid.UUID,
    payload: BidTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """更新标书模板"""
    service = get_bid_draft_service()
    data = payload.model_dump(exclude_unset=True)
    if data.get("variables") is not None:
        data["variables"] = [v.model_dump() if hasattr(v, "model_dump") else v for v in data["variables"]]
    try:
        return await service.update_template(db, template_id, data)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete(
    "/bid-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_bid_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """软删除标书模板"""
    service = get_bid_draft_service()
    try:
        await service.delete_template(db, template_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post(
    "/bid-templates/{template_id}/fill",
    response_model=FillTemplateResponse,
)
async def fill_bid_template(
    template_id: uuid.UUID,
    payload: FillTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:view")),
):
    """填充标书模板变量

    body.variables 为 {变量名: 值}，缺失变量保留原占位符 {variable}。
    """
    service = get_bid_draft_service()
    try:
        return await service.fill_template(db, template_id, payload.variables)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# 标书草稿（按项目维度）
# ============================================================

@router.get(
    "/projects/{project_id}/bid-draft",
    response_model=Optional[BidDraftOut],
)
async def get_project_bid_draft(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:view")),
):
    """获取项目最新标书草稿（不存在则返回 null）"""
    service = get_bid_draft_service()
    return await service.get_draft(db, project_id)


@router.post(
    "/projects/{project_id}/bid-draft",
    response_model=BidDraftOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_bid_draft(
    project_id: uuid.UUID,
    payload: BidDraftCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """创建项目标书草稿"""
    service = get_bid_draft_service()
    sections = (
        [s.model_dump() for s in payload.sections] if payload.sections else None
    )
    try:
        return await service.create_draft(
            db,
            project_id=project_id,
            title=payload.title,
            template_id=payload.template_id,
            user_id=current_user.id,
            sections=sections,
            metadata_json=payload.metadata_json,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put(
    "/projects/{project_id}/bid-draft",
    response_model=BidDraftOut,
)
async def update_project_bid_draft(
    project_id: uuid.UUID,
    payload: BidDraftUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """更新项目最新标书草稿（不存在则 404）"""
    service = get_bid_draft_service()
    draft = await service.get_draft(db, project_id)
    if draft is None:
        raise HTTPException(404, "项目尚无标书草稿")
    data = payload.model_dump(exclude_unset=True)
    if data.get("sections") is not None:
        data["sections"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in data["sections"]]
    return await service.update_draft(db, draft.id, data)


# ============================================================
# AI 生成章节
# ============================================================

@router.post(
    "/projects/{project_id}/bid-draft/generate",
    response_model=GenerateSectionResponse,
)
async def generate_bid_section(
    project_id: uuid.UUID,
    payload: GenerateSectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("bid:create")),
):
    """AI 生成标书章节

    流程：RAG 召回历史标书片段 → LLM 生成 → 返回内容 + 证据链 + 置信度。
    """
    service = get_bid_draft_service()
    try:
        return await service.generate_section(
            db,
            project_id=project_id,
            section_title=payload.section_title,
            category=payload.category,
            context=payload.context,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
