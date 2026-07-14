"""资质台账端点

T4.2: CRUD + POST /{id}/extract（OCR+LLM 字段提取）+ GET /expiring（即将过期列表）
T4.4: POST /{id}/upload-certificate（上传证书 PDF 自动创建 Document + 关联资质）
"""
import io
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.config import settings
from app.core.database import get_db
from app.core.minio_client import minio_client
from app.models.company import Company
from app.models.document import Document, DocumentType, DocParseStatus
from app.models.feedback import QualificationAlert
from app.models.qualification import Qualification, QualificationType
from app.models.user import User
from app.schemas.qualification import (
    QualificationAlertOut,
    QualificationCreate,
    QualificationOut,
    QualificationUpdate,
)
from app.services.qualification_service import get_qualification_service

router = APIRouter()


# ============================================================
# CRUD
# ============================================================

@router.post("", response_model=QualificationOut, status_code=status.HTTP_201_CREATED)
async def create_qualification(
    payload: QualificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:create")),
):
    """创建资质台账记录"""
    qual = Qualification(**payload.model_dump(), created_by=current_user.id)
    db.add(qual)
    await db.commit()
    await db.refresh(qual)
    return qual


@router.get("", response_model=list[QualificationOut])
async def list_qualifications(
    qual_type: Optional[QualificationType] = None,
    company_id: Optional[str] = None,
    supplier_name: Optional[str] = None,
    is_valid: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:view")),
):
    """资质列表（支持按类型 / 公司 / 供应商 / 有效性过滤）"""
    stmt = (
        select(Qualification, Company)
        .outerjoin(Company, Qualification.company_id == Company.id)
        .where(Qualification.is_deleted == False)
    )
    if qual_type:
        stmt = stmt.where(Qualification.qual_type == qual_type)
    if company_id:
        stmt = stmt.where(Qualification.company_id == uuid.UUID(company_id))
    if supplier_name:
        stmt = stmt.where(Qualification.supplier_name.ilike(f"%{supplier_name}%"))
    if is_valid is not None:
        stmt = stmt.where(Qualification.is_valid == is_valid)
    stmt = stmt.order_by(Qualification.created_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    # 附加 company_name / company_type
    out = []
    for qual, company in rows:
        item = QualificationOut(
            id=qual.id,
            name=qual.name,
            qual_type=qual.qual_type,
            cert_number=qual.cert_number,
            issuer=qual.issuer,
            scope=qual.scope,
            issue_date=qual.issue_date,
            expire_date=qual.expire_date,
            company_id=qual.company_id,
            company_name=company.name if company else None,
            company_type=company.company_type.value if company else None,
            owner=qual.owner,
            supplier_name=qual.supplier_name,
            document_id=qual.document_id,
            is_valid=qual.is_valid,
            metadata_json=qual.metadata_json,
            created_at=qual.created_at,
        )
        out.append(item)
    return out


@router.get("/expiring", response_model=list[QualificationOut])
async def list_expiring(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:view")),
):
    """即将过期的资质列表（默认 ≤30 天，含已过期）"""
    threshold = date.today() + timedelta(days=max(days, 0))
    stmt = (
        select(Qualification)
        .where(
            Qualification.is_deleted == False,
            Qualification.expire_date.is_not(None),
            Qualification.expire_date <= threshold,
        )
        .order_by(Qualification.expire_date.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/alerts", response_model=list[QualificationAlertOut])
async def list_alerts(
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:view")),
):
    """查询资质预警记录（由 Celery 定时任务写入）"""
    stmt = select(QualificationAlert).order_by(QualificationAlert.alert_date.desc())
    if severity:
        stmt = stmt.where(QualificationAlert.severity == severity)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{qual_id}", response_model=QualificationOut)
async def get_qualification(
    qual_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:view")),
):
    qual = await db.get(Qualification, uuid.UUID(qual_id))
    if not qual or qual.is_deleted:
        raise HTTPException(404, "资质不存在")
    return qual


@router.patch("/{qual_id}", response_model=QualificationOut)
async def update_qualification(
    qual_id: str,
    payload: QualificationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:update")),
):
    qual = await db.get(Qualification, uuid.UUID(qual_id))
    if not qual or qual.is_deleted:
        raise HTTPException(404, "资质不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(qual, k, v)
    await db.commit()
    await db.refresh(qual)
    return qual


@router.delete("/{qual_id}", status_code=204)
async def delete_qualification(
    qual_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:delete")),
):
    """软删除资质记录"""
    qual = await db.get(Qualification, uuid.UUID(qual_id))
    if not qual or qual.is_deleted:
        raise HTTPException(404, "资质不存在")
    qual.is_deleted = True
    await db.commit()


# ============================================================
# T4.4：资质-文档关联（上传证书 PDF 自动创建 Document + 关联资质）
# ============================================================

@router.post("/{qual_id}/upload-certificate", response_model=QualificationOut)
async def upload_certificate(
    qual_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:update")),
):
    """上传资质证书 PDF：
    1. 上传至 MinIO
    2. 自动创建 Document（doc_type=QUALIFICATION）
    3. 关联到 Qualification.document_id

    不在此处触发解析，调用 /qualifications/{id}/extract 触发 OCR+LLM 字段提取
    """
    qual = await db.get(Qualification, uuid.UUID(qual_id))
    if not qual or qual.is_deleted:
        raise HTTPException(404, "资质不存在")

    try:
        content = await file.read()
        if not content:
            raise HTTPException(400, "上传文件为空")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"读取文件失败: {e}")

    # 上传 MinIO
    file_key = f"qualifications/{qual.id}/{file.filename}"
    try:
        minio_client.put_object(
            settings.MINIO_BUCKET,
            file_key,
            io.BytesIO(content),
            length=len(content),
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(500, f"MinIO 上传失败: {e}")

    # 创建 Document（doc_type=QUALIFICATION）
    doc = Document(
        name=file.filename,
        doc_type=DocumentType.QUALIFICATION,
        file_key=file_key,
        file_size=len(content),
        mime_type=file.content_type,
        parse_status=DocParseStatus.PENDING,
        created_by=current_user.id,
    )
    db.add(doc)
    await db.flush()  # 拿到 doc.id

    # 关联到资质
    qual.document_id = doc.id
    await db.commit()
    await db.refresh(qual)
    return qual


# ============================================================
# T4.2：OCR+LLM 字段提取
# ============================================================

@router.post("/{qual_id}/extract")
async def extract_fields(
    qual_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("qualification:extract")),
):
    """OCR + LLM 提取资质证书字段（需先上传证书）"""
    service = get_qualification_service()
    try:
        return await service.extract_fields(db, uuid.UUID(qual_id))
    except ValueError as e:
        raise HTTPException(400, str(e))
