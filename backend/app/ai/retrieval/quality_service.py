"""检索质量层 refine：去重 + 重排 + 多样性

参考 lib-v0.2 retrieval_quality_service.py + rerank_service.py：
1. _dedupe 三级去重：id → source:domain:source_id:chunk_index → text:hash
2. rerank：API 模式调外部 /rerank；本地 fallback _local_score
3. 多样性 max_per_source（默认 3，按 domain:source_id 限流）
4. metadata 注入 retrieval_mode/final_retrieval_mode/quality_rank/original_rank/rerank_score

设计原则：
- exact_bonus 对数字/符号命中加 0.04 最多 0.12（确定性 bonus）
- 本地 fallback 保证 rerank API 不可用时仍可用
- rerank API 模式走 LLM provider（TODO）
"""
import hashlib
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict
from loguru import logger

# 多样性配置
DEFAULT_MAX_PER_SOURCE = 3

# 本地 rerank 权重
LOCAL_RERANK_WEIGHTS = {
    "base": 0.42,       # 基础分（原召回分）
    "coverage": 0.38,   # 查询词覆盖率
    "title": 0.10,      # 标题匹配
    "phrase": 0.08,     # 短语匹配
    "exact_bonus_max": 0.12,  # 数字/符号命中 bonus 上限
    "exact_bonus_per": 0.04,  # 每个数字/符号命中加 0.04
}


def dedupe(chunks_with_scores: List[tuple]) -> List[tuple]:
    """三级去重
    
    1. id 去重（同 chunk id）
    2. source:domain:source_id:chunk_index 去重
    3. text:hash 去重（内容相同的块）
    
    输入：[(chunk, score), ...]
    输出：去重后的 [(chunk, score), ...]
    """
    seen_ids = set()
    seen_source_keys = set()
    seen_text_hashes = set()
    result = []
    
    for chunk, score in chunks_with_scores:
        # 1. id 去重
        cid = getattr(chunk, "id", None)
        if cid and cid in seen_ids:
            continue
        if cid:
            seen_ids.add(cid)
        
        # 2. source key 去重
        source_key = f"{getattr(chunk, 'knowledge_base_id', '')}:{getattr(chunk, 'source_doc_id', '')}:{getattr(chunk, 'chunk_index', '')}"
        if source_key in seen_source_keys:
            continue
        seen_source_keys.add(source_key)
        
        # 3. text hash 去重
        content = (getattr(chunk, "content", "") or "")[:500]
        text_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        if text_hash in seen_text_hashes:
            continue
        seen_text_hashes.add(text_hash)
        
        result.append((chunk, score))
    
    return result


def _compute_coverage(query_text: str, content: str) -> float:
    """计算查询词在内容中的覆盖率"""
    if not query_text or not content:
        return 0.0
    query_words = set(query_text.lower().split())
    content_lower = content.lower()
    if not query_words:
        return 0.0
    matched = sum(1 for w in query_words if w in content_lower)
    return matched / len(query_words)


def _compute_title_score(query_text: str, title: Optional[str]) -> float:
    """计算标题匹配分"""
    if not title or not query_text:
        return 0.0
    query_lower = query_text.lower()
    title_lower = title.lower()
    if query_lower in title_lower:
        return 1.0
    query_words = set(query_lower.split())
    title_words = set(title_lower.split())
    if not query_words:
        return 0.0
    return len(query_words & title_words) / len(query_words)


def _compute_exact_bonus(query_text: str, content: str) -> float:
    """计算数字/符号命中的 bonus（确定性检查）
    
    对数字、单位、符号的精确匹配给 bonus
    """
    import re
    # 提取查询中的数字和符号
    numbers_in_query = set(re.findall(r"\d+\.?\d*", query_text))
    if not numbers_in_query:
        return 0.0
    
    content_lower = content.lower()
    bonus = 0.0
    for num in numbers_in_query:
        if num in content_lower:
            bonus += LOCAL_RERANK_WEIGHTS["exact_bonus_per"]
    
    return min(bonus, LOCAL_RERANK_WEIGHTS["exact_bonus_max"])


