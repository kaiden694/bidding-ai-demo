"""向量化服务：文档切块批量向量化入库"""
import uuid
from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk, KnowledgeChunk
from app.ai.embedding.client import get_embedding_client


class EmbeddingService:
    """把切块内容向量化并回写 embedding 列"""

    def __init__(self):
        self._client = get_embedding_client()

    async def embed_document_chunks(self, session: AsyncSession, document_id: uuid.UUID, batch_size: int = 32):
        """批量向量化某文档的所有切块"""
        result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)
        )
        chunks: List[DocumentChunk] = result.scalars().all()
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            vectors = await self._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()

    async def embed_knowledge_chunks(self, session: AsyncSession, knowledge_base_id: uuid.UUID, batch_size: int = 32):
        result = await session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == knowledge_base_id)
        )
        chunks: List[KnowledgeChunk] = result.scalars().all()
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            vectors = await self._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
