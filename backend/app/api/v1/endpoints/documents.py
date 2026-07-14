"""文档管理端点：上传 / 列表 / 解析 / 删除"""
import uuid
import io
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, get_project_scope
from app.core.database import get_db
from app.core.minio_client import minio_client
from app.core.config import settings
from app.models.document import Document, DocumentType, DocParseStatus
from app.models.user import User
from app.schemas.document import DocumentOut, DocumentCreate
from app.ai.parsing.parser import DocumentParser

router = APIRouter()


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: DocumentType = Form(DocumentType.OTHER),
    project_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("document:upload")),
):
    """上传文档到 MinIO 并创建记录"""
    content = await file.read()
    file_key = f"docs/{uuid.uuid4()}/{file.filename}"
    minio_client.put_object(
        settings.MINIO_BUCKET, file_key, io.BytesIO(content), length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )
    doc = Document(
        name=file.filename,
        doc_type=doc_type,
        project_id=uuid.UUID(project_id) if project_id else None,
        file_key=file_key,
        file_size=len(content),
        mime_type=file.content_type,
        parse_status=DocParseStatus.PENDING,
        created_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    project_id: Optional[str] = None,
    doc_type: Optional[DocumentType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("document:view")),
    allowed_project_ids: Optional[list[uuid.UUID]] = Depends(get_project_scope),
):
    """文档列表（应用项目级数据隔离）"""
    stmt = select(Document).where(Document.is_deleted == False)
    if project_id:
        stmt = stmt.where(Document.project_id == uuid.UUID(project_id))
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    # 项目级数据隔离：非管理员仅可访问自己创建的项目内的文档
    if allowed_project_ids is not None:
        stmt = stmt.where(
            (Document.created_by == current_user.id) | (Document.project_id.in_(allowed_project_ids))
        )
    stmt = stmt.order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{doc_id}/parse", response_model=DocumentOut)
async def parse_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("document:parse")),
):
    """解析文档：从 MinIO 拉取 → 解析 → 切块入库 → 向量化（Phase 1 同步，Phase 2 转 Celery）"""
    doc = await db.get(Document, uuid.UUID(doc_id))
    if not doc:
        raise HTTPException(404, "文档不存在")
    # 拉取文件
    obj = minio_client.get_object(settings.MINIO_BUCKET, doc.file_key)
    file_bytes = obj.read()
    obj.close()
    # 解析
    doc.parse_status = DocParseStatus.PARSING
    await db.commit()
    try:
        parser = DocumentParser()
        result = await parser.parse(file_bytes, doc.name, doc.mime_type or "")
        from app.ai.rag.chunker import chunk_text
        from app.ai.rag.text_utils import strip_line_number_prefix
        from app.models.document import DocumentChunk
        from app.services.vector_quota_service import (
            get_vector_quota_service, VectorQuotaError,
        )

        # T15.4 写入前校验向量块数配额（超限 → 409 Conflict）
        if result.chunks:
            quota_service = get_vector_quota_service()
            await quota_service.enforce_quota(
                db, planned_count=len(result.chunks),
            )

        for idx, c in enumerate(result.chunks):
            # T15.3 行号前缀剥离（清洗语义向量/检索关键词污染）
            cleaned_content = strip_line_number_prefix(c.content) if c.content else c.content
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=cleaned_content,
                page_number=c.page_number,
                section=c.section,
                table_ref=c.table_ref,
                chunk_type=c.chunk_type,
                metadata_json=c.metadata,
            )
            db.add(chunk)
        doc.page_count = result.page_count
        doc.metadata_json = {"parser": result.parser_used, "chunk_count": len(result.chunks)}
        # 先持久化切块，便于向量化服务查询回写
        await db.commit()
        # 向量化：调用 EmbeddingService 批量回写 DocumentChunk.embedding
        from app.services.embedding_service import get_embedding_service

        embedding_service = get_embedding_service()
        await embedding_service.embed_document_chunks(db, doc.id)
        doc.parse_status = DocParseStatus.DONE
        await db.commit()
        await db.refresh(doc)
        return doc
    except VectorQuotaError as e:
        # 配额超限：不修改 parse_status（保持 PARSING → 上层可重试或人工清理）
        await db.rollback()
        doc.parse_status = DocParseStatus.FAILED
        doc.parse_error = str(e)
        await db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=e.to_dict())
    except Exception as e:
        doc.parse_status = DocParseStatus.FAILED
        doc.parse_error = str(e)
        await db.commit()
        raise HTTPException(500, f"解析失败: {e}")
