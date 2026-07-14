"""统一检索门面 RetrievalService（P2-9）

参考 lib-v0.2 retrieval_service.py 的 RetrievalService 设计：
- 6 domain 隔离：params/materials/contracts/expert/bidding/enterprise
- RetrievalScope：tenant_context/product_ids/certificate_ids/allowed_org_ids/permissions
- RetrievalResult 标准化：id/domain/content/score/source_id/source_name/metadata
- log_retrieval_event：query_hash（SHA256 前 16 位）结构化检索日志

设计原则：
- 现有 RAGRetriever 作为底层 backend 保留
- 上层业务调用统一走 RetrievalService（不直接调 retriever/hybrid_search）
- AI-first：domain 路由通过策略表配置，不写硬规则
"""
import enum
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding.client import get_embedding_client
from app.ai.retrieval.hybrid import hybrid_search
from app.ai.retrieval.quality_service import refine
from app.models.document import DocumentChunk, KnowledgeChunk
from app.models.general_knowledge import GeneralKnowledgeBase, GeneralKnowledgeChunk
from app.models.product import Product, ProductChunk


# ============================================================
# 枚举与数据类
# ============================================================
class RetrievalDomain(str, enum.Enum):
    """检索域：6 类隔离，每个域走不同 backend"""
    PARAMS = "params"             # 招标参数（DocumentChunk，type=tender/spec）
    MATERIALS = "materials"       # 产品资料（ProductChunk）
    CONTRACTS = "contracts"       # 合同文档（DocumentChunk，type=contract）
    EXPERT = "expert"             # 历史经验（KnowledgeChunk + FeedbackRecord）
    BIDDING = "bidding"           # 历史标书（KnowledgeChunk，category=标书）
    ENTERPRISE = "enterprise"    # 企业资料（GeneralKnowledgeChunk）


@dataclass
class RetrievalScope:
    """检索范围（租户隔离 + 权限过滤）"""
    tenant_context: Optional[Dict[str, Any]] = None     # 租户上下文（project_id/organization_id）
    product_ids: Optional[List[uuid.UUID]] = None       # 限定产品
    certificate_ids: Optional[List[uuid.UUID]] = None   # 限定资质证书
    allowed_org_ids: Optional[List[uuid.UUID]] = None   # 可见组织
    permissions: Optional[List[str]] = None             # 调用方权限列表
    document_ids: Optional[List[uuid.UUID]] = None      # 限定文档（params/contracts 域）


@dataclass
class RetrievalResult:
    """标准化检索结果"""
    id: str                                              # chunk id
    domain: str                                          # 检索域
    content: str                                         # 原文片段
    score: float                                         # 综合分数（0~1）
    source_id: Optional[str] = None                      # 来源实体 id（document_id/product_id 等）
    source_name: Optional[str] = None                    # 来源名称
    metadata: Dict[str, Any] = field(default_factory=dict)  # 页码/章节/表格/标签等
    retrieval_mode: Optional[str] = None                 # 检索模式：hybrid/vector/lexical
    rerank_score: Optional[float] = None                # rerank 分数


