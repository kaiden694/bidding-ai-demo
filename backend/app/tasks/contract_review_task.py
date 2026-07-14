"""合同风险扫描 Celery 异步任务

参考 parsing.py 的模式：SyncSessionLocal 管理状态回写，AsyncSessionLocal + asyncio.run 调用 async service。
"""
import asyncio
import uuid

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal, AsyncSessionLocal
from app.models.contract import Contract
from app.services.contract_review_service import get_contract_review_service


@celery_app.task(name="contract_review.run", queue="llm", bind=True, max_retries=2, default_retry_delay=30)
def run_contract_review_task(self, contract_id: str):
    """异步执行合同风险扫描

    流程：
    1. 用 SyncSession 校验合同存在
    2. 用 asyncio.run 包裹 async session 调用 ContractReviewService.review
    3. service 内部成功后置 review_status=reviewing
    4. 失败兜底：ReviewStatus 无 failed 状态，保持 pending 便于重试
    """
    contract_uuid = uuid.UUID(contract_id)
    logger.info(f"[Celery] 开始合同风险扫描: {contract_id}")

    # 1. 用 SyncSession 校验合同存在
    with SyncSessionLocal() as db:
        contract = db.get(Contract, contract_uuid)
        if not contract:
            logger.error(f"合同不存在: {contract_id}")
            return

    # 2. 用 asyncio.run 包裹 async session 调用审查服务
    try:
        asyncio.run(_run_review_async(contract_uuid))
        logger.info(f"[Celery] 合同风险扫描完成: {contract_id}")
    except Exception as e:
        logger.error(f"[Celery] 合同风险扫描失败 {contract_id}: {e}")
        # ReviewStatus 枚举无 failed 状态，失败时保持 pending 便于重试/重新触发
        raise self.retry(exc=e, countdown=30)


async def _run_review_async(contract_uuid: uuid.UUID):
    """异步执行审查：用 async session 加载 contract 并调用 service

    service.review 内部管理 review_status 状态转换，
    在 async session 内完成风险写入与状态持久化。
    """
    async with AsyncSessionLocal() as session:
        contract = await session.get(Contract, contract_uuid)
        if not contract:
            raise ValueError(f"合同不存在: {contract_uuid}")
        service = get_contract_review_service()
        await service.review(session, contract)
