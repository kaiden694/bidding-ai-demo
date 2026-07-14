"""
知识库管理服务（Phase 2 增强）

设计要点（v1.2 §13 AI 优先）：
- batch_import: ZIP 批量导入 → 解析 → 切块 → 向量化（复用 Phase 1 解析器与向量化服务）
- reindex: 重建索引（重新 Embedding 所有切块，进度可查询）
- version_management: 版本切换 + 旧版本归档（is_active 单活）
- 标签管理：通过 tags JSON 字段，非硬规则分类
- 进度跟踪：通过 KnowledgeBase.metadata_json 记录导入/重建进度

不包含硬编码的文件类型映射规则，文件解析由 DocumentParser（AI/规则混合）处理。
"""
import io
import uuid
import zipfile
from typing import List, Optional, Tuple

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.parsing.parser import DocumentParser
from app.ai.rag.text_utils import strip_line_number_prefix
from app.models.document import (
    KnowledgeBase, KnowledgeChunk, Document, DocumentType, DocParseStatus,
)
from app.models.general_knowledge import (
    GeneralKnowledgeBase, GeneralKnowledgeChunk, GeneralDocCategory,
)
from app.services.embedding_service import get_embedding_service


# 批量导入支持的单文件大小上限（50MB）
_MAX_FILE_SIZE = 50 * 1024 * 1024
# 支持的文档扩展名（仅做基础过滤，具体解析由 DocumentParser 路由）
_SUPPORTED_EXTS = {"pdf", "docx", "doc", "txt", "md", "html", "htm"}


