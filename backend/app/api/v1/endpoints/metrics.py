"""
Prometheus 指标端点

GET /metrics 返回 Prometheus 文本格式指标，供 Prometheus 抓取

指标来源：
1. MetricsCollector 内存计数器（HTTP / LLM / Celery）
2. async_engine.pool（DB 连接池状态）
3. LLMClient 状态（熔断器活跃情况）
4. 业务聚合查询（活跃用户数、项目数按状态）

设计要点：
- /metrics 是公开端点（无认证），生产环境建议在 Ingress 层限制访问 IP
- 业务指标查询失败不影响其他指标输出（每项独立 try/except）
- DB 查询使用独立会话，不依赖请求作用域
"""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response
from loguru import logger
from sqlalchemy import func, select

from app.core.metrics import get_metrics_collector


router = APIRouter()


def _fmt_labels(**labels) -> str:
    """构建 Prometheus 标签段：{key="value",key2="value2"}"""
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in labels.items()]
    return "{" + ",".join(parts) + "}"


def _collect_db_pool_metrics(lines: list[str]) -> None:
    """DB 连接池指标：从 async_engine.pool 获取

    - db_pool_size：连接池配置大小
    - db_pool_checked_out：已检出（正在使用）连接数
    - db_pool_overflow：溢出连接数
    """
    try:
        from app.core.database import async_engine

        pool = async_engine.pool
        # asyncio pool 提供 status() 文本，也可用属性读取
        size = getattr(pool, "size", lambda: 0)()
        checked_out = getattr(pool, "checkedout", lambda: 0)()
        overflow = getattr(pool, "overflow", lambda: 0)()

        lines.append("# HELP db_pool_size DB 连接池配置大小")
        lines.append("# TYPE db_pool_size gauge")
        lines.append(f"db_pool_size{_fmt_labels(pool='asyncpg')} {size}")

        lines.append("# HELP db_pool_checked_out DB 已检出（使用中）连接数")
        lines.append("# TYPE db_pool_checked_out gauge")
        lines.append(f"db_pool_checked_out{_fmt_labels(pool='asyncpg')} {checked_out}")

        lines.append("# HELP db_pool_overflow DB 溢出连接数")
        lines.append("# TYPE db_pool_overflow gauge")
        lines.append(f"db_pool_overflow{_fmt_labels(pool='asyncpg')} {overflow}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[metrics] DB 连接池指标采集失败: {e}")


def _collect_llm_circuit_breaker_metrics(lines: list[str]) -> None:
    """LLM 熔断器状态指标

    - llm_circuit_breaker_active：当前处于熔断期的 provider 数量
    """
    try:
        from app.ai.llm.client import get_llm_client

        client = get_llm_client()
        providers_status = client.list_providers_status()
        active_count = sum(1 for p in providers_status if p.get("in_circuit_break"))

        lines.append("# HELP llm_circuit_breaker_active 当前处于熔断期的 LLM provider 数量")
        lines.append("# TYPE llm_circuit_breaker_active gauge")
        lines.append(f"llm_circuit_breaker_active {active_count}")

        # 每个 provider 健康状态（gauge：1 健康 / 0 不健康）
        lines.append("# HELP llm_provider_healthy LLM provider 健康状态（1=健康 0=不健康）")
        lines.append("# TYPE llm_provider_healthy gauge")
        for p in providers_status:
            name = p.get("name") or "unknown"
            healthy = 1 if p.get("is_healthy") else 0
            lines.append(f'llm_provider_healthy{_fmt_labels(provider=name)} {healthy}')
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[metrics] LLM 熔断器指标采集失败: {e}")


async def _collect_business_metrics(lines: list[str]) -> None:
    """业务指标：活跃用户数 + 项目数按状态

    - active_users_total：24h 内登录过的用户数（基于 audit_log 或 user.updated_at）
    - projects_total{status}：项目数按状态分组
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.project import Project, ProjectStatus
        from app.models.user import User

        async with AsyncSessionLocal() as session:
            # 活跃用户数（24h 内 updated_at）
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            try:
                stmt = select(func.count(User.id)).where(
                    User.updated_at >= since,
                    User.is_deleted.is_(False),
                )
                active_users = (await session.execute(stmt)).scalar() or 0
                lines.append("# HELP active_users_total 24h 内活跃用户数")
                lines.append("# TYPE active_users_total gauge")
                lines.append(f"active_users_total {active_users}")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[metrics] 活跃用户指标采集失败: {e}")

            # 项目数按状态分组
            try:
                stmt = (
                    select(Project.status, func.count(Project.id))
                    .where(Project.is_deleted.is_(False))
                    .group_by(Project.status)
                )
                rows = (await session.execute(stmt)).all()
                lines.append("# HELP projects_total 项目数（按状态）")
                lines.append("# TYPE projects_total gauge")
                # 确保所有状态都有输出（即便为 0），便于 Grafana 面板稳定展示
                status_counts = {row[0].value if hasattr(row[0], "value") else row[0]: row[1] for row in rows}
                for status_enum in ProjectStatus:
                    name = status_enum.value
                    count = status_counts.get(name, 0)
                    lines.append(f'projects_total{_fmt_labels(status=name)} {count}')
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[metrics] 项目数指标采集失败: {e}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[metrics] 业务指标采集失败: {e}")


@router.get("/metrics")
async def metrics():
    """返回 Prometheus 格式指标

    - 无需认证（生产环境在 Ingress 层限制访问 IP）
    - DB / LLM / 业务指标采集失败不影响内存计数器指标输出
    """
    # 1. 内存计数器指标（HTTP / LLM / Celery）
    collector = get_metrics_collector()
    lines: list[str] = [collector.format_prometheus()]

    # 2. DB 连接池指标
    _collect_db_pool_metrics(lines)

    # 3. LLM 熔断器状态
    _collect_llm_circuit_breaker_metrics(lines)

    # 4. 业务聚合指标（异步）
    await _collect_business_metrics(lines)

    metrics_text = "\n".join(lines)
    return Response(content=metrics_text, media_type="text/plain; version=0.0.4; charset=utf-8")
