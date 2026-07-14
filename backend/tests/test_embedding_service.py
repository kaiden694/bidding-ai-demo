"""T1.4: EmbeddingService 单元测试（mock EmbeddingClient + AsyncSession）

被测方法 embed_document_chunks 通过 select(DocumentChunk) 查询切块，再批量回写
embedding 列。此处用「站位映射类」替换 DocumentChunk 引用，使 select/where/order_by
走真实 SQLAlchemy（可编译校验），EmbeddingClient 与 AsyncSession 全部 mock。
"""
import sys
import types
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column
from pgvector.sqlalchemy import Vector

# 测试不连接真实 DB：用桩替换 app.core.database，避免 create_engine 触发
# asyncpg/psycopg 导入（测试环境未安装）。app.models 包初始化会拉入 user→database。
if "app.core.database" not in sys.modules:
    _db_stub = types.ModuleType("app.core.database")

    class _DBBase(DeclarativeBase):
        pass

    _db_stub.Base = _DBBase
    _db_stub.async_engine = None
    _db_stub.AsyncSessionLocal = None
    _db_stub.sync_engine = None
    _db_stub.SyncSessionLocal = None

    async def _get_db():  # pragma: no cover - 仅占位
        yield None

    _db_stub.get_db = _get_db
    sys.modules["app.core.database"] = _db_stub

# 提前导入被测模块，使 patch 的 dotted path 可解析
from app.services.embedding_service import EmbeddingService


# ---- 站位映射类：仅用于构建真实 Select 语句（不依赖真实 ORM 完整注册）----
class _Base(DeclarativeBase):
    pass


class _DocumentChunk(_Base):
    __tablename__ = "document_chunk"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = mapped_column(UUID(as_uuid=True))
    chunk_index = mapped_column(Integer)
    content = mapped_column(Text)
    embedding = mapped_column(Vector(8))


class TestEmbedDocumentChunks(unittest.IsolatedAsyncioTestCase):
    """覆盖 embed_document_chunks 核心路径：批量回写 embedding"""

    async def asyncSetUp(self):
        self._model_patcher = patch(
            "app.services.embedding_service.DocumentChunk", _DocumentChunk
        )
        self._model_patcher.start()
        self.addCleanup(self._model_patcher.stop)

    def _make_service(self):
        """构造 EmbeddingService，client 用 AsyncMock 替换"""
        with patch("app.services.embedding_service.get_embedding_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client
            service = EmbeddingService()
        return service, mock_client

    @staticmethod
    def _mock_session(chunks):
        """构造 mock AsyncSession，execute -> scalars().all() -> chunks"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = chunks
        session = AsyncMock()
        session.execute.return_value = mock_result
        return session

    async def test_embed_chunks_writes_embedding(self):
        """验证切块入库后 embedding 列被回写"""
        service, mock_client = self._make_service()
        # 1. mock EmbeddingClient.embed 返回固定向量
        mock_client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

        # 2. mock session.execute 查询返回模拟的 DocumentChunk 列表
        chunk1 = MagicMock()
        chunk1.content = "chunk-content-1"
        chunk2 = MagicMock()
        chunk2.content = "chunk-content-2"
        session = self._mock_session([chunk1, chunk2])

        # 3. 调用 embed_document_chunks
        document_id = uuid.uuid4()
        await service.embed_document_chunks(session, document_id)

        # 4. 断言 embed 按内容列表被调用
        mock_client.embed.assert_awaited_once_with(["chunk-content-1", "chunk-content-2"])
        # 5. 断言 commit 被调用
        session.commit.assert_awaited()
        # 6. 断言 chunk.embedding 被赋值
        self.assertEqual(chunk1.embedding, [0.1, 0.2, 0.3])
        self.assertEqual(chunk2.embedding, [0.4, 0.5, 0.6])

    async def test_embed_chunks_empty(self):
        """无切块时不报错，不调用 embed，不 commit"""
        service, mock_client = self._make_service()
        mock_client.embed = AsyncMock(return_value=[])

        session = self._mock_session([])

        document_id = uuid.uuid4()
        await service.embed_document_chunks(session, document_id)

        # 无切块：不应调用 embed，也不应 commit
        mock_client.embed.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_embed_chunks_failure(self):
        """Embedding 失败时抛异常且不 commit"""
        service, mock_client = self._make_service()
        mock_client.embed = AsyncMock(side_effect=RuntimeError("LLM down"))

        chunk1 = MagicMock()
        chunk1.content = "chunk-content-1"
        session = self._mock_session([chunk1])

        document_id = uuid.uuid4()
        with self.assertRaises(RuntimeError):
            await service.embed_document_chunks(session, document_id)

        # 失败时不应 commit
        session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