class KnowledgeService:
    """知识库管理服务（覆盖历史知识库 + 通用知识库）"""

    def __init__(self):
        self._parser = DocumentParser()
        self._embedding = get_embedding_service()

    # ------------------------------------------------------------------
    # 批量导入
    # ------------------------------------------------------------------
    async def batch_import(
        self,
        session: AsyncSession,
        kb_id: uuid.UUID,
        zip_bytes: bytes,
        *,
        is_general: bool = False,
        created_by: Optional[uuid.UUID] = None,
    ) -> dict:
        """ZIP 批量导入知识库文档

        - 解压 → 逐文件解析 → 切块入库 → 批量向量化
        - 进度写入 KnowledgeBase.metadata_json.import_progress
        - 返回 {total, success, failed, chunks, errors}
        """
        kb = await self._get_kb(session, kb_id, is_general)
        if kb is None:
            raise ValueError("知识库不存在")

        # 初始化进度
        await self._update_progress(session, kb, is_general, {
            "status": "running",
            "total": 0,
            "success": 0,
            "failed": 0,
            "chunks": 0,
        })

        files = self._extract_zip(zip_bytes)
        await self._update_progress(session, kb, is_general, {
            "status": "running", "total": len(files),
        })

        result = {"total": len(files), "success": 0, "failed": 0, "chunks": 0, "errors": []}
        for filename, content in files:
            try:
                if len(content) > _MAX_FILE_SIZE:
                    raise ValueError(f"文件过大: {len(content)} bytes (上限 {_MAX_FILE_SIZE})")
                chunk_count = await self._import_single_file(
                    session, kb, filename, content, is_general, created_by
                )
                result["success"] += 1
                result["chunks"] += chunk_count
            except Exception as e:
                logger.warning(f"批量导入文件 {filename} 失败: {e}")
                result["failed"] += 1
                result["errors"].append({"file": filename, "error": str(e)})

            # 更新进度
            await self._update_progress(session, kb, is_general, {
                "success": result["success"],
                "failed": result["failed"],
                "chunks": result["chunks"],
            })

        await self._update_progress(session, kb, is_general, {
            "status": "done",
        })
        return result

    def _extract_zip(self, zip_bytes: bytes) -> List[Tuple[str, bytes]]:
        """解压 ZIP，返回 [(filename, content), ...]（仅文件，跳过目录）"""
        files = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                ext = info.filename.lower().rsplit(".", 1)[-1] if "." in info.filename else ""
                if ext not in _SUPPORTED_EXTS:
                    continue
                files.append((info.filename, zf.read(info.filename)))
        return files

    async def _import_single_file(
        self,
        session: AsyncSession,
        kb,
        filename: str,
        content: bytes,
        is_general: bool,
        created_by: Optional[uuid.UUID],
    ) -> int:
        """导入单个文件：解析 → 切块 → 入库（向量化由 reindex 或批量调用触发）

        P3-15 集成：
        - T15.4 写入前校验向量块数配额（超限抛 VectorQuotaError → API 层 409）
        - T15.3 切块入库前剥离行号前缀（清洗语义向量/检索关键词污染）
        """
        parse_result = await self._parser.parse(content, filename, "")
        chunk_count = len(parse_result.chunks)

        # T15.4 写入前校验配额（超限抛 VectorQuotaError）
        if chunk_count > 0:
            from app.services.vector_quota_service import get_vector_quota_service
            quota_service = get_vector_quota_service()
            await quota_service.enforce_quota(
                session, planned_count=chunk_count,
            )

        chunks_to_embed: List = []
        for idx, c in enumerate(parse_result.chunks):
            # T15.3 行号前缀剥离（清洗文本）
            cleaned_content = strip_line_number_prefix(c.content) if c.content else c.content
            if is_general:
                chunk = GeneralKnowledgeChunk(
                    knowledge_base_id=kb.id,
                    chunk_index=idx,
                    content=cleaned_content,
                    page_number=c.page_number,
                    section=c.section,
                    table_ref=c.table_ref,
                    chunk_type=c.chunk_type,
                    metadata_json=c.metadata,
                )
            else:
                chunk = KnowledgeChunk(
                    knowledge_base_id=kb.id,
                    chunk_index=idx,
                    content=cleaned_content,
                    page_number=c.page_number,
                    section=c.section,
                    table_ref=c.table_ref,
                    chunk_type=c.chunk_type,
                    metadata_json=c.metadata,
                )
            session.add(chunk)
            chunks_to_embed.append(chunk)
        await session.commit()

        # 批量向量化
        if chunks_to_embed:
            if is_general:
                await self._embed_general_chunks(session, chunks_to_embed)
            else:
                await self._embed_history_chunks(session, chunks_to_embed)
        return chunk_count

    async def _embed_history_chunks(self, session: AsyncSession, chunks: List[KnowledgeChunk]):
        """向量化历史知识库切块"""
        for i in range(0, len(chunks), 32):
            batch = chunks[i:i + 32]
            vectors = await self._embedding._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()

    async def _embed_general_chunks(self, session: AsyncSession, chunks: List[GeneralKnowledgeChunk]):
        """向量化通用知识库切块"""
        for i in range(0, len(chunks), 32):
            batch = chunks[i:i + 32]
            vectors = await self._embedding._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()

    # ------------------------------------------------------------------
    # 索引重建
    # ------------------------------------------------------------------
    async def reindex(
        self,
        session: AsyncSession,
        kb_id: uuid.UUID,
        *,
        is_general: bool = False,
    ) -> dict:
        """重新 Embedding 所有切块（清空旧向量 → 重新向量化）"""
        kb = await self._get_kb(session, kb_id, is_general)
        if kb is None:
            raise ValueError("知识库不存在")

        await self._update_progress(session, kb, is_general, {
            "reindex_status": "running", "reindex_total": 0, "reindex_done": 0,
        })

        # 统计总数
        if is_general:
            count_stmt = select(GeneralKnowledgeChunk).where(
                GeneralKnowledgeChunk.knowledge_base_id == kb_id
            )
        else:
            count_stmt = select(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_base_id == kb_id
            )
        total = len((await session.execute(count_stmt)).scalars().all())
        await self._update_progress(session, kb, is_general, {
            "reindex_total": total,
        })

        # 分批向量化
        if is_general:
            done = await self._reindex_general(session, kb_id, kb, is_general)
        else:
            done = await self._reindex_history(session, kb_id, kb, is_general)

        await self._update_progress(session, kb, is_general, {
            "reindex_status": "done", "reindex_done": done,
        })
        return {"total": total, "reindexed": done}

    async def _reindex_history(
        self, session: AsyncSession, kb_id: uuid.UUID, kb, is_general: bool
    ) -> int:
        result = await session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == kb_id)
        )
        chunks = list(result.scalars().all())
        done = 0
        for i in range(0, len(chunks), 32):
            batch = chunks[i:i + 32]
            vectors = await self._embedding._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()
            done += len(batch)
            await self._update_progress(session, kb, is_general, {"reindex_done": done})
        return done

    async def _reindex_general(
        self, session: AsyncSession, kb_id: uuid.UUID, kb, is_general: bool
    ) -> int:
        result = await session.execute(
            select(GeneralKnowledgeChunk).where(
                GeneralKnowledgeChunk.knowledge_base_id == kb_id
            )
        )
        chunks = list(result.scalars().all())
        done = 0
        for i in range(0, len(chunks), 32):
            batch = chunks[i:i + 32]
            vectors = await self._embedding._client.embed([c.content for c in batch])
            for c, vec in zip(batch, vectors):
                c.embedding = vec
            await session.commit()
            done += len(batch)
            await self._update_progress(session, kb, is_general, {"reindex_done": done})
        return done

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------
    async def switch_version(
        self,
        session: AsyncSession,
        target_kb_id: uuid.UUID,
        *,
        is_general: bool = False,
    ) -> dict:
        """版本切换：将目标知识库设为 active，同 name 的其他版本设为 inactive

        - 同一 name 下可有多个 version（如 v1.0 / v2.0）
        - 仅一个 is_active=True（当前生效版本）
        - 切换 = 将目标设为 active，同 name 其余设为 inactive
        """
        kb = await self._get_kb(session, target_kb_id, is_general)
        if kb is None:
            raise ValueError("目标知识库不存在")

        # 同 name 的所有版本置为 inactive
        Model = GeneralKnowledgeBase if is_general else KnowledgeBase
        result = await session.execute(
            select(Model).where(Model.name == kb.name)
        )
        siblings = list(result.scalars().all())
        for s in siblings:
            s.is_active = (s.id == target_kb_id)
        await session.commit()
        return {
            "name": kb.name,
            "active_version": kb.version,
            "active_id": str(kb.id),
        }

    async def archive_old_versions(
        self,
        session: AsyncSession,
        name: str,
        *,
        is_general: bool = False,
        keep_active: bool = True,
    ) -> int:
        """归档旧版本（将非 active 版本的 is_active 全部置 False）"""
        Model = GeneralKnowledgeBase if is_general else KnowledgeBase
        result = await session.execute(select(Model).where(Model.name == name))
        archived = 0
        for kb in result.scalars().all():
            if keep_active and kb.is_active:
                continue
            if kb.is_active:
                kb.is_active = False
                archived += 1
        await session.commit()
        return archived

    # ------------------------------------------------------------------
    # 标签管理（T3.3）
    # ------------------------------------------------------------------
    async def update_chunk_tags(
        self,
        session: AsyncSession,
        chunk_id: uuid.UUID,
        tags: dict,
        *,
        is_general: bool = False,
    ):
        """更新切块标签（KnowledgeChunk.tags / GeneralKnowledgeChunk.metadata_json.tags）"""
        Model = GeneralKnowledgeChunk if is_general else KnowledgeChunk
        chunk = await session.get(Model, chunk_id)
        if not chunk:
            raise ValueError("切块不存在")
        # 历史知识库切块用 tags 字段；通用知识库切块通过 metadata_json.tags
        if is_general:
            meta = dict(chunk.metadata_json or {})
            meta["tags"] = tags
            chunk.metadata_json = meta
        else:
            chunk.metadata_json = tags  # KnowledgeChunk 无 tags 列，复用 metadata_json
        await session.commit()
        await session.refresh(chunk)
        return chunk

    async def filter_chunks_by_tag(
        self,
        session: AsyncSession,
        kb_id: uuid.UUID,
        tag_key: str,
        tag_value: str,
        *,
        is_general: bool = False,
        limit: int = 100,
    ) -> List:
        """按标签筛选切块（标签存储在 metadata_json / tags JSON 中）"""
        if is_general:
            stmt = (
                select(GeneralKnowledgeChunk)
                .where(GeneralKnowledgeChunk.knowledge_base_id == kb_id)
                .where(GeneralKnowledgeChunk.metadata_json[tag_key].astext == tag_value)
                .limit(limit)
            )
        else:
            stmt = (
                select(KnowledgeChunk)
                .where(KnowledgeChunk.knowledge_base_id == kb_id)
                .where(KnowledgeChunk.metadata_json[tag_key].astext == tag_value)
                .limit(limit)
            )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # 进度查询
    # ------------------------------------------------------------------
    async def get_import_status(
        self, session: AsyncSession, kb_id: uuid.UUID, *, is_general: bool = False
    ) -> dict:
        """查询导入/重建进度"""
        kb = await self._get_kb(session, kb_id, is_general)
        if kb is None:
            raise ValueError("知识库不存在")
        meta = kb.metadata_json if hasattr(kb, "metadata_json") and kb.metadata_json else {}
        return {
            "knowledge_base_id": str(kb.id),
            "name": kb.name,
            "import_progress": meta.get("import_progress", {}),
            "reindex_progress": meta.get("reindex_progress", {}),
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    async def _get_kb(self, session: AsyncSession, kb_id: uuid.UUID, is_general: bool):
        if is_general:
            return await session.get(GeneralKnowledgeBase, kb_id)
        return await session.get(KnowledgeBase, kb_id)

    async def _update_progress(
        self, session: AsyncSession, kb, is_general: bool, progress: dict
    ):
        """更新进度（写入 metadata_json.import_progress / reindex_progress）"""
        meta = dict(kb.metadata_json or {}) if kb.metadata_json else {}
        # 区分导入进度与重建进度
        if any(k.startswith("reindex") for k in progress.keys()):
            reindex_meta = meta.get("reindex_progress", {})
            reindex_meta.update(progress)
            meta["reindex_progress"] = reindex_meta
        else:
            import_meta = meta.get("import_progress", {})
            import_meta.update(progress)
            meta["import_progress"] = import_meta
        kb.metadata_json = meta
        await session.commit()


_knowledge_service: Optional[KnowledgeService] = None


def get_knowledge_service() -> KnowledgeService:
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
