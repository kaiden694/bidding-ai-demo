"""速率限制中间件（基于 Redis 滑动窗口算法）

规则：
- 全局：100 req/min per IP
- 登录端点：5 req/min per IP（防暴力破解）
- AI 端点：10 req/min per user（防 LLM 滥用）
- 白名单：/health /metrics /docs /redoc /openapi.json

降级策略：Redis 不可用时放行（不阻塞业务），仅记录警告日志
"""
import time
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

# 白名单路径（不做限流）
WHITELIST_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}

# 路径规则：匹配前缀 → (limit, window_seconds)
RATE_RULES = [
    # 登录：5 req/min
    ("/api/v1/auth/login", 5, 60),
    # AI 助手：10 req/min
    ("/api/v1/assistant/chat", 10, 60),
    # AI 比对：10 req/min
    ("/api/v1/comparison", 10, 60),
    # 标书生成：5 req/min
    ("/api/v1/projects", 5, 60),
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""

    # Redis 不可用时的降级缓存时间（秒），避免每次请求都尝试连接
    _RETRY_INTERVAL = 30

    def __init__(self, app):
        super().__init__(app)
        self._redis = None  # 延迟初始化
        self._last_check_at = 0.0  # 上次检查 Redis 可用性的时间
        self._redis_unavailable = False  # Redis 不可用标志

    async def _get_redis(self):
        """延迟获取 Redis 连接（避免启动时阻塞）

        如 Redis 不可用，标记并在 _RETRY_INTERVAL 秒内不再重试，
        避免每个请求都等待连接超时拖慢响应。
        """
        import time as _time
        now = _time.time()

        # Redis 已确认不可用，在重试间隔内直接返回 None
        if self._redis_unavailable and (now - self._last_check_at) < self._RETRY_INTERVAL:
            return None

        # 首次或重试间隔已过，尝试连接
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=0.5,  # 连接超时 0.5s（避免长时间等待）
                socket_timeout=0.5,          # 操作超时 0.5s
            )
            # 立即 ping 测试，确认 Redis 真正可用
            await client.ping()
            self._redis = client
            self._redis_unavailable = False
            return client
        except Exception as e:
            # 连接失败，标记不可用，记录时间
            if not self._redis_unavailable:
                logger.warning(f"Redis 不可用，速率限制降级 {self._RETRY_INTERVAL}s: {e}")
            self._redis_unavailable = True
            self._last_check_at = now
            return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 白名单放行
        if path in WHITELIST_PATHS:
            return await call_next(request)

        # 匹配限流规则
        rule = self._match_rule(path)
        if rule is None:
            # 全局限流：100 req/min per IP
            rule = (100, 60)

        limit, window = rule
        client_ip = self._get_client_ip(request)
        key = f"ratelimit:{client_ip}:{path}"

        # 获取 Redis
        redis = await self._get_redis()
        if redis is None:
            # Redis 不可用，放行（降级策略）
            return await call_next(request)

        try:
            # 滑动窗口：ZSET + 时间戳
            now = time.time()
            pipe = redis.pipeline()
            # 移除窗口外的记录
            pipe.zremrangebyscore(key, 0, now - window)
            # 添加当前请求
            pipe.zadd(key, {str(now): now})
            # 统计窗口内请求数
            pipe.zcard(key)
            # 设置 key 过期时间（避免内存泄漏）
            pipe.expire(key, window)
            results = await pipe.execute()
            count = results[2]

            if count > limit:
                logger.warning(f"速率限制触发: ip={client_ip} path={path} count={count}/{limit}")
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "请求过于频繁，请稍后再试",
                        "retry_after": window,
                    },
                    headers={
                        "Retry-After": str(window),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            # 放行，并在响应头添加限流信息
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
            return response

        except Exception as e:
            # Redis 异常，放行（降级策略）
            logger.warning(f"速率限制异常，放行: {e}")
            return await call_next(request)

    def _match_rule(self, path: str) -> Optional[tuple]:
        """匹配路径规则"""
        for prefix, limit, window in RATE_RULES:
            if path.startswith(prefix):
                return (limit, window)
        return None

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP（支持代理转发）"""
        # X-Forwarded-For（Nginx/Ingress 转发）
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        # X-Real-IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        # 直连
        return request.client.host if request.client else "unknown"
