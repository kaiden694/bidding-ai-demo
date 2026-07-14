"""
应用入口：FastAPI 主应用
- 注册中间件（CORS / 日志 / 限流 / 审计）
- 挂载路由（v1 API + 健康检查 + AI 引擎）
- 启动事件：初始化 DB / MinIO bucket
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from loguru import logger

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.telemetry import init_telemetry
from app.api.v1.api import api_router
from app.api.v1.endpoints.metrics import router as metrics_router
from app.middleware.audit import AuditMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.metrics_middleware import MetricsMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化资源，关闭时清理"""
    # 结构化 JSON 日志（先于其他初始化，保证后续日志可观测）
    setup_logging()
    logger.info(f"启动 {settings.APP_NAME} | env={settings.APP_ENV}")

    # OpenTelemetry 链路追踪（未启用或依赖缺失时静默跳过）
    init_telemetry(app)

    # 初始化基础设施
    from app.core.init_db import init_database
    from app.core.init_minio import ensure_minio_bucket
    await init_database()
    await ensure_minio_bucket()

    logger.info("基础设施初始化完成")
    yield

    logger.info("应用关闭，清理资源...")


app = FastAPI(
    title=settings.APP_NAME,
    description="基于大模型与 RAG 的智能招投标与合同合规 AI 工作台",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 审计日志中间件（拦截写操作并异步写入 audit_log 表）
app.add_middleware(AuditMiddleware)

# 请求 ID 中间件（最外层，最先执行：注入 request_id 到 contextvar，供日志/审计读取）
# 添加顺序：后添加 = 外层，故放在 AuditMiddleware 之后
app.add_middleware(RequestIdMiddleware)

# Prometheus 指标采集中间件（记录每个请求的 method/path/status/duration）
# 放在最内层（最先添加的中间件最先执行被最外层包裹）— 此处添加顺序确保指标覆盖全部链路
app.add_middleware(MetricsMiddleware)

# 速率限制中间件（基于 Redis 滑动窗口，Redis 不可用时降级放行）
app.add_middleware(RateLimitMiddleware)

# 安全响应头中间件（注入 X-Content-Type-Options / X-Frame-Options / CSP 等）
app.add_middleware(SecurityHeadersMiddleware)

# 路由挂载
app.include_router(api_router, prefix="/api/v1")

# Prometheus 指标端点（独立挂载在 /metrics，不放在 /api/v1 下，匹配 Prometheus metrics_path 配置）
app.include_router(metrics_router)


@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": app.version,
    }


@app.get("/", tags=["系统"])
async def root():
    return {"message": "Smart Bidding & Contract Compliance AI Workbench", "docs": "/docs"}
