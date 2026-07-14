"""数据库初始化：建表 + 启用扩展 + 种子角色"""
import os

from loguru import logger
from sqlalchemy import text

from app.core.database import async_engine, AsyncSessionLocal, Base
from app.db import base  # noqa: F401  (触发所有模型注册)
from app.db.base_data import seed_all


# Phase 5 新增列清单（CREATE TABLE 不会添加到已存在的表，需 ALTER TABLE 补齐）
# 格式: (表名, 列名, 列定义 SQL)
_PHASE5_NEW_COLUMNS = [
    # P0-2 证据链：comparison_result.evidence_span_id
    ("comparison_result", "evidence_span_id", "UUID"),
    # P0-3 校准缓存：feedback_record 新增 4 字段
    ("feedback_record", "feedback_type", "VARCHAR(64)"),
    ("feedback_record", "judgment", "VARCHAR(64)"),
    ("feedback_record", "calibration_confidence", "FLOAT"),
    ("feedback_record", "calibration_scope", "VARCHAR(128)"),
    # P0-2 证据链：contract_risk.evidence_span_id
    ("contract_risk", "evidence_span_id", "UUID"),
    # P2-11 ★号废标风险：comparison_result.is_disqualifying
    ("comparison_result", "is_disqualifying", "BOOLEAN DEFAULT FALSE"),
    # 模型新增字段但表未补齐（历史遗留）
    ("knowledge_base", "metadata_json", "JSON"),
    # 多公司管理：Product / Qualification 增加 company_id 外键
    ("product", "company_id", "UUID"),
    ("qualification", "company_id", "UUID"),
]


async def _patch_phase5_columns() -> None:
    """为已存在的表补齐 Phase 5 新增列（idempotent）

    使用 PostgreSQL 的 ALTER TABLE ... ADD COLUMN IF NOT EXISTS，
    开发环境直接 create_all 不会改已存在表的 schema，需手动补。
    """
    async with async_engine.begin() as conn:
        for table, column, ddl in _PHASE5_NEW_COLUMNS:
            try:
                await conn.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {ddl}')
                )
                # 为新建列补索引（IF NOT EXISTS 由 try/except 兜底）
                if column in ("evidence_span_id", "feedback_type", "calibration_scope", "is_disqualifying"):
                    idx_name = f"ix_{table}_{column}"
                    try:
                        await conn.execute(
                            text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{column}")')
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[init_db] 补列 {table}.{column} 失败（不阻断）: {e}")
    logger.info(f"Phase 5 列补齐完成（{len(_PHASE5_NEW_COLUMNS)} 项）")


async def init_database():
    """启动时确保扩展可用 + 表存在（开发环境用；生产用 Alembic）"""
    async with async_engine.connect() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.commit()
        logger.info("PG 扩展已就绪 (vector / pg_trgm / uuid-ossp)")

    # 开发环境直接建表，生产用 alembic upgrade head
    if os.getenv("APP_ENV", "dev") == "dev":
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("开发环境：表结构已创建（生产请用 alembic）")

        # Phase 5 新增列补齐（已存在的表不会由 create_all 自动加列）
        await _patch_phase5_columns()

        # 种子数据（角色 + 权限点 + 角色-权限分配）
        async with AsyncSessionLocal() as session:
            await seed_all(session)
        logger.info("种子数据已就绪（角色/权限/分配）")
