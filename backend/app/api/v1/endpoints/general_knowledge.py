"""通用知识库端点：企业资料/政策法规上传 + 向量检索

T3.2: 增加 import / reindex / import-status 端点（复用 KnowledgeService）
T3.3: visibility 控制加强（按用户身份过滤）
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import get_rag_retriever
from app.api.deps import require_permission
from app.core.database import get_db
from app.models.general_knowledge import (
    GeneralDocCategory,
    GeneralKnowledgeBase,
)
from app.models.user import User
from app.schemas.general_knowledge import (
    GeneralKnowledgeCreate,
    GeneralKnowledgeOut,
    GeneralSearchRequest,
)
from app.services.knowledge_service import get_knowledge_service

router = APIRouter()


@router.post("", response_model=GeneralKnowledgeOut, status_code=201)
async def create_general_knowledge(
    payload: GeneralKnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:create")),
):
    """创建通用知识库条目（如企业资料、政策法规）"""
    kb = GeneralKnowledgeBase(**payload.model_dump(), created_by=current_user.id)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("", response_model=list[GeneralKnowledgeOut])
async def list_general_knowledge(
    category: Optional[GeneralDocCategory] = None,
    visibility: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:view")),
):
    """通用知识库列表（按用户身份过滤可见范围）

    visibility:
    - admin 用户可看全部
    - 普通用户：仅能看 visibility=all 或与自己身份匹配的（front/back）
    """
    stmt = select(GeneralKnowledgeBase).where(GeneralKnowledgeBase.is_deleted == False)
    if category:
        stmt = stmt.where(GeneralKnowledgeBase.category == category)
    # 非管理员按身份过滤可见范围
    if not current_user.is_admin:
        # 后台管理用户（持有 general_knowledge:view 视为后台身份）
        # 若传入 visibility 参数，仅看 all 与该 visibility
        if visibility:
            stmt = stmt.where(
                GeneralKnowledgeBase.visibility.in_(["all", visibility])
            )
        else:
            stmt = stmt.where(
                GeneralKnowledgeBase.visibility.in_(["all", "back"])
            )
    elif visibility:
        # 管理员显式过滤
        stmt = stmt.where(
            GeneralKnowledgeBase.visibility.in_(["all", visibility])
        )
    stmt = stmt.order_by(GeneralKnowledgeBase.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{kb_id}", response_model=GeneralKnowledgeOut)
async def get_general_knowledge(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:view")),
):
    kb = await db.get(GeneralKnowledgeBase, uuid.UUID(kb_id))
    if not kb or kb.is_deleted:
        raise HTTPException(404, "知识库不存在")
    # 非管理员仅可访问可见的知识库
    if not current_user.is_admin and kb.visibility not in ("all", "back"):
        raise HTTPException(403, "无权访问该知识库")
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_general_knowledge(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:create")),
):
    """软删除（GeneralKnowledgeBase 继承 SoftDeleteMixin）"""
    kb = await db.get(GeneralKnowledgeBase, uuid.UUID(kb_id))
    if not kb or kb.is_deleted:
        raise HTTPException(404, "知识库不存在")
    kb.is_deleted = True
    await db.commit()


@router.post("/search")
async def search_general_knowledge(
    payload: GeneralSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:view")),
):
    """通用知识库语义检索（供前台/后台/AI 助手使用）"""
    retriever = get_rag_retriever()
    results = await retriever.search_knowledge(
        db, query=payload.query, category=payload.category, top_k=payload.top_k
    )
    return {"results": results}


# ============================================================
# 批量导入 / 索引重建 / 进度查询（T3.2，复用 KnowledgeService）
# ============================================================

@router.post("/{kb_id}/import")
async def batch_import(
    kb_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:create")),
):
    """ZIP 批量导入通用知识库文档（解析 → 切块 → 向量化）"""
    try:
        zip_bytes = await file.read()
        if not zip_bytes:
            raise HTTPException(400, "上传文件为空")
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(400, "仅支持 ZIP 文件")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"读取文件失败: {e}")

    service = get_knowledge_service()
    try:
        result = await service.batch_import(
            db,
            uuid.UUID(kb_id),
            zip_bytes,
            is_general=True,
            created_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.post("/{kb_id}/reindex")
async def reindex(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:create")),
):
    """重建通用知识库所有切块的 Embedding"""
    service = get_knowledge_service()
    try:
        result = await service.reindex(db, uuid.UUID(kb_id), is_general=True)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.get("/{kb_id}/import-status")
async def get_import_status(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("general_knowledge:view")),
):
    """查询通用知识库的导入/重建进度"""
    service = get_knowledge_service()
    try:
        return await service.get_import_status(
            db, uuid.UUID(kb_id), is_general=True
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
