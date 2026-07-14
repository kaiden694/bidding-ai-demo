"""证据链服务：证据存证 + 最佳证据选择 + 人工复核"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import (
    EvidenceSourceFile,
    EvidenceDocumentPage,
    EvidenceExtractionRun,
    EvidenceSpan,
)
from app.models.document import DocumentChunk


class EvidenceService:
    """证据链服务"""

    # 打分权重（参考 lib-v0.2 evidence_service.py）
    _SCORE_FIELD_HIT = 20       # field 命中
    _SCORE_QUOTE_CONTAINS = 12  # quote 包含查询文本
    _SCORE_HAS_PAGE = 2         # 有页码
    _SCORE_REVIEW_APPROVED = 3  # 复核通过
    _MAX_REVIEW_HISTORY = 20    # 复核历史最多保留 20 条

    async def get_or_create_source_file(
        self, session: AsyncSession, domain: str, source_table: str, source_id: uuid.UUID,
        file_name: Optional[str] = None, file_key: Optional[str] = None,
    ) -> EvidenceSourceFile:
        """获取或创建源文件记录（domain + source_table + source_id 三元组唯一）"""
        stmt = select(EvidenceSourceFile).where(
            EvidenceSourceFile.domain == domain,
            EvidenceSourceFile.source_table == source_table,
            EvidenceSourceFile.source_id == source_id,
            EvidenceSourceFile.is_deleted == False,
        )
        result = await session.execute(stmt)
        existing = result.scalars().first()
        if existing:
            return existing
        sf = EvidenceSourceFile(
            domain=domain, source_table=source_table, source_id=source_id,
            file_name=file_name, file_key=file_key,
        )
        session.add(sf)
        await session.flush()
        return sf

    async def create_extraction_run(
        self, session: AsyncSession, source_file_id: uuid.UUID,
        extractor_type: str = "llm", model_name: Optional[str] = None,
        prompt_text: Optional[str] = None, parser_version: Optional[str] = None,
    ) -> EvidenceExtractionRun:
        """创建提取过程记录（追溯 LLM 提取）"""
        prompt_hash = None
        if prompt_text:
            prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        run = EvidenceExtractionRun(
            source_file_id=source_file_id, extractor_type=extractor_type,
            model_name=model_name, prompt_hash=prompt_hash,
            parser_version=parser_version, status="done",
        )
        session.add(run)
        await session.flush()
        return run

    async def create_evidence_span(
        self, session: AsyncSession, source_file_id: uuid.UUID,
        quote_text: str, page_number: Optional[int] = None,
        field_name: Optional[str] = None, confidence: float = 0.8,
        extraction_run_id: Optional[uuid.UUID] = None,
        char_offset_start: Optional[int] = None, char_offset_end: Optional[int] = None,
    ) -> EvidenceSpan:
        """创建证据片段"""
        span = EvidenceSpan(
            source_file_id=source_file_id, extraction_run_id=extraction_run_id,
            quote_text=quote_text, page_number=page_number,
            field_name=field_name, confidence=confidence,
            char_offset_start=char_offset_start, char_offset_end=char_offset_end,
        )
        session.add(span)
        await session.flush()
        return span

    async def evidence_citation_for_target(
        self, session: AsyncSession, source_file_id: uuid.UUID,
        field_name: Optional[str] = None, query_text: Optional[str] = None,
        top_k: int = 3,
    ) -> List[EvidenceSpan]:
        """按打分选最佳证据（参考 lib-v0.2 打分规则）"""
        stmt = select(EvidenceSpan).where(EvidenceSpan.source_file_id == source_file_id)
        if field_name:
            stmt = stmt.where(EvidenceSpan.field_name == field_name)
        stmt = stmt.order_by(desc(EvidenceSpan.created_at)).limit(50)
        result = await session.execute(stmt)
        spans = list(result.scalars().all())

        scored = []
        for span in spans:
            score = 0.0
            if field_name and span.field_name == field_name:
                score += self._SCORE_FIELD_HIT
            if query_text and query_text in (span.quote_text or ""):
                score += self._SCORE_QUOTE_CONTAINS
            if span.page_number:
                score += self._SCORE_HAS_PAGE
            if span.review_status == "approved":
                score += self._SCORE_REVIEW_APPROVED
            scored.append((score, span))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    async def review_evidence_span(
        self, session: AsyncSession, span_id: uuid.UUID,
        review_status: str, reviewer_id: Optional[uuid.UUID] = None,
        comment: Optional[str] = None,
    ) -> EvidenceSpan:
        """人工复核证据片段（review_history 最多 20 条）"""
        span = await session.get(EvidenceSpan, span_id)
        if not span:
            raise ValueError("证据片段不存在")
        history = span.review_history or []
        history.append({
            "review_status": review_status,
            "reviewer_id": str(reviewer_id) if reviewer_id else None,
            "comment": comment,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        span.review_history = history[-self._MAX_REVIEW_HISTORY:]
        span.review_status = review_status
        if reviewer_id:
            span.reviewed_by = reviewer_id
        await session.flush()
        return span

    async def create_spans_from_chunks(
        self, session: AsyncSession, source_file_id: uuid.UUID,
        chunks: List[DocumentChunk], extraction_run_id: Optional[uuid.UUID] = None,
    ) -> List[EvidenceSpan]:
        """从文档切块批量创建证据片段"""
        spans = []
        for chunk in chunks:
            span = await self.create_evidence_span(
                session, source_file_id=source_file_id,
                quote_text=(chunk.content or "")[:1000],
                page_number=chunk.page_number,
                extraction_run_id=extraction_run_id,
                char_offset_start=0,
                char_offset_end=min(len(chunk.content or ""), 1000),
            )
            spans.append(span)
        return spans


# 单例
_evidence_service: Optional[EvidenceService] = None


def get_evidence_service() -> EvidenceService:
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = EvidenceService()
    return _evidence_service
