"""报告端点（多产品对比报告）"""
import io
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import require_permission
from app.core.database import get_db
from app.models.user import User
from app.services.report_service import get_report_service

router = APIRouter()


class MultiReportRequest(BaseModel):
    task_ids: List[str]


@router.post("/reports/multi-comparison")
async def generate_multi_report(
    payload: MultiReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comparison:export")),
):
    """生成多产品对比报告（横向 A4 Word）"""
    if not payload.task_ids:
        raise HTTPException(400, "请至少选择一个对比任务")
    service = get_report_service()
    try:
        task_uuids = [uuid.UUID(tid) for tid in payload.task_ids]
        content = await service.generate_multi_comparison_report(db, task_uuids)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": "attachment; filename=multi_comparison_report.docx"},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"报告生成失败: {e}")
