"""RAG 检索层：混合检索（向量 + 关键词 + 标签）+ 重排序

================================================================
派生索引设计原则（P3-15 T15.1）
================================================================
向量块（*Chunk.embedding）是 **derived index（派生索引）**，不是事实存储：

1. 源数据驻留在普通业务表中：
   - DocumentChunk.content / KnowledgeChunk.content → 来自 Document（原始文档）
   - GeneralKnowledgeChunk.content → 来自通用知识库导入文件
   - ProductChunk.content → 来自 Product（产品资料）
   这些表是 single source of truth，向量块只是它们的检索投影。

2. 派生意味着可重建：删除所有 embedding 行后，可通过
   - EmbeddingService.embed_document_chunks
   - EmbeddingService.embed_knowledge_chunks
   - KnowledgeService.reindex
   重新生成，业务逻辑不丢失任何信息。

3. 因此引入 **向量块数配额（Vector Quota）**：
   企业套餐上限覆盖所有 *Chunk 表（参见 VectorQuotaService），
   超限时阻止新增并返回 409 Conflict——但不影响源数据。

4. 行号前缀剥离（参见 text_utils.strip_line_number_prefix）：
   切块文本入库前剥离 "1 | " / "2、 " 等行号前缀，
   避免污染语义向量与检索关键词。
================================================================
"""
from app.ai.rag.retriever import RAGRetriever, get_rag_retriever
from app.ai.rag.chunker import chunk_text
from app.ai.rag.text_utils import (
    strip_line_number_prefix,
    semantic_requirement_text,
)

__all__ = [
    "RAGRetriever",
    "get_rag_retriever",
    "chunk_text",
    "strip_line_number_prefix",
    "semantic_requirement_text",
]
