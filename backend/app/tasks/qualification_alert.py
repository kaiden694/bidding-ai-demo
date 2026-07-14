"""资质预警 Celery 定时任务（T4.3）

每日 09:00 扫描所有资质：
- 已过期 → severity=expired
- 7 天内到期 → severity=critical
- 30 天内到期 → severity=warning
- 同一资质同一天仅生成一条预警（按 alert_date + qualification_id 去重）

设计要点（v1.2 §13 AI 优先）：
- 仅做"日期差"这一确定性事实判断，不涉及资质内容风险判定
- severity 阈值属于事实性边界（硬规则），不进入 LLM 语义层
"""
import asyncio
from datetime import date, timedelta

from loguru import logger
from sqlalchemy import select, and_

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.feedback import QualificationAlert
from app.models.qualification import Qualification


# 事实性阈值（确定性边界校验）
_WARN_DAYS = 30
_CRITICAL_DAYS = 7


@celery_app.task(name="qualification_alert.scan_daily", queue="default")
def scan_qualification_alerts_daily():
    """每日 09:00 扫描资质，生成预警记录（幂等：同资质同日不重复）"""
    logger.info("[Celery] 开始资质预警扫描")
    try:
        stats = asyncio.run(_scan_async())
        logger.info(f"[Celery] 资质预警扫描完成: {stats}")
        return stats
    except Exception as e:
        logger.error(f"[Celery] 资质预警扫描失败: {e}")
        raise


async def _scan_async() -> dict:
    """异步扫描：遍历所有有效资质 → 计算 days_remaining → 写入预警记录（去重）"""
    today = date.today()
    warn_threshold = today + timedelta(days=_WARN_DAYS)

    stats = {"total": 0, "warning": 0, "critical": 0, "expired": 0, "skipped": 0}

    async with AsyncSessionLocal() as session:
        # 拉取所有未删除、未失效且设置了 expire_date 的资质
        stmt = select(Qualification).where(
            Qualification.is_deleted == False,
            Qualification.is_valid == True,
            Qualification.expire_date.is_not(None),
        )
        result = await session.execute(stmt)
        quals = list(result.scalars().all())

        for qual in quals:
            # 仅对"即将到期（≤30天）或已过期"的资质生成预警
            if qual.expire_date > warn_threshold:
                continue

            days_remaining = (qual.expire_date - today).days
            if days_remaining <= 0:
                severity = "expired"
            elif days_remaining <= _CRITICAL_DAYS:
                severity = "critical"
            else:
                severity = "warning"

            # 幂等：同一资质同一天不重复生成
            existing_stmt = select(QualificationAlert).where(
                and_(
                    QualificationAlert.qualification_id == qual.id,
                    QualificationAlert.alert_date == today,
                )
            )
            existing = (await session.execute(existing_stmt)).scalars().first()
            if existing:
                stats["skipped"] += 1
                continue

            alert = QualificationAlert(
                qualification_id=qual.id,
                alert_date=today,
                expire_date=qual.expire_date,
                days_remaining=days_remaining,
                severity=severity,
                notified=False,
                metadata_json={"qualification_name": qual.name},
            )
            session.add(alert)
            stats["total"] += 1
            stats[severity] += 1

        await session.commit()

    return stats
