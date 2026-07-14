"""协作评论端点（Phase 3 T6）

路由（采用全路径，prefix=""，与 todos.py 一致）：
- GET  /projects/{id}/comments: 项目评论列表（支持 entity_type/entity_id 过滤）
- POST /projects/{id}/comments: 创建评论（含 @提及 + AI 分析）
- DELETE /comments/{id}: 软删除评论（作者或 admin）
- POST /comments/{id}/analyze: 触发 AI 分析评论情感 + 关键问题
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.comment import Comment, CommentEntityType
from app.models.project import Project
from app.models.user import User
from app.schemas.comment import (
    CommentAnalyzeResponse,
    CommentCreate,
    CommentListResponse,
    CommentOut,
)
from app.services.comment_service import get_comment_service

router = APIRouter()


# ============================================================
# 辅助：批量构建 CommentOut（author_name + replies_count）
# ============================================================
async def _enrich_comments(
    db: AsyncSession, comments: list[Comment]
) -> list[CommentOut]:
    """批量加载作者名 + 一级回复数，构造 CommentOut 列表"""
    if not comments:
        return []

    # 收集所有需要查询的评论（含 replies 已挂载的一级回复）
    all_comments: list[Comment] = list(comments)
    for c in comments:
        # list_by_entity 已挂载 replies；list_comments 没有
        replies = getattr(c, "replies", None) or []
        all_comments.extend(replies)

    comment_ids = [c.id for c in all_comments]
    author_ids = list({c.author_id for c in all_comments})

    # 1. 作者名（username / full_name）
    author_map: dict[uuid.UUID, str] = {}
    if author_ids:
        stmt = select(User.id, User.username, User.full_name).where(
            User.id.in_(author_ids)
        )
        for uid, username, full_name in (await db.execute(stmt)).all():
            author_map[uid] = full_name or username

    # 2. 一级回复数（仅对有评论的 id 统计）
    replies_count_map: dict[uuid.UUID, int] = {}
    if comment_ids:
        stmt = (
            select(Comment.parent_id, func.count(Comment.id))
            .where(
                Comment.parent_id.in_(comment_ids),
                Comment.is_deleted.is_(False),
            )
            .group_by(Comment.parent_id)
        )
        for pid, cnt in (await db.execute(stmt)).all():
            replies_count_map[pid] = int(cnt or 0)

    def to_out(c: Comment) -> CommentOut:
        out = CommentOut.model_validate(c)
        out.author_name = author_map.get(c.author_id)
        out.replies_count = replies_count_map.get(c.id, 0)
        # 嵌套回复递归构造
        replies = getattr(c, "replies", None) or []
        if replies:
            # 对 replies 递归调用（已知 replies_count 为 0，避免额外查询）
            out_replies = []
            for r in replies:
                r_out = CommentOut.model_validate(r)
                r_out.author_name = author_map.get(r.author_id)
                r_out.replies_count = replies_count_map.get(r.id, 0)
                out_replies.append(r_out)
            # 用 metadata_json 不合适，直接放在 extra / 通过模型序列化扩展
            # 此处不展开嵌套回复字段，前端可通过 entity_id 单独查询
        return out

    return [to_out(c) for c in comments]


# ============================================================
# 项目评论列表 / 创建
# ============================================================
@router.get("/projects/{project_id}/comments", response_model=CommentListResponse)
async def list_project_comments(
    project_id: uuid.UUID,
    entity_type: Optional[CommentEntityType] = Query(
        None, description="按实体类型过滤（contract/document/comparison/qualification/project）"
    ),
    entity_id: Optional[uuid.UUID] = Query(None, description="按实体 ID 过滤（与 entity_type 一起使用）"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comment:view")),
):
    """查询项目评论列表（默认仅返回顶层评论）

    - 支持 entity_type + entity_id 过滤到具体实体
    - 当指定 entity_type + entity_id 时，返回该实体的评论树（含一级回复）
    """
    # 校验项目存在
    project = await db.get(Project, project_id)
    if project is None or project.is_deleted:
        raise HTTPException(status_code=404, detail="项目不存在")

    service = get_comment_service()
    # 指定实体 → 返回评论树
    if entity_type is not None and entity_id is not None:
        tree = await service.list_by_entity(
            db,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        outs = await _enrich_comments(db, tree)
        return CommentListResponse(items=outs, total=len(outs))

    # 普通分页列表
    items, total = await service.list_comments(
        db,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    outs = await _enrich_comments(db, items)
    return CommentListResponse(items=outs, total=total)


@router.post(
    "/projects/{project_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    project_id: uuid.UUID,
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comment:create")),
):
    """创建评论（含 @提及 + AI 分析）

    - 自动解析 content 中的 @username，匹配 User 表创建 Mention + 站内信
    - AI 分析为可选、不阻塞主流程（try/except）
    - parent_id 指定时为回复，需属于同一 entity
    """
    # 校验项目存在
    project = await db.get(Project, project_id)
    if project is None or project.is_deleted:
        raise HTTPException(status_code=404, detail="项目不存在")

    service = get_comment_service()
    try:
        comment = await service.create_comment(
            db,
            project_id=project_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            author_id=current_user.id,
            content=payload.content,
            parent_id=payload.parent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    outs = await _enrich_comments(db, [comment])
    return outs[0]


# ============================================================
# 单条评论：删除 / AI 分析
# ============================================================
@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comment:delete")),
):
    """软删除评论（仅作者或 admin 可删，不级联删除回复）"""
    service = get_comment_service()
    try:
        await service.delete_comment(
            db,
            comment_id=comment_id,
            user_id=current_user.id,
            is_admin=current_user.is_admin,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/comments/{comment_id}/analyze", response_model=CommentAnalyzeResponse)
async def analyze_comment(
    comment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comment:view")),
):
    """AI 分析评论（情感 + 关键问题，单独触发）

    返回 {comment_id, ai_sentiment, ai_keywords}
    """
    service = get_comment_service()
    try:
        result = await service.analyze_comment(db, comment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI 分析失败：{e}",
        )
    return result
