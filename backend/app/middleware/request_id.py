"""请求 ID 中间件

功能：
- 每个请求生成唯一 request_id（UUID4）
- 注入到 contextvars（供日志读取，async 安全）
- 注入到响应头 X-Request-ID
- 从请求头 X-Request-ID 读取（如上游传入，便于跨服务链路串联）

使用：
- app.add_middleware(RequestIdMiddleware)

注意：
- contextvars 在 asyncio 中每个请求独立，不会串号
- 中间件执行顺序：后添加的先执行（外层），Request ID 应在内层（紧贴业务）
  但日志需要 request_id，故需在日志记录之前设置——通过 contextvars 实现
"""
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# 请求头名称
REQUEST_ID_HEADER = "X-Request-ID"

# 全局 contextvar（供日志 formatter 读取，async 安全）
# 默认空字符串，非请求上下文时返回空
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个请求注入唯一 request_id

    - 优先从请求头 X-Request-ID 读取（上游网关 / 前端传入）
    - 否则生成 UUID4
    - 写入 contextvar（供日志读取）+ 响应头（便于客户端排查）
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 1. 从请求头读取或生成 request_id
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        # 2. 设置到 contextvar（供日志在请求处理期间读取）
        token = request_id_var.set(request_id)

        try:
            # 3. 处理请求
            response = await call_next(request)

            # 4. 注入响应头（便于客户端 / 上游关联）
            response.headers[REQUEST_ID_HEADER] = request_id

            return response
        finally:
            # 5. 清理 contextvar（防止跨请求串号，finally 保证异常时也清理）
            request_id_var.reset(token)
