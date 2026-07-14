"""文档解析异步任务：Phase 2 转移到 Celery，释放 HTTP 请求"""
import uuid
import io
import asyncio

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal, AsyncSessionLocal
from app.core.minio_client import minio_client
from app.core.config import settings
from app.models.document import Document, DocumentChunk, DocParseStatus
from app.ai.parsing.parser import DocumentParser
from app.ai.rag.text_utils import strip_line_number_prefix


async def _embed_chunks_async(document_id: uuid.UUID):
    """异步辅助：用 async session 调用向量化服务回写 DocumentChunk.embedding"""
    from app.services.embedding_service import get_embedding_service

    async with AsyncSessionLocal() as session:
        service = get_embedding_service()
        await service.embed_document_chunks(session, document_id)


async def _enforce_quota_async(planned_count: int) -> dict:
    """异步辅助：T15.4 写入前校验向量块数配额

    VectorQuotaError 抛出后由 sync 调用方捕获，标记 doc.parse_status=FAILED。
    """
    from app.services.vector_quota_service import get_vector_quota_service
    async with AsyncSessionLocal() as session:
        service = get_vector_quota_service()
        return await service.enforce_quota(session, planned_count=planned_count)


@celery_app.task(name="parse_document", queue="parsing", bind=True, max_retries=2)
def parse_document_task(self, doc_id: str):
    """异步解析文档并切块入库 + 向量化"""
    doc_uuid = uuid.UUID(doc_id)
    logger.info(f"[Celery] 开始解析文档: {doc_id}")
    with SyncSessionLocal() as db:
        doc = db.get(Document, doc_uuid)
        if not doc:
            logger.error(f"文档不存在: {doc_id}")
            return
        try:
            doc.parse_status = DocParseStatus.PARSING
            db.commit()
            # 拉取文件
            obj = minio_client.get_object(settings.MINIO_BUCKET, doc.file_key)
            file_bytes = obj.read()
            obj.close()
            # 同步解析（在 worker 进程）
            parser = DocumentParser()
            # Note: parse 是 async，Celery sync 任务里需用 asyncio.run
            result = asyncio.run(parser.parse(file_bytes, doc.name, doc.mime_type or ""))

            # T15.4 写入前校验向量块数配额（超限抛 VectorQuotaError）
            if result.chunks:
                asyncio.run(_enforce_quota_async(len(result.chunks)))

            for idx, c in enumerate(result.chunks):
                # T15.3 行号前缀剥离（清洗语义向量/检索关键词污染）
                cleaned_content = strip_line_number_prefix(c.content) if c.content else c.content
                db.add(DocumentChunk(
                    document_id=doc.id, chunk_index=idx, content=cleaned_content,
                    page_number=c.page_number, section=c.section, table_ref=c.table_ref,
                    chunk_type=c.chunk_type, metadata_json=c.metadata,
                ))
            doc.page_count = result.page_count
            doc.metadata_json = {"parser": result.parser_used, "chunk_count": len(result.chunks)}
            # 先持久化切块，便于向量化服务查询回写
            db.commit()
            # 向量化：用 asyncio.run 包裹 async 调用，行为与同步端点一致
            asyncio.run(_embed_chunks_async(doc.id))
            doc = db.get(Document, doc_uuid)
            doc.parse_status = DocParseStatus.DONE
            db.commit()
            logger.info(f"[Celery] 文档解析完成: {doc_id}, {len(result.chunks)} 块")
        except Exception as e:
            db.rollback()
            doc = db.get(Document, doc_uuid)
            doc.parse_status = DocParseStatus.FAILED
            doc.parse_error = str(e)
            db.commit()
            # 配额超限不重试（业务校验失败，重试无意义）
            err_code = getattr(e, "error_code", None)
            if err_code == "vector_quota_exceeded":
                logger.error(f"[Celery] 文档解析失败（配额超限） {doc_id}: {e}")
                return  # 不抛出 retry
            logger.error(f"[Celery] 文档解析失败 {doc_id}: {e}")
            raise self.retry(exc=e, countdown=30)
