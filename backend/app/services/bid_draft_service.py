"""
标书起草辅助服务（Phase 3 T4）

功能：
- 标书模板 CRUD（含变量占位符）
- 标书草稿 CRUD（按项目维度）
- AI 生成草稿章节：RAG 召回历史标书片段作为 few-shot → LLM 生成 → 返回内容 + 证据链 + 置信度
- 模板变量填充：替换 {variable} 占位符，返回已填充/缺失变量清单

依赖：
- T3 多 LLM 负载均衡（app.ai.llm.client.get_llm_client）
- 知识库 RAG（app.ai.rag.retriever.get_rag_retriever）
"""
import re
import uuid
from string import Formatter
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.rag.retriever import get_rag_retriever
from app.models.bid_draft import (
    BidDraft,
    BidDraftStatus,
    BidTemplate,
    BidTemplateCategory,
)
from app.models.project import Project


# ============================================================
# LLM Prompt
# ============================================================

SYSTEM_PROMPT = (
    "你是标书起草专家，根据历史经验和项目要求生成标书章节。"
    "需要参考历史标书片段（few-shot）作为风格与结构范例，"
    "结合项目实际情况生成专业、规范、可直接用于投标的章节内容。"
    "禁止编造资质/业绩/案例，未提供的信息用占位符标注（如【请补充：xxx】）。"
    "输出为纯文本/Markdown，不要包裹代码块。"
)

USER_PROMPT_TEMPLATE = """请为以下标书章节生成内容：

【项目信息】
- 项目名称：{project_name}
- 项目编号：{project_code}
- 甲方：{client}
- 行业：{industry}

【章节要求】
- 章节标题：{section_title}
- 章节分类：{category}
{context_block}

【历史标书片段参考】（RAG 召回，仅作为风格与结构参考，不可照抄具体业绩数据）
{reference_block}
{few_shot_block}
【生成要求】
1. 内容须贴合项目实际情况，专业规范，可直接用于投标
2. 如缺少项目具体信息，用占位符【请补充：xxx】标注，不要编造
3. 章节结构清晰，包含必要的子标题与要点
4. 控制篇幅在 800-2000 字之间
5. 若提供了【已知产品白名单】，涉及产品名称时优先使用白名单中的名称
"""


