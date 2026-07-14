"""MinIO 客户端单例

配置：连接超时 3s + 重试 1 次（避免 MinIO 不可用时长时间阻塞）
"""
from urllib3.poolmanager import PoolManager
from minio import Minio

from app.core.config import settings

# 自定义 HTTP 客户端：超时 3s，重试 1 次（默认 3 次太慢）
_http_client = PoolManager(
    num_pools=10,
    maxsize=10,
    timeout=3.0,
    retries=1,  # 仅重试 1 次（默认 3 次会阻塞 9s+）
)

minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
    http_client=_http_client,
)
