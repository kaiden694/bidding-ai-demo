"""参数偏离比对 Celery 异步任务

参考 parsing.py 的模式：SyncSessionLocal 管理状态回写，AsyncSessionLocal + asyncio.run 调用 async service。
"""
import asyncio
import uuid

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal, AsyncSessionLocal
from app.models.comparison import ComparisonTask
from app.services.comparison_service import get_comparison_service


@celery_app.task(name="comparison.run", queue="llm", bind=True, max_retries=2, default_retry_delay=30)
def run_comparison_task(self, task_id: str):
    """异步执行参数偏离比对

    流程：
    1. 用 SyncSession 提前标记 status=running，便于前端轮询
    2. 用 asyncio.run 包裹 async session 调用 ComparisonService.compare
    3. service 内部成功后置 done，异常置 failed
    4. 异常兜底：async session 不可用时用 SyncSession 置 failed
    """
    task_uuid = uuid.UUID(task_id)
    logger.info(f"[Celery] 开始参数偏离比对: {task_id}")

    # 1. 用 SyncSession 提前标记 running
    with SyncSessionLocal() as db:
        task = db.get(ComparisonTask, task_uuid)
        if not task:
            logger.error(f"比对任务不存在: {task_id}")
            return
        task.status = "running"
        db.commit()

    # 2. 用 asyncio.run 包裹 async session 调用比对服务
    try:
        asyncio.run(_run_compare_async(task_uuid))
        logger.info(f"[Celery] 参数偏离比对完成: {task_id}")
    except Exception as e:
        logger.error(f"[Celery] 参数偏离比对失败 {task_id}: {e}")
        # 兜底：service 内部已置 failed，此处仅作为 async session 异常时的兜底
        with SyncSessionLocal() as db:
            task = db.get(ComparisonTask, task_uuid)
            if task and task.status not in ("done", "failed"):
                task.status = "failed"
                task.error = str(e)
                db.commit()
        raise self.retry(exc=e, countdown=30)


async def _run_compare_async(task_uuid: uuid.UUID):
    """异步执行比对：用 async session 加载 task 并调用 service

    service.compare 内部管理 status 状态转换（running→done/failed），
    在 async session 内完成全部持久化。
    """
    async with AsyncSessionLocal() as session:
        task = await session.get(ComparisonTask, task_uuid)
        if not task:
            raise ValueError(f"比对任务不存在: {task_uuid}")
        service = get_comparison_service()
        await service.compare(session, task)
