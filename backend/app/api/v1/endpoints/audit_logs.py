"""审计日志端点"""
import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.audit import AuditLog

router = APIRouter()


@router.get("", dependencies=[Depends(require_permission("audit_log:view"))])
async def list_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """审计日志列表（分页 + 多维筛选）"""
    stmt = select(AuditLog)
    conditions = []
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if action:
        conditions.append(AuditLog.action == action)
    if resource:
        conditions.append(AuditLog.resource == resource)
    if resource_id:
        conditions.append(AuditLog.resource_id == resource_id)
    if start:
        conditions.append(AuditLog.created_at >= start)
    if end:
        conditions.append(AuditLog.created_at <= end)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "username": log.username,
            "action": log.action,
            "resource": log.resource,
            "resource_id": log.resource_id,
            "ip": log.ip,
            "user_agent": log.user_agent,
            "before_value": log.before_value,
            "after_value": log.after_value,
            "detail": log.detail,
            "status": log.status,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get("/export", dependencies=[Depends(require_permission("audit_log:export"))])
async def export_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    """导出审计日志 CSV"""
    stmt = select(AuditLog)
    conditions = []
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if action:
        conditions.append(AuditLog.action == action)
    if resource:
        conditions.append(AuditLog.resource == resource)
    if start:
        conditions.append(AuditLog.created_at >= start)
    if end:
        conditions.append(AuditLog.created_at <= end)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(10000)  # 导出上限 1 万条
    result = await db.execute(stmt)
    logs = result.scalars().all()

    # 生成 CSV
    output = io.StringIO()
    output.write("\ufeff")  # BOM 让 Excel 正确识别 UTF-8
    writer = csv.writer(output)
    writer.writerow(["时间", "用户ID", "用户名", "操作", "资源", "资源ID", "IP", "状态", "详情"])
    for log in logs:
        writer.writerow([
            log.created_at.isoformat() if log.created_at else "",
            str(log.user_id) if log.user_id else "",
            log.username or "",
            log.action or "",
            log.resource or "",
            log.resource_id or "",
            log.ip or "",
            log.status or "",
            log.detail or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )
