"""
HTTP 指标采集中间件

职责：
- 拦截所有进入应用的 HTTP 请求
- 记录 method / 归一化 path / status / 耗时 到 MetricsCollector
- 路径归一化：将 UUID 替换为 {id}，避免高基数标签导致 Prometheus 内存爆炸

注意：
- 中间件执行顺序：后添加 = 外层，最先执行
- 添加顺序应在 RequestIdMiddleware 之后（更内层），避免计入库内层中间件的耗时
  但又应在外层以便捕获完整请求生命周期——此处按"贴近业务"原则放在最内层
"""
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import get_metrics_collector


# 预编译正则：UUID（8-4-4-4-12）
_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
# 纯数字 ID（如 /api/v1/users/123）
_NUMERIC_ID_RE = re.compile(r"/\d+(?=/|$)")


def _normalize_path(path: str) -> str:
    """归一化路径，避免高基数标签

    - UUID → {id}
    - 纯数字 → {id}
    例：
      /api/v1/projects/550e8400-e29b-41d4-a716-446655440000 → /api/v1/projects/{id}
      /api/v1/users/123 → /api/v1/users/{id}
    """
    path = _UUID_RE.sub("/{id}", path)
    path = _NUMERIC_ID_RE.sub("/{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """HTTP 指标采集中间件"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.perf_counter() - start
            # status_code 在异常时可能未生成，默认 500
            status = getattr(locals().get("response", None), "status_code", 500)
            path = _normalize_path(request.url.path)
            try:
                get_metrics_collector().record_http_request(
                    request.method, path, status, duration
                )
            except Exception:  # noqa: BLE001
                # 指标采集失败不影响主请求
                pass
