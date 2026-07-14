"""审计日志中间件

自动拦截 POST/PUT/DELETE 请求，异步写入 audit_log 表。
单条记录耗时 ≤ 10ms，不阻塞主请求。

设计要点：
- before_value：UPDATE/DELETE 时查询原值（业务层负责，中间件只记录请求/响应）
- after_value：从响应体提取（若为 JSON）
- 异步写入：使用 asyncio.create_task fire-and-forget
"""
import asyncio
import json
import uuid
from typing import Optional, Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.audit import AuditLog


# 需要审计的 HTTP 方法
AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 资源映射：从 URL 路径提取 resource 类型
# 例：/api/v1/contracts/{id}/review → resource="contract"
URL_RESOURCE_MAP = {
    "auth": "auth",
    "users": "user",
    "roles": "role",
    "organizations": "organization",
    "permissions": "permission",
    "documents": "document",
    "contracts": "contract",
    "comparison": "comparison",
    "projects": "project",
    "knowledge": "knowledge",
    "knowledge-bases": "knowledge",
    "general-knowledge": "general_knowledge",
    "products": "product",
    "qualifications": "qualification",
    "assistant": "assistant",
    "audit-logs": "audit_log",
}

# 登录端点特殊处理
LOGIN_PATH = "/api/v1/auth/login"


def _extract_resource(path: str) -> Optional[str]:
    """从 URL 路径提取资源类型"""
    # 去掉 /api/v1/ 前缀
    if path.startswith("/api/v1/"):
        segments = path[len("/api/v1/"):].split("/")
    else:
        segments = path.strip("/").split("/")
    if not segments or not segments[0]:
        return None
    return URL_RESOURCE_MAP.get(segments[0], segments[0])


def _extract_action(method: str, path: str) -> str:
    """从 HTTP 方法 + URL 推断操作类型"""
    if LOGIN_PATH in path:
        return "login"
    if "/parse" in path:
        return "parse"
    if "/review" in path:
        return "review"
    if "/export" in path:
        return "export"
    if "/reindex" in path:
        return "reindex"
    if "/import" in path or "/batch-import" in path:
        return "import"
    if "/reset-password" in path:
        return "reset_password"
    if "/permissions" in path:
        return "assign_permissions"
    method_map = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
    return method_map.get(method, method.lower())


def _extract_resource_id(path: str) -> Optional[str]:
    """从 URL 提取资源 ID（UUID 格式的路径段）"""
    segments = path.strip("/").split("/")
    for seg in segments:
        # UUID 格式：8-4-4-4-12
        try:
            uuid.UUID(seg)
            return seg
        except (ValueError, TypeError):
            continue
    return None


async def _write_audit_log(
    user_id: Optional[uuid.UUID],
    username: Optional[str],
    action: str,
    resource: Optional[str],
    resource_id: Optional[str],
    ip: str,
    user_agent: str,
    before_value: Optional[dict],
    after_value: Optional[dict],
    detail: Optional[str],
    status_code: int,
):
    """异步写入审计日志（fire-and-forget）"""
    try:
        async with AsyncSessionLocal() as session:
            log = AuditLog(
                user_id=user_id,
                username=username,
                action=action,
                resource=resource,
                resource_id=resource_id,
                ip=ip,
                user_agent=user_agent[:256] if user_agent else None,
                before_value=before_value,
                after_value=after_value,
                detail=detail or f"HTTP {status_code}",
                status="success" if status_code < 400 else "failed",
            )
            session.add(log)
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"审计日志写入失败: {e}")


class AuditMiddleware(BaseHTTPMiddleware):
    """审计日志中间件"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 仅审计写操作
        if request.method not in AUDITED_METHODS:
            return await call_next(request)

        path = request.url.path
        # 跳过非业务路径
        if not path.startswith("/api/v1/") and LOGIN_PATH not in path:
            return await call_next(request)

        # 提取用户信息（从 Authorization header）
        auth_header = request.headers.get("authorization", "")
        user_id = None
        username = None
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            payload = decode_token(token)
            if payload and payload.get("type") == "access":
                try:
                    user_id = uuid.UUID(payload.get("sub", ""))
                except ValueError:
                    pass
                username = payload.get("username")

        # 提取 IP 和 UA
        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")

        # 提取请求体（用于 after_value）
        before_value = None
        try:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    before_value = json.loads(body_bytes)
                except (json.JSONDecodeError, ValueError):
                    before_value = None
        except Exception:  # noqa: BLE001
            pass

        # 调用下游
        response = await call_next(request)

        # 提取响应体（仅 JSON 响应）
        after_value = None
        if response.headers.get("content-type", "").startswith("application/json"):
            try:
                # 读取响应体后需要重新放回，避免下游拿不到
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk

                # 重新构造响应
                response = Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
                if response_body:
                    try:
                        after_value = json.loads(response_body)
                        # 避免记录过大
                        if isinstance(after_value, dict):
                            after_value = {
                                k: v for k, v in after_value.items()
                                if k in ("id", "title", "name", "code", "status", "message", "username")
                            }
                    except (json.JSONDecodeError, ValueError):
                        after_value = None
            except Exception as e:  # noqa: BLE001
                logger.debug(f"审计日志读取响应体失败: {e}")

        # 提取审计字段
        action = _extract_action(request.method, path)
        resource = _extract_resource(path)
        resource_id = _extract_resource_id(path)

        # fire-and-forget 异步写入
        asyncio.create_task(_write_audit_log(
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_value=before_value,
            after_value=after_value,
            detail=None,
            status_code=response.status_code,
        ))

        return response
