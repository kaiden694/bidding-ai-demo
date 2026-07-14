"""MinIO 初始化：确保 bucket 存在"""
from loguru import logger
from minio import Minio
from minio.error import S3Error
from urllib3.poolmanager import PoolManager

from app.core.config import settings


async def ensure_minio_bucket():
    """启动时确保默认 bucket 存在（不存在则创建）

    超时 3s + 重试 1 次，避免 MinIO 不可用时长时间阻塞启动
    """
    try:
        # 自定义 HTTP 客户端：短超时 + 少重试
        _http_client = PoolManager(
            num_pools=1,
            maxsize=1,
            timeout=3.0,
            retries=1,
        )
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
            http_client=_http_client,
        )
        if not client.bucket_exists(settings.MINIO_BUCKET):
            client.make_bucket(settings.MINIO_BUCKET)
            logger.info(f"MinIO bucket 已创建: {settings.MINIO_BUCKET}")
        else:
            logger.info(f"MinIO bucket 已存在: {settings.MINIO_BUCKET}")
    except S3Error as e:
        logger.error(f"MinIO 初始化失败（S3Error）: {e}")
        # MinIO 为辅助资源（仅用于导出报告），缺失不应阻塞 API 启动
        # 不 raise：降级运行，导出报告端点在调用时再尝试连接或返回 503
    except Exception as e:  # noqa: BLE001  连接不可达等运行期错误
        logger.warning(f"MinIO 暂不可用，已降级运行（导出报告功能将失败）: {type(e).__name__}: {e}")
