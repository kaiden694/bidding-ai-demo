"""T2.3: RAGRetriever 单元测试（mock EmbeddingClient + DB）

被测 RAGRetriever 三个 search 方法通过 select(Model).where(...).order_by(cosine)
检索。此处用「站位映射类」替换模型引用，使 select/过滤条件/cosine_distance 走真实
SQLAlchemy（可编译 SQL 校验过滤条件），EmbeddingClient 与 AsyncSession 全部 mock。
"""
import sys
import types
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column
from pgvector.sqlalchemy import Vector

# 测试不连接真实 DB：用桩替换 app.core.database，避免 create_engine 触发
# asyncpg/psycopg 导入（测试环境未安装）。仅需提供 DeclarativeBase 给模型基类。
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
from app.ai.rag.retriever import RAGRetriever


# ---- 站位映射类：仅用于构建真实 Select 语句（不依赖真实 ORM 完整注册）----
class _Base(DeclarativeBase):
    pass


class _DocumentChunk(_Base):
    __tablename__ = "document_chunk"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = mapped_column(UUID(as_uuid=True))
    content = mapped_column(Text)
    page_number = mapped_column(Integer)
    section = mapped_column(String(256))
    table_ref = mapped_column(String(128))
    chunk_type = mapped_column(String(32))
    embedding = mapped_column(Vector(8))


class _GeneralKnowledgeChunk(_Base):
    __tablename__ = "general_knowledge_chunk"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id = mapped_column(UUID(as_uuid=True))
    source_doc_id = mapped_column(UUID(as_uuid=True), nullable=True)
    content = mapped_column(Text)
    page_number = mapped_column(Integer)
    section = mapped_column(String(256))
    table_ref = mapped_column(String(128))
    chunk_type = mapped_column(String(32))
    embedding = mapped_column(Vector(8))


class _GeneralKnowledgeBase(_Base):
    __tablename__ = "general_knowledge_base"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    is_deleted = mapped_column(Boolean)
    is_published = mapped_column(Boolean)
    category = mapped_column(String(64))
    visibility = mapped_column(String(16))


class _Product(_Base):
    __tablename__ = "product"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    is_deleted = mapped_column(Boolean)
    is_published = mapped_column(Boolean)
    category_id = mapped_column(UUID(as_uuid=True))


class _ProductChunk(_Base):
    __tablename__ = "product_chunk"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = mapped_column(UUID(as_uuid=True))
    source_doc_id = mapped_column(UUID(as_uuid=True), nullable=True)
    content = mapped_column(Text)
    page_number = mapped_column(Integer)
    section = mapped_column(String(256))
    table_ref = mapped_column(String(128))
    chunk_type = mapped_column(String(32))
    embedding = mapped_column(Vector(8))


# retriever 模块内引用的模型名 -> 站位映射类
_MODEL_PATCHES = {
    "DocumentChunk": _DocumentChunk,
    "GeneralKnowledgeChunk": _GeneralKnowledgeChunk,
    "GeneralKnowledgeBase": _GeneralKnowledgeBase,
    "Product": _Product,
    "ProductChunk": _ProductChunk,
}


