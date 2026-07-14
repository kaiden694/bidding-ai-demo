"""参数偏离比对端点"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, get_project_scope
from app.core.database import get_db
from app.models.comparison import ComparisonTask, ComparisonResult
from app.models.user import User
from app.schemas.comparison import ComparisonCreate, ComparisonTaskOut, ComparisonResultOut
from app.services.comparison_service import get_comparison_service

router = APIRouter()


@router.post("", response_model=ComparisonTaskOut, status_code=201)
async def create_comparison_task(
    payload: ComparisonCreate,
    sync: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comparison:create")),
):
    """创建参数偏离比对任务
    - 方式 A: tender_doc_id + spec_doc_id（招标文件 vs 规格书文档）
    - 方式 B: tender_doc_id + product_id（招标文件 vs 产品中心选型产品 specs）
    - sync=True（默认）: 同步执行比对，立即返回结果
    - sync=False: 触发 Celery 异步任务，立即返回 task（status=pending），
      结果可通过 GET /{task_id}/results 轮询获取
    """
    if not payload.spec_doc_id and not payload.product_id:
        raise HTTPException(400, "必须提供 spec_doc_id 或 product_id 之一")
    task = ComparisonTask(
        project_id=payload.project_id,
        tender_doc_id=payload.tender_doc_id,
        spec_doc_id=payload.spec_doc_id,
        product_id=payload.product_id,
        status="pending",
        created_by=current_user.id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    if sync:
        # 同步调用比对服务（Phase 1 默认）
        service = get_comparison_service()
        try:
            await service.compare(db, task)
        except Exception as e:
            raise HTTPException(500, f"比对失败: {e}")
        await db.refresh(task)
    else:
        # 触发 Celery 异步任务
        from app.tasks.comparison_task import run_comparison_task
        run_comparison_task.delay(str(task.id))
    return task


@router.get("/{task_id}", response_model=ComparisonTaskOut)
async def get_comparison_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comparison:view")),
):
    task = await db.get(ComparisonTask, uuid.UUID(task_id))
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/results", response_model=list[ComparisonResultOut])
async def get_comparison_results(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comparison:view")),
):
    stmt = select(ComparisonResult).where(ComparisonResult.task_id == uuid.UUID(task_id))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{task_id}/export")
async def export_comparison_report(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("comparison:export")),
):
    """导出参数偏离比对报告 Docx（生成 → 上传 MinIO → 返回 file_key + download_url）"""
    from app.services.report_service import get_report_service

    service = get_report_service()
    try:
        file_key = await service.generate_comparison_report(db, uuid.UUID(task_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"file_key": file_key, "download_url": service.presigned_url(file_key)}
