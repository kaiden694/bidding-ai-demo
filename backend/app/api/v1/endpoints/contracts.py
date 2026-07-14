"""合同风险扫描端点"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, get_project_scope
from app.core.database import get_db
from app.models.contract import Contract, ContractRisk, ReviewStatus
from app.models.user import User
from app.schemas.contract import ContractCreate, ContractOut, ContractRiskOut, ContractReviewCreate
from app.services.contract_review_service import get_contract_review_service

router = APIRouter()


@router.post("", response_model=ContractOut, status_code=201)
async def create_contract(
    payload: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:create")),
):
    """创建合同记录（可关联已上传并解析的文档 document_id）"""
    contract = Contract(
        title=payload.title,
        project_id=payload.project_id,
        document_id=payload.document_id,
        counterparty=payload.counterparty,
        sign_date=payload.sign_date,
        effective_date=payload.effective_date,
        expire_date=payload.expire_date,
        amount=payload.amount,
        review_status=ReviewStatus.PENDING,
        created_by=current_user.id,
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return contract


@router.get("", response_model=list[ContractOut])
async def list_contracts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:view")),
    allowed_project_ids: list[uuid.UUID] | None = Depends(get_project_scope),
):
    """合同列表（应用项目级数据隔离）"""
    stmt = select(Contract).where(Contract.is_deleted == False)
    if allowed_project_ids is not None:
        stmt = stmt.where(
            (Contract.created_by == current_user.id) | (Contract.project_id.in_(allowed_project_ids))
        )
    stmt = stmt.order_by(Contract.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{contract_id}", response_model=ContractOut)
async def get_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:view")),
):
    contract = await db.get(Contract, uuid.UUID(contract_id))
    if not contract:
        raise HTTPException(404, "合同不存在")
    return contract


@router.post("/{contract_id}/review", response_model=list[ContractRiskOut], status_code=201)
async def review_contract(
    contract_id: str,
    sync: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:review")),
    response: Response = None,
):
    """合同风险扫描（v1.2 AI 主导：LLM 全文语义分析 + 轻量确定性校验，不写硬规则包）

    - 获取合同正文切块 → 调用 ContractReviewService.review → 写入 ContractRisk → 返回列表
    - 风险识别/等级/修改建议/证据链均由 LLM 语义分析产出（审查要点清单作为 Prompt 上下文）
    - 仅对日期过期、必备条款存在性做事实性/结构性轻量校验
    - sync=True（默认）: 同步执行扫描，立即返回风险列表
    - sync=False: 触发 Celery 异步任务，立即返回空列表（status=202），
      风险结果可通过 GET /{contract_id}/risks 轮询获取
    """
    contract = await db.get(Contract, uuid.UUID(contract_id))
    if not contract:
        raise HTTPException(404, "合同不存在")
    if sync:
        service = get_contract_review_service()
        risks = await service.review(db, contract)
        return risks
    else:
        from app.tasks.contract_review_task import run_contract_review_task
        run_contract_review_task.delay(str(contract.id))
        response.status_code = 202
        return []


@router.get("/{contract_id}/risks", response_model=list[ContractRiskOut])
async def list_contract_risks(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:view")),
):
    stmt = select(ContractRisk).where(ContractRisk.contract_id == uuid.UUID(contract_id))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{contract_id}/export")
async def export_risk_report(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contract:export")),
):
    """导出合同风险扫描报告 Docx（生成 → 上传 MinIO → 返回 file_key + download_url）"""
    from app.services.report_service import get_report_service

    service = get_report_service()
    try:
        file_key = await service.generate_risk_report(db, uuid.UUID(contract_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"file_key": file_key, "download_url": service.presigned_url(file_key)}