class TestRAGSearch(unittest.IsolatedAsyncioTestCase):
    """覆盖 RAG 召回核心路径：向量召回 + 过滤 + 证据格式"""

    async def asyncSetUp(self):
        # patch get_embedding_client，使 RAGRetriever 持有 mock client
        self._emb_patcher = patch("app.ai.rag.retriever.get_embedding_client")
        mock_get = self._emb_patcher.start()
        self.mock_client = AsyncMock()
        mock_get.return_value = self.mock_client
        # patch 模型引用为站位映射类，使 select/条件构建走真实 SQLAlchemy
        self._model_patchers = [
            patch(f"app.ai.rag.retriever.{name}", cls)
            for name, cls in _MODEL_PATCHES.items()
        ]
        for p in self._model_patchers:
            p.start()
        self.retriever = RAGRetriever()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self._emb_patcher.stop()
        for p in self._model_patchers:
            p.stop()

    @staticmethod
    def _mock_session(chunks):
        """构造 mock AsyncSession，execute -> scalars().all() -> chunks"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = chunks
        session = AsyncMock()
        session.execute.return_value = mock_result
        return session

    @staticmethod
    def _executed_stmt(session):
        """取回传给 session.execute 的 Select 语句"""
        return session.execute.await_args.args[0]

    @staticmethod
    def _stmt_sql(stmt):
        """编译语句为 SQL 字符串（不含字面量绑定，避免 pgvector 字面量渲染问题）"""
        return str(stmt.compile())

    async def test_search_documents_returns_evidence(self):
        """验证向量召回返回证据格式（chunk_id/content/page_number/section）"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)

        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk = MagicMock()
        chunk.id = chunk_id
        chunk.document_id = doc_id
        chunk.content = "evidence content"
        chunk.page_number = 3
        chunk.section = "2.1 技术要求"
        chunk.table_ref = "表1"
        chunk.chunk_type = "text"

        session = self._mock_session([chunk])
        results = await self.retriever.search_documents(session, "测试查询")

        self.assertEqual(len(results), 1)
        ev = results[0]
        # 证据格式关键字段
        self.assertEqual(ev["chunk_id"], str(chunk_id))
        self.assertEqual(ev["document_id"], str(doc_id))
        self.assertEqual(ev["content"], "evidence content")
        self.assertEqual(ev["page_number"], 3)
        self.assertEqual(ev["section"], "2.1 技术要求")
        self.assertEqual(ev["table_ref"], "表1")
        self.assertEqual(ev["chunk_type"], "text")
        # 向量召回被调用一次
        self.mock_client.embed_one.assert_awaited_once_with("测试查询")

    async def test_search_documents_with_document_ids_filter(self):
        """验证 document_ids 过滤条件出现在 SQL 中"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)
        session = self._mock_session([])

        await self.retriever.search_documents(
            session, "查询", document_ids=[uuid.uuid4(), uuid.uuid4()]
        )

        sql = self._stmt_sql(self._executed_stmt(session))
        self.assertIn("document_id", sql)

    async def test_search_general_knowledge_filters_visibility(self):
        """验证 visibility 过滤条件出现在 SQL 中"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)
        session = self._mock_session([])

        await self.retriever.search_general_knowledge(
            session, "查询", visibility="front"
        )

        sql = self._stmt_sql(self._executed_stmt(session))
        # visibility 过滤列出现
        self.assertIn("visibility", sql)
        # 已发布 + 未删除条件出现
        self.assertIn("is_published", sql)
        self.assertIn("is_deleted", sql)

    async def test_search_general_knowledge_returns_evidence(self):
        """验证通用知识库召回证据格式"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)

        kb_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        chunk = MagicMock()
        chunk.id = chunk_id
        chunk.knowledge_base_id = kb_id
        chunk.source_doc_id = None  # 测试 None 分支
        chunk.content = "gk content"
        chunk.page_number = 5
        chunk.section = "第一章"
        chunk.table_ref = None
        chunk.chunk_type = "heading"

        session = self._mock_session([chunk])
        results = await self.retriever.search_general_knowledge(session, "查询")

        self.assertEqual(len(results), 1)
        ev = results[0]
        self.assertEqual(ev["chunk_id"], str(chunk_id))
        self.assertEqual(ev["knowledge_base_id"], str(kb_id))
        self.assertIsNone(ev["source_doc_id"])
        self.assertEqual(ev["content"], "gk content")
        self.assertEqual(ev["page_number"], 5)
        self.assertEqual(ev["section"], "第一章")
        self.assertEqual(ev["chunk_type"], "heading")

    async def test_search_products_filters_published(self):
        """验证只检索已上架且未删除产品（条件出现在 SQL 中）"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)
        session = self._mock_session([])

        await self.retriever.search_products(session, "查询")

        sql = self._stmt_sql(self._executed_stmt(session))
        # 仅检索已上架且未删除产品
        self.assertIn("is_published", sql)
        self.assertIn("is_deleted", sql)

    async def test_search_products_returns_evidence(self):
        """验证产品资料召回证据格式"""
        self.mock_client.embed_one = AsyncMock(return_value=[0.1] * 8)

        prod_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        source_doc_id = uuid.uuid4()
        chunk = MagicMock()
        chunk.id = chunk_id
        chunk.product_id = prod_id
        chunk.source_doc_id = source_doc_id
        chunk.content = "product content"
        chunk.page_number = 2
        chunk.section = "参数表"
        chunk.table_ref = "表A"
        chunk.chunk_type = "table"

        session = self._mock_session([chunk])
        results = await self.retriever.search_products(session, "查询")

        self.assertEqual(len(results), 1)
        ev = results[0]
        self.assertEqual(ev["chunk_id"], str(chunk_id))
        self.assertEqual(ev["product_id"], str(prod_id))
        self.assertEqual(ev["source_doc_id"], str(source_doc_id))
        self.assertEqual(ev["content"], "product content")
        self.assertEqual(ev["page_number"], 2)
        self.assertEqual(ev["section"], "参数表")
        self.assertEqual(ev["chunk_type"], "table")

    async def test_search_empty_query(self):
        """空查询返回空列表，不调用 embed/execute"""
        session = self._mock_session([])
        for method_name in (
            "search_documents",
            "search_general_knowledge",
            "search_products",
        ):
            results = await getattr(self.retriever, method_name)(session, "")
            self.assertEqual(results, [], f"{method_name} 空查询应返回空列表")
            results_ws = await getattr(self.retriever, method_name)(session, "   ")
            self.assertEqual(results_ws, [], f"{method_name} 空白查询应返回空列表")

        # 未触发向量化与 DB 查询
        self.mock_client.embed_one.assert_not_awaited()
        session.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
