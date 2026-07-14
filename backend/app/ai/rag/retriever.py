"""
RAG 检索器：混合检索
- 向量召回（pgvector cosine）
- 关键词过滤（pg_trgm ILIKE）
- 业务标签过滤
- 重排序（Phase 2 接入 bge-reranker）
返回可定位的证据（chunk_id + 页码 + 章节 + 原文片段）

检索目标：
- 文档切块（DocumentChunk）：招标/标书/规格书等业务文档证据
- 历史知识库（KnowledgeChunk）：专家经验/范本/历史标书
- 通用知识库（GeneralKnowledgeChunk）：企业资料/政策法规/行业标准/内部规范
- 产品资料（ProductChunk）：产品技术资料，供参数偏离比对选型
"""
import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import DocumentChunk, KnowledgeChunk
from app.models.general_knowledge import GeneralKnowledgeBase, GeneralKnowledgeChunk
from app.models.product import Product, ProductChunk
from app.ai.embedding.client import get_embedding_client


class RAGRetriever:
    """混合检索器"""

    def __init__(self):
        self._embedding_client = get_embedding_client()

    async def search_documents(
        self,
        session: AsyncSession,
        query: str,
        document_ids: Optional[list] = None,
        top_k: int = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """在文档切块中检索证据"""
        if not query or not query.strip():
            return []
        top_k = top_k or settings.RAG_RETRIEVE_TOP_K
        query_vec = await self._embedding_client.embed_one(query)
        # 向量召回（cosine 距离）
        stmt = select(DocumentChunk).order_by(
            DocumentChunk.embedding.cosine_distance(query_vec)
        ).limit(top_k)
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
        if keyword:
            stmt = stmt.where(DocumentChunk.content.ilike(f"%{keyword}%"))
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        return [self._to_evidence(c) for c in chunks]

    async def search_knowledge(
        self,
        session: AsyncSession,
        query: str,
        category: Optional[str] = None,
        top_k: int = None,
    ) -> list[dict]:
        """在历史知识库中检索"""
        if not query or not query.strip():
            return []
        top_k = top_k or settings.RAG_RETRIEVE_TOP_K
        query_vec = await self._embedding_client.embed_one(query)
        stmt = select(KnowledgeChunk).order_by(
            KnowledgeChunk.embedding.cosine_distance(query_vec)
        ).limit(top_k)
        if category:
            stmt = stmt.where(KnowledgeChunk.category == category)
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        return [self._to_evidence_kc(c) for c in chunks]

    @staticmethod
    def _to_evidence(chunk: DocumentChunk) -> dict:
        """组装证据（含定位信息）"""
        return {
            "chunk_id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "content": chunk.content,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "table_ref": chunk.table_ref,
            "chunk_type": chunk.chunk_type,
        }

    @staticmethod
    def _to_evidence_kc(chunk: KnowledgeChunk) -> dict:
        return {
            "chunk_id": str(chunk.id),
            "title": chunk.title,
            "content": chunk.content,
            "category": chunk.category,
            "page_number": chunk.page_number,
        }

    async def search_general_knowledge(
        self,
        session: AsyncSession,
        query: str,
        category: Optional[str] = None,
        visibility: Optional[str] = None,
        top_k: int = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """在通用知识库中检索（企业资料/政策法规/行业标准/内部规范等）

        向量召回 + 关键词过滤；支持按 category（分类）与 visibility（可见范围
        front/back/all）过滤。visibility="all" 的内容对前台/后台均可见。
        """
        if not query or not query.strip():
            return []
        top_k = top_k or settings.RAG_RETRIEVE_TOP_K
        query_vec = await self._embedding_client.embed_one(query)
        stmt = select(GeneralKnowledgeChunk).join(
            GeneralKnowledgeBase,
            GeneralKnowledgeChunk.knowledge_base_id == GeneralKnowledgeBase.id,
        )
        conditions = [
            GeneralKnowledgeBase.is_deleted.is_(False),
            GeneralKnowledgeBase.is_published.is_(True),
        ]
        if category:
            conditions.append(GeneralKnowledgeBase.category == category)
        if visibility:
            conditions.append(GeneralKnowledgeBase.visibility.in_([visibility, "all"]))
        if keyword:
            conditions.append(GeneralKnowledgeChunk.content.ilike(f"%{keyword}%"))
        stmt = stmt.where(and_(*conditions)).order_by(
            GeneralKnowledgeChunk.embedding.cosine_distance(query_vec)
        ).limit(top_k)
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        return [self._to_evidence_gk(c) for c in chunks]

    async def search_products(
        self,
        session: AsyncSession,
        query: str,
        product_ids: Optional[list] = None,
        category_id: Optional[uuid.UUID] = None,
        top_k: int = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """在产品资料中检索（用于产品选型/参数偏离比对）

        从 ProductChunk 向量库召回，仅检索已上架且未删除的产品；
        可按 product_ids 列表或 category_id 过滤。
        """
        if not query or not query.strip():
            return []
        top_k = top_k or settings.RAG_RETRIEVE_TOP_K
        query_vec = await self._embedding_client.embed_one(query)
        stmt = select(ProductChunk).join(
            Product, ProductChunk.product_id == Product.id
        )
        conditions = [
            Product.is_deleted.is_(False),
            Product.is_published.is_(True),
        ]
        if product_ids:
            conditions.append(ProductChunk.product_id.in_(product_ids))
        if category_id:
            conditions.append(Product.category_id == category_id)
        if keyword:
            conditions.append(ProductChunk.content.ilike(f"%{keyword}%"))
        stmt = stmt.where(and_(*conditions)).order_by(
            ProductChunk.embedding.cosine_distance(query_vec)
        ).limit(top_k)
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        return [self._to_evidence_pc(c) for c in chunks]

    @staticmethod
    def _to_evidence_gk(chunk: GeneralKnowledgeChunk) -> dict:
        """通用知识库证据（含定位信息）"""
        return {
            "chunk_id": str(chunk.id),
            "knowledge_base_id": str(chunk.knowledge_base_id),
            "source_doc_id": str(chunk.source_doc_id) if chunk.source_doc_id else None,
            "content": chunk.content,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "table_ref": chunk.table_ref,
            "chunk_type": chunk.chunk_type,
        }

    @staticmethod
    def _to_evidence_pc(chunk: ProductChunk) -> dict:
        """产品资料证据（含定位信息）"""
        return {
            "chunk_id": str(chunk.id),
            "product_id": str(chunk.product_id),
            "source_doc_id": str(chunk.source_doc_id) if chunk.source_doc_id else None,
            "content": chunk.content,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "table_ref": chunk.table_ref,
            "chunk_type": chunk.chunk_type,
        }


_rag: Optional[RAGRetriever] = None


def get_rag_retriever() -> RAGRetriever:
    global _rag
    if _rag is None:
        _rag = RAGRetriever()
    return _rag