# ============================================================
# RetrievalService
# ============================================================
class RetrievalService:
    """统一检索门面

    使用方式：
        scope = RetrievalScope(document_ids=[tender_doc_id])
        results = await retrieval_service.search(
            session, query="电池容量", domain=RetrievalDomain.PARAMS, scope=scope, top_k=5
        )
    """

    def __init__(self):
        self._embedding_client = get_embedding_client()

    async def search(
        self,
        session: AsyncSession,
        query: str,
        domain: RetrievalDomain = RetrievalDomain.PARAMS,
        scope: Optional[RetrievalScope] = None,
        top_k: int = 10,
        use_rerank: bool = True,
    ) -> List[RetrievalResult]:
        """统一检索入口

        - 根据 domain 路由到不同 backend
        - 走 hybrid_search（向量 + 词法 RRF 融合）+ refine（去重 + rerank + 多样性）
        - 标准化为 RetrievalResult
        - 记录结构化检索日志
        """
        scope = scope or RetrievalScope()
        query_hash = self._hash_query(query)

        try:
            # 域路由
            if domain == RetrievalDomain.PARAMS:
                results = await self._search_params(session, query, scope, top_k, use_rerank)
            elif domain == RetrievalDomain.MATERIALS:
                results = await self._search_materials(session, query, scope, top_k, use_rerank)
            elif domain == RetrievalDomain.CONTRACTS:
                results = await self._search_contracts(session, query, scope, top_k, use_rerank)
            elif domain == RetrievalDomain.EXPERT:
                results = await self._search_expert(session, query, scope, top_k)
            elif domain == RetrievalDomain.BIDDING:
                results = await self._search_bidding(session, query, scope, top_k, use_rerank)
            elif domain == RetrievalDomain.ENTERPRISE:
                results = await self._search_enterprise(session, query, scope, top_k, use_rerank)
            else:
                logger.warning(f"[RetrievalService] 未知 domain: {domain}")
                results = []

            self._log_event(
                query_hash=query_hash, domain=domain.value, top_k=top_k,
                hit_count=len(results), scope=scope, status="ok",
            )
            return results
        except Exception as e:
            self._log_event(
                query_hash=query_hash, domain=domain.value, top_k=top_k,
                hit_count=0, scope=scope, status="error", error=str(e),
            )
            logger.warning(f"[RetrievalService] 检索失败 domain={domain.value}: {e}")
            return []

    # ============================================================
    # 域 backend 实现
    # ============================================================
    async def _search_params(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int, use_rerank: bool,
    ) -> List[RetrievalResult]:
        """招标参数域：DocumentChunk"""
        document_ids = scope.document_ids
        filters = None
        if document_ids:
            filters = {"document_id": document_ids[0]}  # hybrid_search filters 单值匹配
        return await self._hybrid_refine(
            session, query, DocumentChunk, filters, top_k, use_rerank,
            domain=RetrievalDomain.PARAMS.value,
        )

    async def _search_materials(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int, use_rerank: bool,
    ) -> List[RetrievalResult]:
        """产品资料域：ProductChunk + 产品上下文过滤"""
        filters = None
        if scope.product_ids:
            filters = {"product_id": scope.product_ids[0]}
        results = await self._hybrid_refine(
            session, query, ProductChunk, filters, top_k, use_rerank,
            domain=RetrievalDomain.MATERIALS.value,
        )
        # 补充 source_name（产品名）
        if results:
            await self._enrich_product_names(session, results)
        return results

    async def _search_contracts(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int, use_rerank: bool,
    ) -> List[RetrievalResult]:
        """合同文档域：DocumentChunk（type=contract 的文档切块）"""
        filters = None
        if scope.document_ids:
            filters = {"document_id": scope.document_ids[0]}
        return await self._hybrid_refine(
            session, query, DocumentChunk, filters, top_k, use_rerank,
            domain=RetrievalDomain.CONTRACTS.value,
        )

    async def _search_expert(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int,
    ) -> List[RetrievalResult]:
        """历史经验域：KnowledgeChunk + FeedbackRecord
        不走 rerank（ FeedbackRecord 走 cosine 排序即可）
        """
        # 1. KnowledgeChunk 向量召回
        kc_results = await self._vector_only(
            session, query, KnowledgeChunk, top_k=top_k,
            domain=RetrievalDomain.EXPERT.value,
        )
        # TODO: 可叠加 FeedbackRecord 召回，作为可演进经验资产
        return kc_results[:top_k]

    async def _search_bidding(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int, use_rerank: bool,
    ) -> List[RetrievalResult]:
        """历史标书域：KnowledgeChunk（category=标书）"""
        results = await self._hybrid_refine(
            session, query, KnowledgeChunk, None, top_k, use_rerank,
            domain=RetrievalDomain.BIDDING.value,
        )
        # 过滤 category=标书（不在 SQL 层过滤是因为 hybrid_search 不支持任意 filter）
        return [r for r in results if (r.metadata.get("category") in (None, "标书", "bidding"))][:top_k]

    async def _search_enterprise(
        self, session: AsyncSession, query: str, scope: RetrievalScope,
        top_k: int, use_rerank: bool,
    ) -> List[RetrievalResult]:
        """企业资料域：GeneralKnowledgeChunk"""
        results = await self._hybrid_refine(
            session, query, GeneralKnowledgeChunk, None, top_k, use_rerank,
            domain=RetrievalDomain.ENTERPRISE.value,
        )
        # 过滤已发布且未删除的来源
        return [r for r in results if r.metadata.get("is_published", True)][:top_k]

    # ============================================================
    # 通用 hybrid + refine 工具
    # ============================================================
    async def _hybrid_refine(
        self, session: AsyncSession, query: str, model,
        filters: Optional[Dict], top_k: int, use_rerank: bool,
        domain: str,
    ) -> List[RetrievalResult]:
        """通用：hybrid_search → refine → 标准化为 RetrievalResult"""
        # 生成查询向量
        query_embedding = None
        try:
            query_embedding = await self._embedding_client.embed_one(query)
        except Exception as e:
            logger.warning(f"[RetrievalService] embedding 失败，降级到词法召回: {e}")

        # 双路召回
        raw = await hybrid_search(
            session, model, query, query_embedding=query_embedding,
            top_k=top_k * 2, filters=filters,
        )
        if not raw:
            return []

        # 检索质量层 refine
        refined = await refine(raw, query, top_k=top_k, use_rerank=use_rerank)

        # 标准化
        return [self._to_result(c, s, domain) for c, s in refined]

    async def _vector_only(
        self, session: AsyncSession, query: str, model,
        top_k: int, domain: str,
    ) -> List[RetrievalResult]:
        """纯向量召回（用于 expert 等不需要词法召回的域）"""
        try:
            query_vec = await self._embedding_client.embed_one(query)
        except Exception as e:
            logger.warning(f"[RetrievalService] embedding 失败: {e}")
            return []
        try:
            stmt = (
                select(model)
                .where(model.embedding.is_not(None))
                .order_by(model.embedding.cosine_distance(query_vec))
                .limit(top_k)
            )
            result = await session.execute(stmt)
            chunks = result.scalars().all()
            return [self._to_result(c, 1.0 - i / max(len(chunks), 1), domain)
                    for i, c in enumerate(chunks)]
        except Exception as e:
            logger.warning(f"[RetrievalService] 向量召回失败: {e}")
            return []

    # ============================================================
    # 结果标准化
    # ============================================================
    @staticmethod
    def _to_result(chunk, score: float, domain: str) -> RetrievalResult:
        """将底层 chunk 转为标准化 RetrievalResult"""
        # 提取公共字段
        chunk_id = str(getattr(chunk, "id", "") or "")
        content = getattr(chunk, "content", "") or ""
        page_number = getattr(chunk, "page_number", None)
        section = getattr(chunk, "section", None)
        table_ref = getattr(chunk, "table_ref", None)
        chunk_type = getattr(chunk, "chunk_type", None)
        metadata = getattr(chunk, "metadata_json", None) or {}

        # 来源实体 id（不同模型字段名不同）
        source_id = None
        source_name = None
        for field_name in ("document_id", "product_id", "knowledge_base_id"):
            sid = getattr(chunk, field_name, None)
            if sid is not None:
                source_id = str(sid)
                break

        # 提取 retrieval 元信息
        if isinstance(metadata, dict):
            retrieval_mode = metadata.get("final_retrieval_mode") or metadata.get("retrieval_mode")
            rerank_score = metadata.get("rerank_score")
        else:
            retrieval_mode = None
            rerank_score = None

        # 装入 metadata
        meta = {
            "page_number": page_number,
            "section": section,
            "table_ref": table_ref,
            "chunk_type": chunk_type,
        }
        if isinstance(metadata, dict):
            for k in ("category", "title", "tags", "is_published", "quality_rank"):
                if k in metadata:
                    meta[k] = metadata[k]

        return RetrievalResult(
            id=chunk_id,
            domain=domain,
            content=content,
            score=float(score) if score is not None else 0.0,
            source_id=source_id,
            source_name=source_name,
            metadata=meta,
            retrieval_mode=retrieval_mode or "hybrid",
            rerank_score=float(rerank_score) if rerank_score is not None else None,
        )

    async def _enrich_product_names(
        self, session: AsyncSession, results: List[RetrievalResult]
    ) -> None:
        """补充产品名称到 source_name"""
        product_ids = [r.source_id for r in results if r.source_id]
        if not product_ids:
            return
        try:
            # 解析为 UUID
            pids = []
            for sid in product_ids:
                try:
                    pids.append(uuid.UUID(sid))
                except (ValueError, AttributeError):
                    continue
            if not pids:
                return
            stmt = select(Product.id, Product.name).where(Product.id.in_(pids))
            res = await session.execute(stmt)
            id_to_name = {str(pid): name for pid, name in res.all()}
            for r in results:
                if r.source_id and r.source_id in id_to_name:
                    r.source_name = id_to_name[r.source_id]
        except Exception as e:
            logger.warning(f"[RetrievalService] 补充产品名称失败（不阻断）: {e}")

    # ============================================================
    # 结构化日志（query_hash + scope + 命中数）
    # ============================================================
    @staticmethod
    def _hash_query(query: str) -> str:
        """SHA256 前 16 位（避免明文日志泄露查询内容）"""
        if not query:
            return "empty"
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _log_event(
        query_hash: str, domain: str, top_k: int,
        hit_count: int, scope: RetrievalScope,
        status: str, error: Optional[str] = None,
    ) -> None:
        """结构化检索日志（不写 DB，避免阻塞主流程；后续可接 OpenTelemetry）"""
        try:
            logger.bind(
                event="retrieval",
                query_hash=query_hash,
                domain=domain,
                top_k=top_k,
                hit_count=hit_count,
                status=status,
                error=error,
                has_scope=bool(scope.tenant_context or scope.product_ids
                               or scope.certificate_ids or scope.allowed_org_ids),
            ).info(f"[RetrievalService] domain={domain} hits={hit_count}/{top_k} status={status}")
        except Exception:
            pass


# ============================================================
# 单例
# ============================================================
_retrieval_service: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
