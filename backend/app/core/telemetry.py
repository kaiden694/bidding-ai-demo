"""OpenTelemetry 链路追踪初始化

功能：
- TracerProvider 配置（OTLP exporter，可禁用）
- FastAPI instrumentation（自动追踪 HTTP 请求）
- SQLAlchemy instrumentation（自动追踪 DB 查询）
- Redis instrumentation（自动追踪 Redis 操作）

环境变量：
- OTEL_ENABLED=true/false（默认 false，开发环境禁用）
- OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
- OTEL_SERVICE_NAME=sbaw-backend
- OTEL_RESOURCE_ATTRIBUTES=service.version=1.0.0

降级策略：
- opentelemetry 未安装 或 OTEL_ENABLED=False 时，init_telemetry 静默跳过
  不影响应用启动（dev 环境可能未装 opentelemetry 依赖）
"""
from loguru import logger

from app.core.config import settings


def init_telemetry(app) -> None:
    """初始化 OpenTelemetry（在 app 启动时调用）

    - 如 OTEL_ENABLED=false 或导入失败，静默跳过（不影响应用启动）
    - 配置 TracerProvider + OTLP exporter（gRPC，端口 4317）
    - 自动 instrument FastAPI / SQLAlchemy / Redis

    Args:
        app: FastAPI 应用实例
    """
    if not settings.OTEL_ENABLED:
        # 未启用，静默跳过（dev 环境默认禁用）
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
    except ImportError:
        # opentelemetry 依赖未安装，静默跳过（不影响应用启动）
        logger.warning(
            "OpenTelemetry 依赖未安装，已跳过链路追踪初始化。"
            "如需启用，请安装 requirements.txt 中的 opentelemetry-* 依赖。"
        )
        return

    try:
        # 1. 构建 Resource（service.name + service.version）
        resource = Resource.create(
            {
                "service.name": settings.OTEL_SERVICE_NAME,
                "service.version": getattr(app, "version", "0.1.0"),
            }
        )

        # 2. 创建 TracerProvider
        provider = TracerProvider(resource=resource)

        # 3. 添加 BatchSpanProcessor（OTLP gRPC exporter，批量发送）
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,  # dev 环境用明文 gRPC，生产建议 TLS
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # 4. 设置全局 tracer
        trace.set_tracer_provider(provider)

        # 5. 自动 instrument FastAPI（追踪 HTTP 请求）
        FastAPIInstrumentor.instrument_app(app)

        # 6. 自动 instrument SQLAlchemy（追踪 DB 查询，使用同步引擎）
        try:
            from app.core.database import sync_engine

            SQLAlchemyInstrumentor().instrument(engine=sync_engine)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"SQLAlchemy instrumentation 跳过: {e}")

        # 7. 自动 instrument Redis（追踪 Redis 操作）
        try:
            RedisInstrumentor().instrument()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis instrumentation 跳过: {e}")

        logger.info(
            f"OpenTelemetry 已启用 | service={settings.OTEL_SERVICE_NAME} "
            f"| endpoint={settings.OTEL_EXPORTER_OTLP_ENDPOINT}"
        )
    except Exception as e:  # noqa: BLE001
        # 初始化失败不影响应用启动，仅记录警告
        logger.warning(f"OpenTelemetry 初始化失败，已跳过: {e}")
