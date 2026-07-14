"""LLM 健康检查 Celery 定时任务（Phase 3 T3）

每 60s 执行：
- 并发 ping 所有 provider 的 /models 端点（不消耗 token）
- 更新 LLMProvider.is_healthy / last_check_at
- 同步刷新 LLMClient 内存缓存

注意：Celery 是同步的，需用 asyncio.run() 包装 async 调用（与 qualification_alert 一致）
"""
import asyncio

from loguru import logger

from app.core.celery_app import celery_app
from app.ai.llm.client import get_llm_client


@celery_app.task(name="llm_health_check.scan", queue="default")
def scan_llm_health():
    """每 60s 并发健康检查所有 LLM provider"""
    logger.info("[Celery] 开始 LLM provider 健康检查")
    try:
        # 先热加载，确保内存与 DB 配置一致
        client = get_llm_client()
        client.reload_providers()
        stats = asyncio.run(_check_async())
        logger.info(f"[Celery] LLM 健康检查完成: {stats}")
        return stats
    except Exception as e:
        logger.error(f"[Celery] LLM 健康检查失败: {e}")
        raise


async def _check_async() -> dict:
    """异步并发执行所有 provider 健康检查"""
    client = get_llm_client()
    results = await client.health_check_all()
    healthy = sum(1 for r in results if r.get("is_healthy"))
    unhealthy = len(results) - healthy
    return {
        "total": len(results),
        "healthy": healthy,
        "unhealthy": unhealthy,
    }
