"""文本切分器：按 chunk_size + overlap 切分，保留章节元数据"""
from app.ai.parsing.parser import Chunk
from app.core.config import settings


def chunk_text(text: str, section: str = None, page_number: int = None) -> list[Chunk]:
    """按固定窗口切分（Phase 2 升级为按语义/条款切分）"""
    size = settings.RAG_CHUNK_SIZE
    overlap = settings.RAG_CHUNK_OVERLAP
    if not text:
        return []
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(
            Chunk(
                content=text[start:end],
                section=section,
                page_number=page_number,
                chunk_type="text",
                metadata={"chunk_index": idx},
            )
        )
        start += size - overlap
        idx += 1
    return chunks
