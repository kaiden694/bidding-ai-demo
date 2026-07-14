"""Redis 缓存工具

功能：
- 缓存装饰器：@cached(ttl=300, key_prefix="...")
- 缓存失效：按 key 模式批量删除
- 应用场景：权限点列表 / 知识库列表 / 用户权限

使用：
    from app.core.cache import cached, invalidate_cache

    @cached(ttl=300, key_prefix="permissions")
    async def get_permissions(db):
        ...

    # 失效缓存
    await invalidate_cache("permissions:*")

降级策略：Redis 不可用时直接执行原函数（不阻塞业务），仅记录异常
"""
import hashlib
import functools
import json
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Redis 客户端（延迟初始化）
_redis_client = None


async def get_redis():
    """获取 Redis 客户端（延迟初始化）

    Redis 不可用时返回 None，调用方需自行降级。
    单例：首次成功后复用连接，失败标记 False 避免重复尝试。
    """
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Redis 初始化失败，缓存降级直执行: {e}")
            _redis_client = False  # 标记不可用
    return _redis_client if _redis_client is not False else None


def _serialize_arg(value: Any) -> str:
    """将单个参数序列化为稳定的 cache key 片段

    支持的类型：
    - SQLAlchemy 模型实例（有 id 属性的 ORM 对象）：用 类名:id
    - 基础类型（str/int/float/bool/None）：用 repr
    - dict/list/tuple：JSON 序列化（按 key 排序保证稳定）
    - 其他对象：用 类名 + repr 截断，避免地址变化导致 key 漂移
    """
    # SQLAlchemy 模型实例 / 任意带 id 属性的 ORM 对象
    if hasattr(value, "id") and hasattr(value, "__tablename__"):
        return f"{type(value).__name__}:{value.id}"

    # None / 基础类型
    if value is None or isinstance(value, (str, int, float, bool)):
        return repr(value)

    # dict / list / tuple：JSON 序列化（sort_keys 保证稳定）
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            return repr(value)[:64]

    # 其他对象：用类名 + repr 截断（避免依赖内存地址）
    return f"{type(value).__name__}:{repr(value)[:64]}"


def _build_cache_key(prefix: str, func_name: str, args: tuple, kwargs: dict) -> str:
    """构建稳定的缓存 key

    格式：{prefix}:{func_name}:{md5(序列化参数)[:16]}
    """
    parts = [prefix, func_name]
    parts.extend(_serialize_arg(a) for a in args)
    for k in sorted(kwargs.keys()):
        parts.append(f"{k}={_serialize_arg(kwargs[k])}")
    key_data = "|".join(parts)
    key_hash = hashlib.md5(key_data.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{key_hash}"


def cached(ttl: int = 300, key_prefix: str = "cache"):
    """缓存装饰器

    Args:
        ttl: 缓存过期时间（秒），默认 5 分钟
        key_prefix: key 前缀（用于按业务模块批量失效，如 "permissions:*"）

    注意：
    - 被装饰函数须为 async
    - 参数会通过 _serialize_arg 序列化用作 cache key
    - 函数返回值须可 JSON 序列化
    - Redis 不可用 / 缓存异常时直接执行原函数（不抛错）
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            redis = await get_redis()
            if redis is None:
                # Redis 不可用，直接执行
                return await func(*args, **kwargs)

            cache_key = _build_cache_key(key_prefix, func.__name__, args, kwargs)

            try:
                # 查缓存
                cached_value = await redis.get(cache_key)
                if cached_value:
                    try:
                        return json.loads(cached_value)
                    except (json.JSONDecodeError, TypeError):
                        # 缓存值损坏，删除后重新执行
                        await redis.delete(cache_key)

                # 执行函数
                result = await func(*args, **kwargs)

                # 写缓存（result 可能不可序列化，用 default=str 兜底）
                try:
                    await redis.setex(cache_key, ttl, json.dumps(result, default=str))
                except (TypeError, ValueError) as e:
                    logger.debug(f"缓存写入失败（结果不可序列化）: {e}")

                return result
            except Exception as e:  # noqa: BLE001
                # 缓存异常，直接执行函数（降级策略）
                logger.warning(f"缓存操作异常，降级直执行: {e}")
                return await func(*args, **kwargs)

        return wrapper
    return decorator


async def invalidate_cache(pattern: str) -> int:
    """按模式批量失效缓存

    Args:
        pattern: key 模式（如 "permissions:*"），用 SCAN 迭代避免 KEYS 阻塞

    Returns:
        删除的数量（Redis 不可用时返回 0）
    """
    redis = await get_redis()
    if redis is None:
        return 0

    try:
        # 扫描匹配的 key（避免 KEYS 阻塞主库）
        count = 0
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)
            count += 1
        return count
    except Exception as e:  # noqa: BLE001
        logger.warning(f"失效缓存异常 pattern={pattern}: {e}")
        return 0


async def cache_get(key: str) -> Optional[str]:
    """直接读取缓存"""
    redis = await get_redis()
    if redis is None:
        return None
    try:
        return await redis.get(key)
    except Exception:  # noqa: BLE001
        return None


async def cache_set(key: str, value: str, ttl: int = 300) -> bool:
    """直接写入缓存"""
    redis = await get_redis()
    if redis is None:
        return False
    try:
        await redis.setex(key, ttl, value)
        return True
    except Exception:  # noqa: BLE001
        return False
