"""
Embedding 客户端：OpenAI 兼容接口（bge-m3 / text-embedding-3 等）

支持：
- 从 DB 加载 EmbeddingProvider 配置（运行时增删，无需重启）
- DB 不可用或无记录时降级到 settings 环境变量
- 健康检查（GET /models，不消耗 token）
- 单条/批量向量化
"""
import asyncio
import threading
import time
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings


class EmbeddingClient:
    """Embedding 向量化客户端（多 provider + DB 热加载）

    使用方式：
        client = get_embedding_client()
        vec = await client.embed_one("文本")
        vecs = await client.embed(["文本1", "文本2"])
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._provider: Optional[dict] = None
        self._client: Optional[AsyncOpenAI] = None
        self._load_provider()

    # ============================================================
    # Provider 加载
    # ============================================================
    def _load_provider(self):
        """从 DB 加载启用的 EmbeddingProvider；DB 不可用时降级到 settings"""
        provider: Optional[dict] = None
        try:
            from app.core.database import SyncSessionLocal
            from app.models.embedding_provider import EmbeddingProvider
            from sqlalchemy import select

            with SyncSessionLocal() as session:
                stmt = select(EmbeddingProvider).where(
                    EmbeddingProvider.is_active == True  # noqa: E712
                ).limit(1)
                row = session.execute(stmt).scalars().first()
                if row:
                    provider = self._row_to_provider(row)
        except Exception as e:
            logger.warning(f"[EmbeddingClient] DB 加载 provider 失败，降级到 settings: {e}")

        if not provider:
            provider = self._fallback_provider()
            logger.info("[EmbeddingClient] 使用 settings 降级配置")

        with self._lock:
            self._provider = provider
            # 重建 AsyncOpenAI 客户端
            self._client = AsyncOpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"],
                timeout=60,
            )

    def reload_providers(self):
        """热加载（外部调用后立即生效）"""
        self._load_provider()
        logger.info("[EmbeddingClient] 配置已热重载")

    @staticmethod
    def _row_to_provider(row) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "base_url": row.base_url,
            "api_key": row.api_key,
            "model": row.model,
            "dim": int(row.dim or 1024),
            "is_healthy": bool(row.is_healthy),
            "is_active": bool(row.is_active),
            "_is_fallback": False,
        }

    @staticmethod
    def _fallback_provider() -> dict:
        return {
            "id": None,
            "name": "default",
            "base_url": settings.EMBEDDING_BASE_URL,
            "api_key": settings.EMBEDDING_API_KEY,
            "model": settings.EMBEDDING_MODEL,
            "dim": settings.EMBEDDING_DIM,
            "is_healthy": True,
            "is_active": True,
            "_is_fallback": True,
        }

    # ============================================================
    # 公共属性
    # ============================================================
    @property
    def provider_name(self) -> str:
        return self._provider.get("name", "unknown") if self._provider else "unknown"

    @property
    def model(self) -> str:
        return self._provider.get("model", settings.EMBEDDING_MODEL) if self._provider else settings.EMBEDDING_MODEL

    @property
    def dim(self) -> int:
        return self._provider.get("dim", settings.EMBEDDING_DIM) if self._provider else settings.EMBEDDING_DIM

    @property
    def is_fallback(self) -> bool:
        return bool(self._provider.get("_is_fallback", True)) if self._provider else True

    def get_status(self) -> dict:
        """获取当前 provider 状态（供 API 返回）"""
        if not self._provider:
            return {"name": None, "is_fallback": True, "model": settings.EMBEDDING_MODEL}
        return {
            "id": str(self._provider["id"]) if self._provider.get("id") else None,
            "name": self._provider.get("name"),
            "base_url": self._provider.get("base_url"),
            "model": self._provider.get("model"),
            "dim": self._provider.get("dim"),
            "is_healthy": self._provider.get("is_healthy"),
            "is_active": self._provider.get("is_active"),
            "is_fallback": self._provider.get("_is_fallback", True),
        }

    # ============================================================
    # 向量化接口
    # ============================================================
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化"""
        if not texts:
            return []
        if not self._client:
            raise RuntimeError("Embedding 客户端未初始化")
        resp = await self._client.embeddings.create(
            input=texts, model=self.model
        )
        return [d.embedding for d in resp.data]

    async def embed_one(self, text: str) -> list[float]:
        """单条向量化"""
        res = await self.embed([text])
        return res[0]

    # ============================================================
    # 健康检查
    # ============================================================
    async def health_check(self) -> tuple[bool, Optional[str], Optional[int]]:
        """健康检查：用一段简短文本调用 embed 接口

        返回 (is_healthy, error, latency_ms)
        """
        if not self._client:
            return False, "客户端未初始化", None
        start = time.monotonic()
        try:
            await self._client.embeddings.create(
                input=["ping"], model=self.model
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return True, None, latency_ms
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return False, f"{type(e).__name__}: {e}", latency_ms


_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
