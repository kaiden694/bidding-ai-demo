"""结构化日志配置（loguru）"""
import sys
from loguru import logger

from app.core.config import settings


def setup_logging():
    """初始化日志，移除默认 handler，按级别输出"""
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.APP_LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
        backtrace=True,
        diagnose=settings.APP_ENV == "dev",
        enqueue=True,
    )
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        level=settings.APP_LOG_LEVEL,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )
