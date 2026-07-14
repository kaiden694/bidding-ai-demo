"""知识库端点（历史知识库 + 通用知识库共用 KnowledgeService）

T3.2: 批量导入 / 索引重建 / 进度查询 / 版本切换 / 标签管理
T3.3: KnowledgeChunk 标签管理 + 按 tag 筛选切块
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import get_rag_retriever
from app.api.deps import require_permission
from app.core.database import get_db
from app.models.document import KnowledgeBase, KnowledgeChunk
from app.models.general_knowledge import GeneralKnowledgeChunk
from app.models.user import User
from app.schemas.knowledge import (
    FilterChunksRequest,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    KnowledgeChunkOut,
    SwitchVersionRequest,
    UpdateChunkTagsRequest,
)
from app.services.knowledge_service import get_knowledge_service

router = APIRouter()


# ============================================================
# 历史知识库 CRUD
# ============================================================

@router.post("/bases", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """创建历史知识库条目（标书/合同/经验/范本）"""
    kb = KnowledgeBase(**payload.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("/bases", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    """历史知识库列表（支持按 category / is_active 过滤）"""
    stmt = select(KnowledgeBase).where(KnowledgeBase.is_deleted == False)
    if category:
        stmt = stmt.where(KnowledgeBase.category == category)
    if is_active is not None:
        stmt = stmt.where(KnowledgeBase.is_active == is_active)
    stmt = stmt.order_by(KnowledgeBase.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/bases/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    kb = await db.get(KnowledgeBase, uuid.UUID(kb_id))
    if not kb or kb.is_deleted:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.patch("/bases/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    kb = await db.get(KnowledgeBase, uuid.UUID(kb_id))
    if not kb or kb.is_deleted:
        raise HTTPException(404, "知识库不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(kb, k, v)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete("/bases/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """软删除知识库（KnowledgeBase 继承 SoftDeleteMixin）"""
    kb = await db.get(KnowledgeBase, uuid.UUID(kb_id))
    if not kb or kb.is_deleted:
        raise HTTPException(404, "知识库不存在")
    kb.is_deleted = True
    await db.commit()


# ============================================================
# 批量导入 / 索引重建 / 进度查询（T3.2）
# ============================================================

@router.post("/bases/{kb_id}/import")
async def batch_import(
    kb_id: str,
    file: UploadFile = File(...),
    is_general: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """ZIP 批量导入知识库文档（解析 → 切块 → 向量化）

    - file: ZIP 文件
    - is_general: 是否导入到通用知识库（默认 False，即历史知识库）
    """
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
            is_general=is_general,
            created_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        # T15.4 配额超限 → 409 Conflict
        from app.services.vector_quota_service import VectorQuotaError
        if isinstance(e, VectorQuotaError):
            raise HTTPException(409, detail=e.to_dict())
        raise
    return result


@router.post("/bases/{kb_id}/reindex")
async def reindex(
    kb_id: str,
    is_general: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """重建知识库所有切块的 Embedding"""
    service = get_knowledge_service()
    try:
        result = await service.reindex(db, uuid.UUID(kb_id), is_general=is_general)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.get("/bases/{kb_id}/import-status")
async def get_import_status(
    kb_id: str,
    is_general: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    """查询知识库的导入/重建进度"""
    service = get_knowledge_service()
    try:
        return await service.get_import_status(
            db, uuid.UUID(kb_id), is_general=is_general
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/bases/{kb_id}/switch-version")
async def switch_version(
    kb_id: str,
    payload: SwitchVersionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """版本切换：将目标知识库设为 active，同 name 的其他版本置为 inactive"""
    service = get_knowledge_service()
    try:
        return await service.switch_version(
            db, uuid.UUID(kb_id), is_general=payload.is_general
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# 切块标签管理（T3.3）
# ============================================================

@router.patch("/chunks/{chunk_id}/tags", response_model=KnowledgeChunkOut)
async def update_chunk_tags(
    chunk_id: str,
    payload: UpdateChunkTagsRequest,
    is_general: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:create")),
):
    """更新切块标签（标签存储在 metadata_json.tags，业务自定义结构）"""
    service = get_knowledge_service()
    try:
        return await service.update_chunk_tags(
            db, uuid.UUID(chunk_id), payload.tags, is_general=is_general
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/bases/{kb_id}/chunks/filter")
async def filter_chunks(
    kb_id: str,
    payload: FilterChunksRequest,
    is_general: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    """按标签筛选切块（tag_key + tag_value 精确匹配 metadata_json）"""
    service = get_knowledge_service()
    try:
        chunks = await service.filter_chunks_by_tag(
            db,
            uuid.UUID(kb_id),
            payload.tag_key,
            payload.tag_value,
            is_general=is_general,
            limit=payload.limit,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"items": [_chunk_brief(c) for c in chunks]}


@router.get("/bases/{kb_id}/chunks", response_model=list[KnowledgeChunkOut])
async def list_chunks(
    kb_id: str,
    is_general: bool = False,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    """列出知识库切块（基础列表，标签筛选走 /chunks/filter）"""
    Model = GeneralKnowledgeChunk if is_general else KnowledgeChunk
    # GeneralKnowledgeChunk 有 chunk_index，KnowledgeChunk 无 → 用 created_at 兜底排序
    order_col = getattr(Model, "chunk_index", None) or Model.created_at
    stmt = (
        select(Model)
        .where(Model.knowledge_base_id == uuid.UUID(kb_id))
        .order_by(order_col)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ============================================================
# 语义检索（保留 Phase 1 接口）
# ============================================================

class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    top_k: int = 5


@router.post("/search")
async def search_knowledge(
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:view")),
):
    """语义检索知识库（返回带证据的可定位结果）"""
    retriever = get_rag_retriever()
    results = await retriever.search_knowledge(
        db, query=payload.query, category=payload.category, top_k=payload.top_k
    )
    return {"results": results}


# ============================================================
# 辅助
# ============================================================

def _chunk_brief(chunk) -> dict:
    """切块简要信息（用于标签筛选返回）"""
    return {
        "id": str(chunk.id),
        "chunk_index": getattr(chunk, "chunk_index", None),
        "title": getattr(chunk, "title", None),
        "content": (chunk.content or "")[:200],
        "page_number": getattr(chunk, "page_number", None),
        "section": getattr(chunk, "section", None),
        "metadata_json": chunk.metadata_json,
    }
