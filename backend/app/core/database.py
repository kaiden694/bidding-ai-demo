"""
数据库会话与基类
- 异步引擎（asyncpg）供 FastAPI 使用
- 同步引擎（psycopg）供 Alembic 迁移使用
"""
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# 异步引擎（业务请求使用）
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=False,  # 关闭 SQL echo（即使 dev 也用日志中间件记录慢查询，而非全量打印）
)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# 同步引擎（Alembic 迁移 / 脚本使用）
sync_engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True, echo=False)
SyncSessionLocal = sessionmaker(sync_engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：注入异步 DB 会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
