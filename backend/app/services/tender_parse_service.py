"""招标文档结构化解析服务

参考 lib-v0.2 bidding_service.py：
- extract_document_toc：LLM 提取 PDF 目录树 + 页码范围
- analyze_project：asyncio.gather 并行 4 任务（TOC + Part A/B/C）
- 三部分并行 LLM 提取，避免单次长上下文截断
- prefer_more_complete_table：LLM 结果 vs 本地 fallback，选行数更多的
- 扫描件检测：PDF 图片占比阈值

设计原则：
- 13 维度作为可演进 prompt 模板（TODO 存 ExpertMemory）
- AI-first：所有结构识别由 LLM 完成
- 失败降级：单部分失败不阻塞整体
"""
import asyncio
import uuid
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.llm.response_parser import parse_llm_json, get_force_chinese_system_prompt
from app.models.document import Document, DocumentChunk, DocParseStatus

# 单项超时（秒）
_PART_TIMEOUT = 120
# 扫描件图片占比阈值
_SCAN_IMAGE_RATIO_THRESHOLD = 0.8

# 13 维度定义（TODO: 迁移到 ExpertMemory 作为可演进 prompt 模板）
TOC_PROMPT = """你是招投标文档解析专家。请从招标文件内容中提取目录结构（TOC）和各部分的页码范围。

输出 JSON 格式：
{
  "toc": [
    {"title": "章节标题", "page_start": 1, "page_end": 5, "level": 1}
  ],
  "page_ranges": {
    "summary": {"start": 1, "end": 3},
    "registration": {"start": 4, "end": 6},
    "deposit": {"start": 7, "end": 8},
    "bidding": {"start": 9, "end": 12},
    "opening": {"start": 13, "end": 14},
    "qualification": {"start": 15, "end": 20},
    "proposal_prep": {"start": 21, "end": 25},
    "purchase_list": {"start": 26, "end": 30},
    "tech_spec": {"start": 31, "end": 50},
    "delivery": {"start": 51, "end": 53},
    "after_sales": {"start": 54, "end": 56},
    "other_reqs": {"start": 57, "end": 58},
    "scoring": {"start": 59, "end": 62}
  }
}

仅输出 JSON，不要额外解释。
"""

PART_A_PROMPT = """你是招投标文档解析专家。请从招标文件内容中提取 Part A 信息：项目摘要、报名、保证金、投标、开标。

输出 JSON 格式：
{
  "summary": {
    "project_name": "项目名称",
    "project_code": "项目编号",
    "procurement_type": "采购方式",
    "budget": "预算金额",
    "deadline": "报名截止时间",
    "contact": "联系人信息"
  },
  "registration": {"start_time": "...", "end_time": "...", "method": "报名方式"},
  "deposit": {"amount": "保证金金额", "deadline": "截止时间", "return_policy": "退还政策"},
  "bidding": {"deadline": "投标截止时间", "location": "投标地点", "method": "投标方式"},
  "opening": {"time": "开标时间", "location": "开标地点", "attendees": "参会要求"}
}

仅输出 JSON，不要额外解释。
"""

PART_B_PROMPT = """你是招投标文档解析专家。请从招标文件内容中提取 Part B 信息：资格要求、标书准备、采购清单、技术规格、交付、售后、其他要求。

输出 JSON 格式：
{
  "qualification": [
    {"item": "资格要求项", "is_mandatory": true, "description": "详细描述"}
  ],
  "proposal_prep": {"format_req": "格式要求", "submission_req": "提交要求", "sections": ["章节1", "章节2"]},
  "purchase_list": [
    {"name": "产品名称", "spec": "规格", "quantity": 1, "unit": "单位", "is_mandatory": true}
  ],
  "tech_spec": [
    {"param": "参数名", "required_value": "要求值", "is_mandatory": true, "is_disqualifying": false}
  ],
  "delivery": {"time_limit": "交货期", "location": "交货地点", "method": "交货方式"},
  "after_sales": {"warranty": "质保期", "service_req": "服务要求", "response_time": "响应时间"},
  "other_reqs": [{"item": "其他要求项", "description": "描述"}]
}

注意：
- is_mandatory=true 表示★号条款（必备条款）
- is_disqualifying=true 表示废标条款（不满足即废标）
- 仅输出 JSON，不要额外解释
"""

PART_C_PROMPT = """你是招投标文档解析专家。请从招标文件内容中提取 Part C 信息：评分标准。

输出 JSON 格式：
{
  "scoring": {
    "total_score": 100,
    "categories": [
      {"name": "评分项名称", "max_score": 30, "criteria": "评分标准", "type": "客观/主观"}
    ]
  }
}

仅输出 JSON，不要额外解释。
"""


