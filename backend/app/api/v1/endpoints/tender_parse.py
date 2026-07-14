"""招标文档结构化解析端点"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.document import Document, DocParseStatus
from app.models.user import User
from app.services.tender_parse_service import get_tender_parse_service

router = APIRouter()


@router.post("/documents/{document_id}/analyze-tender")
async def analyze_tender(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("document:parse")),
):
    """解析招标文档，提取 TOC + 13 维度结构化信息"""
    doc = await db.get(Document, uuid.UUID(document_id))
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.parse_status != DocParseStatus.DONE:
        raise HTTPException(400, "文档尚未解析完成，请先解析")

    service = get_tender_parse_service()
    try:
        result = await service.analyze_project(db, doc)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"解析失败: {e}")


@router.post("/documents/{document_id}/extract-disqualifying")
async def extract_disqualifying(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("document:parse")),
):
    """提取废标条款（★号条款 + is_disqualifying）"""
    doc = await db.get(Document, uuid.UUID(document_id))
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.parse_status != DocParseStatus.DONE:
        raise HTTPException(400, "文档尚未解析完成")

    service = get_tender_parse_service()
    try:
        result = await service.analyze_project(db, doc)
        return {
            "document_id": document_id,
            "disqualifying_items": result.get("disqualifying_items", []),
            "mandatory_items": [
                item for item in result.get("tech_spec", [])
                if isinstance(item, dict) and item.get("is_mandatory")
            ],
        }
    except Exception as e:
        raise HTTPException(500, f"提取失败: {e}")
