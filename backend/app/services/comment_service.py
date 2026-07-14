"""
协作评论服务（Phase 3 T6）

职责：
- create_comment: 创建评论 + 解析 @提及 + 发送站内信 + 可选 AI 分析
- list_comments: 评论列表查询（支持按实体类型/ID 过滤）
- list_by_entity: 按实体查询评论树（含一级回复）
- delete_comment: 软删除（仅作者或 admin 可删）
- analyze_comment: AI 分析评论情感 + 提取关键问题

设计要点（v1.2 §13 AI 优先）：
- @提及通过正则解析，匹配 User 表中实际存在的用户
- AI 分析为可选、不阻塞主流程（try/except 包裹）
- 嵌套回复通过 parent_id 自引用，不级联删除
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.models.comment import Comment, CommentEntityType, Mention
from app.models.notification import NotificationType
from app.models.user import User
from app.services.notification_service import get_notification_service


# @username 正则（支持中文/字母/数字/下划线，4-64 字符）
_MENTION_PATTERN = re.compile(r"@([\w\u4e00-\u9fa5]{2,64})")

# AI 分析 Prompt
_AI_ANALYZE_SYSTEM_PROMPT = (
    "你是一个招投标协作评论分析助手。请分析用户评论，返回严格的 JSON："
    '{"sentiment":"positive|neutral|negative","keywords":["关键问题1","关键问题2"]}'
    "。keywords 最多 5 个，提取评论中的核心问题/风险点。仅返回 JSON，不要任何额外文字。"
)


class CommentService:
    """协作评论 + @提及 + AI 分析服务"""

    def __init__(self):
        self._llm = get_llm_client()
        self._notification = get_notification_service()

    # ============================================================
    # 创建评论
    # ============================================================
    async def create_comment(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[uuid.UUID],
        entity_type: CommentEntityType,
        entity_id: uuid.UUID,
        author_id: uuid.UUID,
        content: str,
        parent_id: Optional[uuid.UUID] = None,
    ) -> Comment:
        """创建评论 + 解析 @提及 + 发送站内信 + 可选 AI 分析

        流程：
        1. 校验 parent_id（若指定）属于同一 entity
        2. 写入 Comment
        3. 解析 @username，匹配 User 表创建 Mention + 站内信
        4. AI 分析（try/except，不阻塞）
        """
        # 1. 校验 parent
        if parent_id is not None:
            parent = await db.get(Comment, parent_id)
            if parent is None or parent.is_deleted:
                raise ValueError("父评论不存在或已删除")
            if parent.entity_type != entity_type or parent.entity_id != entity_id:
                raise ValueError("父评论与回复目标实体不一致")
            # 沿用父评论的 project_id
            if project_id is None:
                project_id = parent.project_id

        # 2. 写入评论
        comment = Comment(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            author_id=author_id,
            content=content,
            parent_id=parent_id,
        )
        db.add(comment)
        await db.flush()  # 拿到 comment.id

        # 3. @提及解析
        await self._process_mentions(db, comment, author_id)

        await db.commit()
        await db.refresh(comment)

        # 4. AI 分析（不阻塞主流程）
        await self._safe_analyze(comment)

        return comment

    async def _process_mentions(
        self,
        db: AsyncSession,
        comment: Comment,
        author_id: uuid.UUID,
    ) -> None:
        """解析评论中的 @username，创建 Mention 记录 + 发送站内信"""
        usernames = self._parse_mentions(comment.content)
        if not usernames:
            return

        # 查询匹配的用户（去重 + 排除作者本人）
        stmt = select(User).where(
            User.username.in_(usernames),
            User.is_deleted.is_(False),
        )
        users = list((await db.execute(stmt)).scalars().all())
        if not users:
            return

        author = await db.get(User, author_id)
        author_display = (author.full_name or author.username) if author else "某用户"

        for user in users:
            if user.id == author_id:
                continue  # 不通知作者本人
            mention = Mention(
                comment_id=comment.id,
                mentioned_user_id=user.id,
                is_notified=False,
            )
            db.add(mention)
            await db.flush()

            # 发送站内信
            try:
                await self._notification.send_notification(
                    db,
                    user_id=user.id,
                    type=NotificationType.MENTION,
                    title=f"你在评论中被 @提及",
                    content=(
                        f"{author_display} 在评论中提及了你：\n"
                        f"{comment.content[:200]}"
                    ),
                    related_project_id=comment.project_id,
                    related_entity_type="comment",
                    related_entity_id=comment.id,
                )
                mention.is_notified = True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"评论 @提及站内信发送失败 user={user.id}: {e}")

    @staticmethod
    def _parse_mentions(content: str) -> list[str]:
        """从 content 中解析 @username，返回去重的用户名列表"""
        matches = _MENTION_PATTERN.findall(content or "")
        # 去重保序
        seen: set = set()
        result: list[str] = []
        for name in matches:
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ============================================================
    # 查询
    # ============================================================
    async def list_comments(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[uuid.UUID] = None,
        entity_type: Optional[CommentEntityType] = None,
        entity_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Comment], int]:
        """评论列表查询（默认仅返回顶层评论，不含回复）

        返回 (items, total)
        """
        conditions = [Comment.is_deleted.is_(False), Comment.parent_id.is_(None)]
        if project_id is not None:
            conditions.append(Comment.project_id == project_id)
        if entity_type is not None:
            conditions.append(Comment.entity_type == entity_type)
        if entity_id is not None:
            conditions.append(Comment.entity_id == entity_id)

        # 总数
        count_stmt = select(func.count(Comment.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        # 列表
        stmt = (
            select(Comment)
            .where(*conditions)
            .order_by(Comment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await db.execute(stmt)).scalars().all())
        return items, total

    async def list_by_entity(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[uuid.UUID],
        entity_type: CommentEntityType,
        entity_id: uuid.UUID,
    ) -> list[Comment]:
        """按实体查询评论树（顶层评论 + 一级回复，按创建时间升序）

        返回的 Comment 对象已通过 replies 关系加载一级回复。
        """
        # 顶层评论
        top_stmt = (
            select(Comment)
            .where(
                Comment.is_deleted.is_(False),
                Comment.parent_id.is_(None),
                Comment.entity_type == entity_type,
                Comment.entity_id == entity_id,
            )
            .order_by(Comment.created_at.asc())
        )
        if project_id is not None:
            top_stmt = top_stmt.where(Comment.project_id == project_id)

        top_comments = list((await db.execute(top_stmt)).scalars().all())
        if not top_comments:
            return []

        # 一次性查所有一级回复（避免 N+1）
        top_ids = [c.id for c in top_comments]
        reply_stmt = (
            select(Comment)
            .where(
                Comment.is_deleted.is_(False),
                Comment.parent_id.in_(top_ids),
            )
            .order_by(Comment.parent_id, Comment.created_at.asc())
        )
        replies = list((await db.execute(reply_stmt)).scalars().all())

        # 按 parent_id 分组挂载到顶层评论的 replies 属性
        reply_map: dict[uuid.UUID, list[Comment]] = {}
        for r in replies:
            reply_map.setdefault(r.parent_id, []).append(r)
        for c in top_comments:
            c.replies = reply_map.get(c.id, [])

        return top_comments

    # ============================================================
    # 删除
    # ============================================================
    async def delete_comment(
        self,
        db: AsyncSession,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
        is_admin: bool = False,
    ) -> None:
        """软删除评论（仅作者或 admin 可删，不级联删除回复）"""
        comment = await db.get(Comment, comment_id)
        if comment is None or comment.is_deleted:
            raise ValueError("评论不存在或已删除")

        if not is_admin and comment.author_id != user_id:
            raise PermissionError("无权删除他人评论")

        comment.is_deleted = True
        comment.deleted_at = datetime.now(timezone.utc)
        await db.commit()

    # ============================================================
    # AI 分析
    # ============================================================
    async def analyze_comment(
        self,
        db: AsyncSession,
        comment_id: uuid.UUID,
    ) -> dict:
        """触发 AI 分析评论（独立调用，可单独触发）

        返回 {comment_id, ai_sentiment, ai_keywords}
        """
        comment = await db.get(Comment, comment_id)
        if comment is None or comment.is_deleted:
            raise ValueError("评论不存在或已删除")

        result = await self._safe_analyze(comment, raise_on_error=True)
        # 持久化 AI 结果
        await db.commit()
        await db.refresh(comment)
        return {
            "comment_id": str(comment.id),
            "ai_sentiment": comment.ai_sentiment,
            "ai_keywords": comment.ai_keywords,
        }

    async def _safe_analyze(
        self,
        comment: Comment,
        raise_on_error: bool = False,
    ) -> dict:
        """AI 分析评论情感 + 关键问题（不阻塞主流程）

        - raise_on_error=True 时抛出异常（用于 analyze_comment 单独触发）
        - raise_on_error=False 时仅记录日志（用于 create_comment 内部调用）
        """
        try:
            raw = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _AI_ANALYZE_SYSTEM_PROMPT},
                    {"role": "user", "content": comment.content},
                ],
                temperature=0.1,
                max_tokens=512,
            )
            parsed = self._parse_llm_json(raw)
            sentiment = parsed.get("sentiment")
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "neutral"
            keywords = parsed.get("keywords") or []
            if not isinstance(keywords, list):
                keywords = []

            comment.ai_sentiment = sentiment
            comment.ai_keywords = keywords[:5]
            return {
                "ai_sentiment": sentiment,
                "ai_keywords": comment.ai_keywords,
            }
        except Exception as e:  # noqa: BLE001
            if raise_on_error:
                raise
            logger.warning(f"评论 AI 分析失败（不阻塞主流程）comment={comment.id}: {e}")
            return {"ai_sentiment": None, "ai_keywords": None}

    @staticmethod
    def _parse_llm_json(raw: str) -> dict:
        """解析 LLM 输出的 JSON（容错：去 markdown 围栏 + 提取首个 JSON 对象）"""
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning(f"评论 AI 分析返回非 JSON: {text[:200]}")
            return {}
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"评论 AI 分析 JSON 解析失败: {e}")
            return {}


# ============================================================
# 单例
# ============================================================
_comment_service: Optional[CommentService] = None


def get_comment_service() -> CommentService:
    global _comment_service
    if _comment_service is None:
        _comment_service = CommentService()
    return _comment_service
