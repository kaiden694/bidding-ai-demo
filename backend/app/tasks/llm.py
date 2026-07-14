"""LLM 异步任务：批量向量化 / 比对 / 风险扫描（重 IO 任务转 Celery）"""
import asyncio

from loguru import logger

from app.core.celery_app import celery_app
from app.ai.embedding.client import get_embedding_client


@celery_app.task(name="embed_chunks", queue="llm", bind=True, max_retries=3)
def embed_chunks_task(self, chunk_ids: list[str]):
    """批量向量化文档切块"""
    logger.info(f"[Celery] 批量向量化 {len(chunk_ids)} 个切块")
    # TODO: 从 DB 拉取切块内容 → 批量 embed → 回写 embedding 列
    return {"embedded": len(chunk_ids)}
