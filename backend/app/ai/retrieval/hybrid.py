"""RRF 混合检索融合：语义 + 词法

参考 lib-v0.2 retrieval_service.py 的 _hybrid_results 方法：
- 双路召回：向量路（pgvector ANN）+ 词法路（tsvector + pg_trgm ILIKE）
- RRF 融合公式：fused_score = max(s, l) + min(rrf*4, 0.18)
- k=60.0，lexical 权重 1.08（略加权补偿词法召回靠后）

设计原则：
- HYBRID_SEARCH_ENABLED 开关 + domain 级开关
- k 值与权重写入 ExpertMemory 作为可调经验（TODO）
- 失败降级到纯向量召回
"""
import asyncio
from typing import List, Optional, Dict, Any
from sqlalchemy import select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from app.core.config import settings

# RRF 参数（TODO: 迁移到 ExpertMemory 作为可调经验）
RRF_K = 60.0
RRF_LEXICAL_WEIGHT = 1.08  # lexical 略加权补偿
RRF_BONUS_CAP = 0.18       # RRF 加分上限，防止压制原分


async def vector_search(
    session: AsyncSession,
    model,
    query_embedding: List[float],
    knowledge_base_id: Optional[Any] = None,
    top_k: int = 20,
    filters: Optional[Dict] = None,
) -> List[tuple]:
    """向量路召回（pgvector ANN cosine）
    
    返回 [(chunk, score), ...]，score 为相似度 0~1
    """
    try:
        stmt = select(model).where(model.embedding.is_not(None))
        if knowledge_base_id:
            stmt = stmt.where(model.knowledge_base_id == knowledge_base_id)
        if filters:
            for key, value in filters.items():
                if hasattr(model, key):
                    stmt = stmt.where(getattr(model, key) == value)
        # cosine distance => similarity = 1 - distance
        stmt = stmt.order_by(
            model.embedding.cosine_distance(query_embedding)
        ).limit(top_k)
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        return [(c, 1.0 - i / max(len(chunks), 1)) for i, c in enumerate(chunks)]
    except Exception as e:
        logger.warning(f"向量召回失败: {e}")
        return []


async def lexical_search(
    session: AsyncSession,
    model,
    query_text: str,
    knowledge_base_id: Optional[Any] = None,
    top_k: int = 20,
    filters: Optional[Dict] = None,
) -> List[tuple]:
    """词法路召回（pg_trgm ILIKE 模糊匹配）
    
    返回 [(chunk, score), ...]，score 为相似度 0~1
    """
    if not query_text or not query_text.strip():
        return []
    try:
        stmt = select(model).where(model.content.is_not(None))
        if knowledge_base_id:
            stmt = stmt.where(model.knowledge_base_id == knowledge_base_id)
        if filters:
            for key, value in filters.items():
                if hasattr(model, key):
                    stmt = stmt.where(getattr(model, key) == value)
        # pg_trgm 模糊匹配（content ILIKE %query%）
        search_pattern = f"%{query_text}%"
        stmt = stmt.where(model.content.ilike(search_pattern))
        stmt = stmt.limit(top_k)
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        # 词法召回按顺序给分（越靠前越高）
        return [(c, 1.0 - i / max(len(chunks), 1)) for i, c in enumerate(chunks)]
    except Exception as e:
        logger.warning(f"词法召回失败: {e}")
        return []


def rrf_fuse(
    vector_results: List[tuple],
    lexical_results: List[tuple],
    top_k: int = 10,
) -> List[tuple]:
    """RRF 融合两路召回结果
    
    公式（参考 lib-v0.2）：
    - semantic: weight=1.0, rrf_score = 1.0/(k+rank)
    - lexical: weight=1.08, rrf_score = 1.08/(k+rank)
    - fused_score = max(s, l) + min(rrf*4, 0.18)
    
    返回 [(chunk, fused_score), ...]，按 fused_score 降序
    """
    # 构建 chunk_id -> (chunk, vector_score, lexical_score)
    fused_map: Dict[Any, dict] = {}
    
    for rank, (chunk, score) in enumerate(vector_results):
        cid = getattr(chunk, "id", id(chunk))
        if cid not in fused_map:
            fused_map[cid] = {"chunk": chunk, "vector_score": 0.0, "lexical_score": 0.0}
        rrf_v = 1.0 / (RRF_K + rank + 1)
        fused_map[cid]["vector_score"] = max(fused_map[cid]["vector_score"], score, rrf_v)
    
    for rank, (chunk, score) in enumerate(lexical_results):
        cid = getattr(chunk, "id", id(chunk))
        if cid not in fused_map:
            fused_map[cid] = {"chunk": chunk, "vector_score": 0.0, "lexical_score": 0.0}
        rrf_l = RRF_LEXICAL_WEIGHT / (RRF_K + rank + 1)
        fused_map[cid]["lexical_score"] = max(fused_map[cid]["lexical_score"], score, rrf_l)
    
    # 计算融合分数
    results = []
    for cid, info in fused_map.items():
        s = info["vector_score"]
        l = info["lexical_score"]
        rrf_total = (1.0 / (RRF_K + 1) if s > 0 else 0) + (RRF_LEXICAL_WEIGHT / (RRF_K + 1) if l > 0 else 0)
        fused_score = max(s, l) + min(rrf_total * 4, RRF_BONUS_CAP)
        results.append((info["chunk"], fused_score))
    
    # 按融合分数降序
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


async def hybrid_search(
    session: AsyncSession,
    model,
    query_text: str,
    query_embedding: Optional[List[float]] = None,
    knowledge_base_id: Optional[Any] = None,
    top_k: int = 10,
    filters: Optional[Dict] = None,
    enabled: Optional[bool] = None,
) -> List[tuple]:
    """混合检索入口
    
    - enabled=None 时读 settings.HYBRID_SEARCH_ENABLED（默认 True）
    - enabled=False 时仅走向量路
    - 向量路失败降级到词法路
    """
    if enabled is None:
        enabled = getattr(settings, "HYBRID_SEARCH_ENABLED", True)
    
    # 并行双路召回
    tasks = []
    if query_embedding:
        tasks.append(vector_search(session, model, query_embedding, knowledge_base_id, top_k * 2, filters))
    tasks.append(lexical_search(session, model, query_text, knowledge_base_id, top_k * 2, filters))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    v_results = results[0] if len(results) > 0 and isinstance(results[0], list) else []
    l_results = results[1] if len(results) > 1 and isinstance(results[1], list) else []
    
    if not enabled:
        # 仅用向量路
        return v_results[:top_k]
    
    if not v_results and not l_results:
        return []
    
    if not v_results:
        return l_results[:top_k]
    
    return rrf_fuse(v_results, l_results, top_k)
