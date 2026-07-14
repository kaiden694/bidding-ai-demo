"""
项目状态机服务（Phase 3 T1）

设计要点（v1.2 §13 AI 优先）：
- transition: 硬规则校验（查 ProjectStatusRule）+ 落审计记录
- get_next_statuses: 查询允许的下一状态
- recommend_next_status: LLM 辅助推荐（try/except 不阻塞主流程）
- 硬规则仅保留状态转移矩阵校验，下一状态推荐完全交给 LLM（非硬编码 if-else）
"""
import json
import re
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.models.comparison import ComparisonTask
from app.models.document import Document, DocParseStatus
from app.models.project import Project, ProjectStatus
from app.models.project_state import (
    ProjectStatusRule,
    ProjectStatusTransition,
)


# LLM 推荐下一状态的 Prompt
RECOMMEND_SYSTEM_PROMPT = """你是招投标项目状态流转助手。

任务：根据项目当前状态、文档解析进度、参数偏离比对结果，从「允许的下一状态列表」中推荐最合适的下一状态。

输出 JSON，字段如下：
{
  "recommended_status": "下一状态英文名（必须来自允许列表，若无法推荐则填 null）",
  "reason": "推荐理由（结合项目实际进度，简明扼要）",
  "confidence": 0.0到1.0的浮点数（推荐置信度）
}

判定原则：
- 仅基于项目实际进度（文档是否解析完成、比对是否完成、是否内审通过等）做推荐
- 若当前进度不足以推进，recommended_status 填 null，并在 reason 中说明缺什么
- recommended_status 必须严格来自「允许的下一状态列表」，不得自创

仅输出 JSON，不要额外解释或 Markdown 代码块。"""