class BidDraftService:
    """标书起草辅助服务"""

    # RAG 召回历史标书片段数量
    RAG_TOP_K = 5
    # 单条召回片段截断长度
    CHUNK_CONTENT_LIMIT = 600
    # LLM 生成置信度（无明确指标时给固定值）
    DEFAULT_CONFIDENCE = 0.8

    def __init__(self):
        self._llm = get_llm_client()
        self._rag = get_rag_retriever()

    # ============================================================
    # 模板管理
    # ============================================================

    async def create_template(
        self,
        db: AsyncSession,
        payload: dict,
        user_id: uuid.UUID,
    ) -> BidTemplate:
        """创建标书模板"""
        template = BidTemplate(
            name=payload["name"],
            category=payload.get("category", BidTemplateCategory.OTHER),
            description=payload.get("description"),
            content=payload["content"],
            variables=payload.get("variables"),
            is_active=payload.get("is_active", True),
            industry=payload.get("industry"),
            created_by=user_id,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    async def list_templates(
        self,
        db: AsyncSession,
        category: Optional[BidTemplateCategory] = None,
        is_active: Optional[bool] = None,
    ) -> list[BidTemplate]:
        """查询标书模板列表"""
        stmt = select(BidTemplate).where(BidTemplate.is_deleted == False)  # noqa: E712
        if category is not None:
            stmt = stmt.where(BidTemplate.category == category)
        if is_active is not None:
            stmt = stmt.where(BidTemplate.is_active == is_active)
        stmt = stmt.order_by(BidTemplate.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_template(self, db: AsyncSession, template_id: uuid.UUID) -> BidTemplate:
        """获取标书模板"""
        template = await db.get(BidTemplate, template_id)
        if not template or template.is_deleted:
            raise ValueError("标书模板不存在")
        return template

    async def update_template(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
        payload: dict,
    ) -> BidTemplate:
        """更新标书模板"""
        template = await self.get_template(db, template_id)
        for k, v in payload.items():
            if v is not None:
                setattr(template, k, v)
        await db.commit()
        await db.refresh(template)
        return template

    async def delete_template(self, db: AsyncSession, template_id: uuid.UUID) -> None:
        """软删除标书模板"""
        template = await self.get_template(db, template_id)
        template.is_deleted = True
        await db.commit()

    # ============================================================
    # 草稿管理
    # ============================================================

    async def create_draft(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        title: str,
        template_id: Optional[uuid.UUID],
        user_id: uuid.UUID,
        sections: Optional[list] = None,
        metadata_json: Optional[dict] = None,
    ) -> BidDraft:
        """创建标书草稿（同一项目允许多个草稿；若需唯一可在外层校验）"""
        # 校验项目存在
        project = await db.get(Project, project_id)
        if not project or project.is_deleted:
            raise ValueError("项目不存在")

        # 校验模板存在（若指定）
        if template_id is not None:
            await self.get_template(db, template_id)

        draft = BidDraft(
            project_id=project_id,
            template_id=template_id,
            title=title,
            status=BidDraftStatus.DRAFT,
            sections=sections,
            metadata_json=metadata_json,
            created_by=user_id,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        return draft

    async def get_draft(self, db: AsyncSession, project_id: uuid.UUID) -> Optional[BidDraft]:
        """获取项目最新草稿（按 created_at 倒序取首条）

        返回 None 表示项目尚无草稿。
        """
        stmt = (
            select(BidDraft)
            .where(BidDraft.project_id == project_id)
            .order_by(BidDraft.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_draft_by_id(self, db: AsyncSession, draft_id: uuid.UUID) -> BidDraft:
        """按 ID 获取草稿"""
        draft = await db.get(BidDraft, draft_id)
        if not draft:
            raise ValueError("标书草稿不存在")
        return draft

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        payload: dict,
    ) -> BidDraft:
        """更新草稿"""
        draft = await self.get_draft_by_id(db, draft_id)
        for k, v in payload.items():
            if v is not None:
                setattr(draft, k, v)
        await db.commit()
        await db.refresh(draft)
        return draft

    async def add_section_to_draft(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        section_title: str,
        content: str,
        ai_generated: bool,
        source_chunks: Optional[list] = None,
    ) -> BidDraft:
        """向草稿追加章节"""
        draft = await self.get_draft_by_id(db, draft_id)
        sections = list(draft.sections or [])
        sections.append({
            "title": section_title,
            "content": content,
            "ai_generated": ai_generated,
            "source_chunks": source_chunks or [],
        })
        draft.sections = sections
        await db.commit()
        await db.refresh(draft)
        return draft

    # ============================================================
    # AI 生成章节
    # ============================================================

    async def generate_section(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        section_title: str,
        category: Optional[BidTemplateCategory] = None,
        context: Optional[str] = None,
    ) -> dict:
        """AI 生成标书章节

        流程：
        1. 加载项目信息（名称/编号/甲方/行业）
        2. RAG 召回历史标书片段作为 few-shot 参考
        3. 构建 Prompt → LLM 生成
        4. 返回 {content, source_chunks, confidence}
        """
        # 1. 加载项目信息
        project = await db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        project_info = {
            "project_name": project.name or "（未命名项目）",
            "project_code": project.code or "（无编号）",
            "client": project.client or "（未指定甲方）",
            "industry": project.industry or "（未指定行业）",
        }

        # 2. RAG 召回历史标书片段（few-shot）
        source_chunks = await self._retrieve_reference_chunks(
            db, section_title, category
        )

        # 2.1 召回专家反馈 Few-Shot（P3-13 T13.5）：
        # - 结构识别范例（feedback_type=structure_recognition）
        # - 已知产品白名单（feedback_type=product_name 去重）
        few_shot_block = await self._build_feedback_fewshot_block(db)

        # 3. 构建 Prompt
        reference_block = self._format_reference(source_chunks)
        context_block = f"- 上下文/特殊要求：{context}" if context else ""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            project_name=project_info["project_name"],
            project_code=project_info["project_code"],
            client=project_info["client"],
            industry=project_info["industry"],
            section_title=section_title,
            category=category.value if category else "（未指定）",
            context_block=context_block,
            reference_block=reference_block,
            few_shot_block=few_shot_block,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 4. LLM 生成
        try:
            content = await self._llm.chat(
                messages,
                temperature=0.4,
                max_tokens=4096,
                task_key="bid_draft",
            )
        except Exception as e:
            logger.error("标书章节 LLM 生成失败: {}", e)
            raise

        confidence = self._estimate_confidence(content, source_chunks)

        return {
            "content": content or "",
            "source_chunks": source_chunks,
            "confidence": confidence,
        }

    # ============================================================
    # 模板变量填充
    # ============================================================

    async def fill_template(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
        variables: dict,
    ) -> dict:
        """填充模板变量

        流程：
        1. 加载模板
        2. 解析模板中所有 {variable} 占位符
        3. 用 variables 字典替换；缺失变量保留原占位符
        4. 返回 {content, filled_variables, missing_variables}
        """
        template = await self.get_template(db, template_id)

        # 解析模板中声明的占位符
        declared = self._extract_placeholders(template.content)

        # 已填充与缺失
        filled = []
        missing = []
        for name in declared:
            if name in variables and variables[name] is not None:
                filled.append(name)
            else:
                missing.append(name)

        # 安全替换：仅替换 variables 中存在的键，缺失的保留原占位符
        content = self._safe_format(template.content, variables)
        return {
            "content": content,
            "filled_variables": filled,
            "missing_variables": missing,
        }

    # ============================================================
    # 内部辅助
    # ============================================================

    async def _retrieve_reference_chunks(
        self,
        db: AsyncSession,
        section_title: str,
        category: Optional[BidTemplateCategory] = None,
    ) -> list[dict]:
        """RAG 召回历史标书片段作为参考

        查询文本优先用章节标题；category="bid" 用于聚焦标书知识库。
        召回失败不阻断主流程。
        """
        try:
            chunks = await self._rag.search_knowledge(
                db,
                query=section_title,
                category="bid",
                top_k=self.RAG_TOP_K,
            )
        except Exception as e:
            logger.warning("标书 RAG 召回失败: {}", e)
            return []

        # 截断 content 并精简字段
        out = []
        for c in chunks:
            content = (c.get("content") or "")[: self.CHUNK_CONTENT_LIMIT]
            out.append({
                "chunk_id": c.get("chunk_id"),
                "content": content,
                "page_number": c.get("page_number"),
                "title": c.get("title"),
                "category": c.get("category"),
            })
        return out

    @staticmethod
    def _format_reference(chunks: list[dict]) -> str:
        """格式化召回片段为 Prompt 文本"""
        if not chunks:
            return "（无历史标书片段召回）"
        lines = []
        for i, c in enumerate(chunks, 1):
            title = c.get("title") or c.get("category") or "历史片段"
            content = c.get("content") or ""
            page = c.get("page_number")
            page_str = f" | 页码={page}" if page is not None else ""
            lines.append(
                f"[片段{i}] {title}{page_str} (chunk_id={c.get('chunk_id')})\n{content}"
            )
        return "\n\n".join(lines)

    async def _build_feedback_fewshot_block(self, db: AsyncSession) -> str:
        """构建专家反馈 Few-Shot 块（P3-13 T13.5）

        - 结构识别范例（structure_recognition）：3 条最近修正
        - 已知产品白名单（product_name 去重）：50 条
        - 召回失败不阻断，返回空字符串
        """
        try:
            from app.services.feedback_service import get_feedback_service
            feedback_service = get_feedback_service()
        except Exception as e:
            logger.warning(f"[BidDraft] 反馈服务不可用（不阻断）: {e}")
            return ""

        blocks: list[str] = []

        # 1. 结构识别 Few-Shot 范例
        try:
            examples = await feedback_service.get_structure_examples(db, top_k=3)
            if examples:
                lines = ["【专家结构识别范例】（参考判定倾向，不照搬）"]
                for i, ex in enumerate(examples, 1):
                    ctx = (ex.context_text or "").replace("\n", " ")[:150]
                    corrected = (ex.corrected_verdict or "").replace("\n", " ")[:100]
                    reason = (ex.correction_reason or "").replace("\n", " ")[:200]
                    lines.append(
                        f"[范例{i}] {ctx}\n  正确结构：{corrected}\n  说明：{reason}"
                    )
                blocks.append("\n".join(lines))
        except Exception as e:
            logger.warning(f"[BidDraft] 结构识别范例召回失败（不阻断）: {e}")

        # 2. 已知产品白名单
        try:
            product_names = await feedback_service.get_known_product_names(db, top_k=50)
            if product_names:
                blocks.append(
                    "【已知产品白名单】（涉及产品名时优先使用以下名称）\n"
                    + " / ".join(product_names)
                )
        except Exception as e:
            logger.warning(f"[BidDraft] 产品白名单召回失败（不阻断）: {e}")

        if not blocks:
            return ""
        return "\n".join(blocks) + "\n"

    def _estimate_confidence(self, content: str, source_chunks: list[dict]) -> float:
        """估算生成置信度

        - 有内容且有召回证据 → DEFAULT_CONFIDENCE
        - 有内容但无召回证据 → 略降
        - 内容过短 → 进一步降低
        """
        if not content or len(content.strip()) < 50:
            return 0.3
        if not source_chunks:
            return 0.6
        return self.DEFAULT_CONFIDENCE

    @staticmethod
    def _extract_placeholders(text: str) -> list[str]:
        """提取模板中所有 {variable} 占位符（去重保序）

        使用 string.Formatter 解析；忽略 {{ }} 转义与字段访问语法（仅取字段名）。
        """
        seen: set = set()
        names: list[str] = []
        try:
            for _lit, name, _spec, _conv in Formatter().parse(text):
                if name is None:
                    continue
                # name 可能是 "a.b" 或 "a[0]"，仅取首段字段名
                key = name.split(".")[0].split("[")[0].strip()
                if not key:
                    continue
                if key not in seen:
                    seen.add(key)
                    names.append(key)
        except (ValueError, IndexError):
            # 模板含非法格式语法 → 回退正则
            for m in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text):
                key = m.group(1)
                if key not in seen:
                    seen.add(key)
                    names.append(key)
        return names

    @staticmethod
    def _safe_format(template: str, variables: dict) -> str:
        """安全填充模板：仅替换 variables 中存在的键，缺失的保留原占位符

        避免 str.format_map 在缺键时抛 KeyError。
        """
        class _SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        return template.format_map(_SafeDict(variables))


# 单例
_bid_draft_service: Optional[BidDraftService] = None


def get_bid_draft_service() -> BidDraftService:
    global _bid_draft_service
    if _bid_draft_service is None:
        _bid_draft_service = BidDraftService()
    return _bid_draft_service
