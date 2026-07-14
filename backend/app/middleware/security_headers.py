"""安全响应头中间件

为所有响应注入安全相关的 HTTP 头：
- X-Content-Type-Options: nosniff（防 MIME 嗅探）
- X-Frame-Options: DENY（防点击劫持）
- X-XSS-Protection: 1; mode=block（防 XSS）
- Strict-Transport-Security: max-age=31536000（强制 HTTPS，仅生产）
- Content-Security-Policy: default-src 'self'（限制资源加载来源）
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: 限制浏览器 API 访问
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # 基础安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        # CSP（允许内联样式以兼容 Swagger UI / Element Plus）
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )
        # HSTS（仅生产环境，需 HTTPS）
        if settings.APP_ENV == "prod":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response