class ProjectStateMachine:
    """项目状态机：转移校验 + 审计 + AI 辅助推荐"""

    def __init__(self):
        self._llm = get_llm_client()

    # ------------------------------------------------------------------
    # 状态流转
    # ------------------------------------------------------------------
    async def transition(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        to_status: ProjectStatus,
        user_id: Optional[uuid.UUID],
        reason: Optional[str] = None,
        ai_suggestion: bool = False,
        metadata_json: Optional[dict] = None,
    ) -> ProjectStatusTransition:
        """执行状态流转

        流程：
        1. 查询项目当前状态
        2. 校验转移是否允许（查 ProjectStatusRule）
        3. 不允许则抛 ValueError（含可用下一状态列表）
        4. 更新 Project.status
        5. 记录 ProjectStatusTransition
        6. 返回 transition 记录
        """
        project = await db.get(Project, project_id)
        if project is None:
            raise ValueError("项目不存在")

        from_status = project.status
        if from_status == to_status:
            raise ValueError(f"项目已处于该状态：{from_status.value}")

        # 硬规则校验：转移是否在规则矩阵中且启用
        if not await self._is_transition_allowed(db, from_status, to_status):
            allowed = await self.get_next_statuses(db, project_id)
            allowed_names = ", ".join(s.value for s in allowed)
            raise ValueError(
                f"不允许的状态流转：{from_status.value} -> {to_status.value}。"
                f"当前状态允许的下一状态：[{allowed_names}]"
            )

        # 更新项目状态
        project.status = to_status

        # 落审计记录
        transition = ProjectStatusTransition(
            project_id=project_id,
            from_status=from_status,
            to_status=to_status,
            transition_by=user_id,
            reason=reason,
            ai_suggestion=ai_suggestion,
            metadata_json=metadata_json,
        )
        db.add(transition)
        await db.commit()
        await db.refresh(transition)

        # 状态变更成功后触发通知（给创建者发站内信 + 查 TodoRule 自动生成待办）
        # try/except 不阻塞状态变更本身（transition 已落库）
        try:
            from app.services.notification_service import get_notification_service
            notification_service = get_notification_service()
            await notification_service.notify_status_transition(
                db, project, from_status, to_status, user_id
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"状态变更通知发送失败（不阻塞主流程）: {e}")

        return transition

    async def get_next_statuses(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> list[ProjectStatus]:
        """查询项目当前状态允许的下一状态（基于 ProjectStatusRule）"""
        project = await db.get(Project, project_id)
        if project is None:
            raise ValueError("项目不存在")
        return await self._query_next_statuses(db, project.status)

    async def recommend_next_status(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> dict:
        """LLM 辅助推荐下一状态（可选，try/except 不阻塞主流程）

        综合考虑：项目状态 + 文档解析进度 + 比对结果
        返回：{recommended_status, reason, confidence, available_next_statuses}
        """
        project = await db.get(Project, project_id)
        if project is None:
            raise ValueError("项目不存在")

        available = await self._query_next_statuses(db, project.status)
        available_names = [s.value for s in available]

        # 无可流转状态时直接返回，无需调用 LLM
        if not available_names:
            return {
                "recommended_status": None,
                "reason": "当前状态无可流转的下一状态",
                "confidence": None,
                "available_next_statuses": available,
            }

        # 收集上下文：文档解析进度 + 比对任务进度
        context = await self._build_context(db, project_id, project.status)

        available_enum_values = ", ".join(available_names)
        user_msg = (
            f"项目当前状态：{project.status.value}\n"
            f"允许的下一状态列表：[{available_enum_values}]\n\n"
            f"项目进度上下文：\n{context}"
        )

        try:
            raw = await self._llm.chat(
                messages=[
                    {"role": "system", "content": RECOMMEND_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=512,
            )
            parsed = self._parse_llm_output(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI 推荐下一状态失败（不阻塞主流程）: {e}")
            return {
                "recommended_status": None,
                "reason": "AI 推荐暂不可用",
                "confidence": None,
                "available_next_statuses": available,
            }

        # 校验 LLM 输出的状态确实在允许列表中（硬规则兜底）
        rec = parsed.get("recommended_status")
        if rec and rec not in available_names:
            logger.warning(
                f"LLM 推荐的状态 [{rec}] 不在允许列表中，已忽略"
            )
            rec = None

        recommended_enum = None
        if rec:
            try:
                recommended_enum = ProjectStatus(rec)
            except ValueError:
                recommended_enum = None

        return {
            "recommended_status": recommended_enum,
            "reason": parsed.get("reason"),
            "confidence": self._clamp(parsed.get("confidence"), 0.0, 1.0),
            "available_next_statuses": available,
        }

    async def get_transition_history(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> list[ProjectStatusTransition]:
        """查询项目状态变更历史（按时间倒序）"""
        stmt = (
            select(ProjectStatusTransition)
            .where(ProjectStatusTransition.project_id == project_id)
            .order_by(ProjectStatusTransition.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # 规则管理
    # ------------------------------------------------------------------
    async def list_rules(self, db: AsyncSession) -> list[ProjectStatusRule]:
        """查询全部状态转移规则"""
        stmt = select(ProjectStatusRule).order_by(
            ProjectStatusRule.from_status, ProjectStatusRule.to_status
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def upsert_rules(
        self, db: AsyncSession, rules: list[dict]
    ) -> list[ProjectStatusRule]:
        """批量 upsert 状态规则（幂等）

        - 已存在 (from_status, to_status) 的规则：更新 is_active / description
        - 不存在的规则：新增
        """
        existing = {
            (r.from_status, r.to_status): r
            for r in await self.list_rules(db)
        }
        for rule in rules:
            key = (rule["from_status"], rule["to_status"])
            cur = existing.get(key)
            if cur is None:
                cur = ProjectStatusRule(
                    from_status=rule["from_status"],
                    to_status=rule["to_status"],
                    is_active=rule.get("is_active", True),
                    description=rule.get("description"),
                )
                db.add(cur)
                existing[key] = cur
            else:
                cur.is_active = rule.get("is_active", True)
                if rule.get("description") is not None:
                    cur.description = rule["description"]
        await db.commit()
        return await self.list_rules(db)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    async def _is_transition_allowed(
        self, db: AsyncSession, from_status: ProjectStatus, to_status: ProjectStatus
    ) -> bool:
        """校验转移是否在规则矩阵中且启用"""
        stmt = select(func.count(ProjectStatusRule.id)).where(
            ProjectStatusRule.from_status == from_status,
            ProjectStatusRule.to_status == to_status,
            ProjectStatusRule.is_active.is_(True),
        )
        count = (await db.execute(stmt)).scalar() or 0
        return count > 0

    async def _query_next_statuses(
        self, db: AsyncSession, from_status: ProjectStatus
    ) -> list[ProjectStatus]:
        """查询某状态允许的下一状态列表"""
        stmt = (
            select(ProjectStatusRule.to_status)
            .where(
                ProjectStatusRule.from_status == from_status,
                ProjectStatusRule.is_active.is_(True),
            )
            .order_by(ProjectStatusRule.to_status)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    async def _build_context(
        self, db: AsyncSession, project_id: uuid.UUID, current_status: ProjectStatus
    ) -> str:
        """构建 LLM 推荐上下文：文档解析进度 + 比对任务进度

        失败时返回空字符串，不阻塞推荐
        """
        parts: list[str] = []
        try:
            # 文档解析进度
            doc_stmt = (
                select(
                    Document.doc_type,
                    Document.parse_status,
                    func.count(Document.id),
                )
                .where(
                    Document.project_id == project_id,
                    Document.is_deleted.is_(False),
                )
                .group_by(Document.doc_type, Document.parse_status)
            )
            doc_result = await db.execute(doc_stmt)
            doc_lines: list[str] = []
            for doc_type, parse_status, cnt in doc_result.all():
                doc_lines.append(
                    f"  - {doc_type.value if hasattr(doc_type, 'value') else doc_type}: "
                    f"{parse_status.value if hasattr(parse_status, 'value') else parse_status} "
                    f"({cnt} 份)"
                )
            if doc_lines:
                parts.append("文档解析进度：\n" + "\n".join(doc_lines))
            else:
                parts.append("文档解析进度：尚无文档")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"构建文档上下文失败: {e}")

        try:
            # 比对任务进度
            cmp_stmt = (
                select(ComparisonTask.status, func.count(ComparisonTask.id))
                .where(ComparisonTask.project_id == project_id)
                .group_by(ComparisonTask.status)
            )
            cmp_result = await db.execute(cmp_stmt)
            cmp_lines: list[str] = []
            for status, cnt in cmp_result.all():
                cmp_lines.append(f"  - {status}: {cnt} 个任务")
            if cmp_lines:
                parts.append("参数偏离比对任务：\n" + "\n".join(cmp_lines))
            else:
                parts.append("参数偏离比对任务：尚无任务")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"构建比对上下文失败: {e}")

        return "\n\n".join(parts) if parts else "暂无项目进度数据"

    @staticmethod
    def _parse_llm_output(raw: str) -> dict:
        """解析 LLM 输出的 JSON（容错：去 markdown 围栏 + 提取首个 JSON 对象）"""
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning(f"LLM 推荐返回非 JSON: {text[:200]}")
            return {}
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 推荐 JSON 解析失败: {e}")
            return {}

    @staticmethod
    def _clamp(v, lo: float, hi: float) -> Optional[float]:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return max(lo, min(hi, f))


# 单例
_project_state_machine: Optional[ProjectStateMachine] = None


def get_project_state_machine() -> ProjectStateMachine:
    global _project_state_machine
    if _project_state_machine is None:
        _project_state_machine = ProjectStateMachine()
    return _project_state_machine