def local_rerank(
    chunks_with_scores: List[tuple],
    query_text: str,
    top_k: int = 10,
) -> List[tuple]:
    """本地 fallback rerank
    
    _local_score = base*0.42 + coverage*0.38 + title*0.10 + phrase*0.08 + exact_bonus
    
    exact_bonus 对数字/符号命中加 0.04 最多 0.12（确定性 bonus）
    """
    scored = []
    for chunk, base_score in chunks_with_scores:
        content = getattr(chunk, "content", "") or ""
        title = getattr(chunk, "title", None)
        
        coverage = _compute_coverage(query_text, content)
        title_score = _compute_title_score(query_text, title)
        # phrase_score：简单检查查询文本是否出现在内容中
        phrase_score = 1.0 if query_text.lower() in content.lower() else 0.0
        exact_bonus = _compute_exact_bonus(query_text, content)
        
        final_score = (
            base_score * LOCAL_RERANK_WEIGHTS["base"]
            + coverage * LOCAL_RERANK_WEIGHTS["coverage"]
            + title_score * LOCAL_RERANK_WEIGHTS["title"]
            + phrase_score * LOCAL_RERANK_WEIGHTS["phrase"]
            + exact_bonus
        )
        
        scored.append((chunk, final_score, {
            "base_score": base_score,
            "coverage": coverage,
            "title_score": title_score,
            "phrase_score": phrase_score,
            "exact_bonus": exact_bonus,
            "rerank_score": final_score,
            "rerank_strategy": "local_fallback",
        }))
    
    # 按重排分降序
    scored.sort(key=lambda x: x[1], reverse=True)
    
    # 保留 metadata
    result = []
    for rank, (chunk, score, meta) in enumerate(scored[:top_k]):
        # 注入 metadata
        if hasattr(chunk, "metadata_json") and isinstance(chunk.metadata_json, dict):
            chunk.metadata_json.update({
                "quality_rank": rank + 1,
                "original_rank": chunks_with_scores.index((chunk, meta["base_score"])) + 1 if (chunk, meta["base_score"]) in chunks_with_scores else None,
                "rerank_score": score,
                "rerank_strategy": "local_fallback",
                "final_retrieval_mode": "hybrid_rerank",
            })
        result.append((chunk, score))
    
    return result


async def api_rerank(
    chunks_with_scores: List[tuple],
    query_text: str,
    top_k: int = 10,
) -> List[tuple]:
    """API rerank（调外部 /rerank 端点）
    
    TODO: 接入 LLM provider 的 rerank 端点
    当前降级到 local_rerank
    """
    logger.info("[Rerank] API rerank 暂未接入，降级到 local_rerank")
    return local_rerank(chunks_with_scores, query_text, top_k)


def diversity_filter(
    chunks_with_scores: List[tuple],
    max_per_source: int = DEFAULT_MAX_PER_SOURCE,
) -> List[tuple]:
    """多样性过滤：按 domain:source_id 限流
    
    每个来源最多保留 max_per_source 条
    """
    source_counts = defaultdict(int)
    result = []
    for chunk, score in chunks_with_scores:
        source_key = f"{getattr(chunk, 'knowledge_base_id', '')}:{getattr(chunk, 'source_doc_id', '')}"
        if source_counts[source_key] < max_per_source:
            result.append((chunk, score))
            source_counts[source_key] += 1
    return result


async def refine(
    chunks_with_scores: List[tuple],
    query_text: str,
    top_k: int = 10,
    max_per_source: int = DEFAULT_MAX_PER_SOURCE,
    use_rerank: bool = True,
) -> List[tuple]:
    """检索质量层入口：去重 → 重排 → 多样性 → 限流
    
    输入：[(chunk, score), ...]（来自 hybrid_search 或 vector_search）
    输出：[(chunk, refined_score), ...]，长度 ≤ top_k
    """
    # 1. 去重
    deduped = dedupe(chunks_with_scores)
    
    # 2. 重排
    if use_rerank and query_text:
        reranked = await api_rerank(deduped, query_text, top_k * 2)
    else:
        reranked = deduped
    
    # 3. 多样性
    diversified = diversity_filter(reranked, max_per_source)
    
    # 4. 限流
    return diversified[:top_k]