class TenderParseService:
    """招标文档结构化解析服务"""

    def __init__(self):
        self._llm = get_llm_client()

    async def extract_document_toc(self, document: Document) -> dict:
        """提取文档目录结构（TOC）+ 页码范围映射"""
        # 从 document 的 chunks 构建全文
        # 这里简化：直接用 document.metadata 中的内容或 chunks
        # 实际实现需要从 DB 获取 chunks
        pass  # 由 analyze_project 内部调用

    async def _get_chunks_text(self, session: AsyncSession, doc_id: uuid.UUID, max_chars: int = 50000) -> str:
        """获取文档切块的全文文本"""
        from sqlalchemy import select
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
        result = await session.execute(stmt)
        chunks = result.scalars().all()
        text_parts = []
        total = 0
        for c in chunks:
            content = (c.content or "").strip()
            if content:
                text_parts.append(f"[第{c.page_number or '?'}页]\n{content}")
                total += len(content)
                if total >= max_chars:
                    break
        return "\n\n".join(text_parts)

    def _detect_scan_document(self, chunks: List[DocumentChunk]) -> bool:
        """检测是否为扫描件（图片占比阈值）

        简化实现：检查 chunks 中是否有 OCR 标记或内容过少
        """
        if not chunks:
            return False
        # 如果所有 chunk 都标记为 table/image 类型，可能是扫描件
        image_chunks = sum(1 for c in chunks if getattr(c, "chunk_type", "") in ("image", "table"))
        return image_chunks / max(len(chunks), 1) > _SCAN_IMAGE_RATIO_THRESHOLD

    async def _extract_part(
        self,
        prompt_name: str,
        system_prompt: str,
        chunks_text: str,
        timeout: int = _PART_TIMEOUT,
    ) -> dict:
        """提取单个部分（带超时和容错）"""
        messages = [
            {"role": "system", "content": system_prompt + get_force_chinese_system_prompt()},
            {"role": "user", "content": f"招标文件内容：\n{chunks_text}"},
        ]
        try:
            raw = await asyncio.wait_for(
                self._llm.chat(messages, temperature=0.1, max_tokens=4096),
                timeout=timeout,
            )
            result = parse_llm_json(raw)
            if result and isinstance(result, dict):
                return result
            logger.warning(f"[TenderParse] {prompt_name} 解析返回非 JSON: {(raw or '')[:200]}")
            return {}
        except asyncio.TimeoutError:
            logger.warning(f"[TenderParse] {prompt_name} 提取超时（{timeout}s）")
            return {}
        except Exception as e:
            logger.warning(f"[TenderParse] {prompt_name} 提取失败: {e}")
            return {}

    def _prefer_more_complete_table(self, llm_result: dict, fallback_result: dict, key: str) -> list:
        """选行数更多的结果（LLM vs 本地 fallback）"""
        llm_list = llm_result.get(key, []) if isinstance(llm_result, dict) else []
        fallback_list = fallback_result.get(key, []) if isinstance(fallback_result, dict) else []
        if isinstance(llm_list, list) and isinstance(fallback_list, list):
            return llm_list if len(llm_list) >= len(fallback_list) else fallback_list
        return llm_list or fallback_list or []

    async def analyze_project(self, session: AsyncSession, document: Document) -> dict:
        """主入口：解析招标文档，提取 TOC + 13 维度

        流程：
        1. 获取文档全文
        2. 检测扫描件
        3. 并行提取 4 部分（TOC + Part A + Part B + Part C）
        4. 合并结果
        """
        # 1. 获取全文
        chunks_text = await self._get_chunks_text(session, document.id)
        if not chunks_text.strip():
            raise ValueError("招标文档未解析出任何内容，请先解析文档")

        # 2. 检测扫描件
        from sqlalchemy import select
        stmt = select(DocumentChunk).where(DocumentChunk.document_id == document.id)
        chunks = (await session.execute(stmt)).scalars().all()
        is_scan = self._detect_scan_document(chunks)

        # 3. 并行提取 4 部分
        toc_task = self._extract_part("TOC", TOC_PROMPT, chunks_text)
        part_a_task = self._extract_part("PartA", PART_A_PROMPT, chunks_text)
        part_b_task = self._extract_part("PartB", PART_B_PROMPT, chunks_text)
        part_c_task = self._extract_part("PartC", PART_C_PROMPT, chunks_text)

        toc_result, part_a, part_b, part_c = await asyncio.gather(
            toc_task, part_a_task, part_b_task, part_c_task,
            return_exceptions=True,
        )

        # 容错：异常转为空 dict
        if isinstance(toc_result, Exception):
            toc_result = {}
            logger.warning(f"[TenderParse] TOC 提取异常: {toc_result}")
        if isinstance(part_a, Exception):
            part_a = {}
        if isinstance(part_b, Exception):
            part_b = {}
        if isinstance(part_c, Exception):
            part_c = {}

        # 4. 合并结果
        return {
            "document_id": str(document.id),
            "is_scan_document": is_scan,
            "toc": toc_result.get("toc", []) if isinstance(toc_result, dict) else [],
            "page_ranges": toc_result.get("page_ranges", {}) if isinstance(toc_result, dict) else {},
            "part_a": part_a if isinstance(part_a, dict) else {},
            "part_b": part_b if isinstance(part_b, dict) else {},
            "part_c": part_c if isinstance(part_c, dict) else {},
            # 便捷访问
            "summary": (part_a or {}).get("summary", {}),
            "purchase_list": (part_b or {}).get("purchase_list", []),
            "tech_spec": (part_b or {}).get("tech_spec", []),
            "qualification": (part_b or {}).get("qualification", []),
            "scoring": (part_c or {}).get("scoring", {}),
            "disqualifying_items": [
                item for item in (part_b or {}).get("tech_spec", [])
                if isinstance(item, dict) and item.get("is_disqualifying")
            ],
        }


_tender_parse_service: Optional[TenderParseService] = None


def get_tender_parse_service() -> TenderParseService:
    global _tender_parse_service
    if _tender_parse_service is None:
        _tender_parse_service = TenderParseService()
    return _tender_parse_service
