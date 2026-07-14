"""
资质台账服务（Phase 2）

设计要点（v1.2 §13 AI 优先）：
- extract_fields: OCR（rapidocr-onnxruntime，通过 DocumentParser 调用）→ LLM 结构化字段提取
- LLM Prompt 输出 JSON，字段提取 + 置信度评估
- 置信度低于 0.8 标记"待人工确认"（仅事实性阈值，非风险判定）
- 不写硬规则的字段名映射表，由 LLM 语义理解资质证书文本结构
"""
import json
import re
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.parsing.parser import DocumentParser
from app.core.config import settings
from app.core.minio_client import minio_client
from app.models.document import Document, DocumentType, DocParseStatus
from app.models.qualification import Qualification, QualificationType


# 字段提取置信度阈值（低于此值标记待人工确认）
_CONFIDENCE_THRESHOLD = 0.8

# LLM 提取资质字段的 Prompt
EXTRACT_SYSTEM_PROMPT = """你是资质证书字段提取专家。

任务：从 OCR 识别的资质证书文本中提取结构化字段。

输出 JSON，字段如下（无对应内容时填 null）：
{
  "name": "资质名称",
  "qual_type": "enterprise|supplier|product|personnel 之一",
  "cert_number": "证书编号",
  "issuer": "发证机构",
  "scope": "资质范围/业务范围",
  "issue_date": "YYYY-MM-DD 或 null",
  "expire_date": "YYYY-MM-DD 或 null（长期有效填 null）",
  "owner": "持有方/单位名称",
  "supplier_name": "供应商名称（仅供应商资质时填写）",
  "confidence": 0.0到1.0的浮点数（字段提取整体置信度）
}

判定规则：
- 资质类型（qual_type）依据证书标题/内容语义判断，不靠关键词匹配
- 日期格式统一输出 YYYY-MM-DD
- confidence 反映 OCR 文本清晰度与字段匹配度

仅输出 JSON，不要额外解释或 Markdown 代码块。"""


class QualificationService:
    """资质台账服务：OCR + LLM 字段提取"""

    def __init__(self):
        self._llm = get_llm_client()
        self._parser = DocumentParser()

    async def extract_fields(
        self, session: AsyncSession, qualification_id: uuid.UUID
    ) -> dict:
        """从资质证书 PDF 提取结构化字段

        流程：
        1. 查询资质记录，获取关联的 document_id
        2. 从 MinIO 拉取证书文件 → OCR 解析
        3. LLM 提取结构化字段（JSON 输出）
        4. 更新资质记录字段
        5. 置信度 < 0.8 标记 metadata.need_review = True

        返回：提取结果 + 是否待人工确认
        """
        qual = await session.get(Qualification, qualification_id)
        if not qual:
            raise ValueError("资质记录不存在")
        if not qual.document_id:
            raise ValueError("资质未关联证书文档，请先上传证书")

        # 1. 拉取证书文件
        doc = await session.get(Document, qual.document_id)
        if not doc:
            raise ValueError("关联的证书文档不存在")
        try:
            obj = minio_client.get_object(settings.MINIO_BUCKET, doc.file_key)
            file_bytes = obj.read()
            obj.close()
        except Exception as e:
            raise ValueError(f"从 MinIO 拉取证书文件失败: {e}")

        # 2. OCR 解析（DocumentParser 内置 OCR fallback）
        parse_result = await self._parser.parse(file_bytes, doc.name, doc.mime_type or "")
        ocr_text = "\n\n".join(c.content for c in parse_result.chunks if c.content)
        if not ocr_text.strip():
            raise ValueError("OCR 未识别出任何文本，证书可能为扫描件质量过低")

        # 3. LLM 提取结构化字段
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"证书 OCR 文本：\n{ocr_text}"},
        ]
        raw = await self._llm.chat(messages, temperature=0.1, max_tokens=2048)
        fields = self._parse_llm_output(raw)

        # 4. 更新资质记录字段
        confidence = self._clamp(fields.get("confidence"), 0.0, 1.0)
        need_review = confidence < _CONFIDENCE_THRESHOLD

        if fields.get("name"):
            qual.name = fields["name"]
        if fields.get("qual_type"):
            qual.qual_type = self._normalize_qual_type(fields["qual_type"])
        if fields.get("cert_number"):
            qual.cert_number = fields["cert_number"]
        if fields.get("issuer"):
            qual.issuer = fields["issuer"]
        if fields.get("scope"):
            qual.scope = fields["scope"]
        if fields.get("issue_date"):
            qual.issue_date = self._parse_date(fields["issue_date"])
        if fields.get("expire_date"):
            qual.expire_date = self._parse_date(fields["expire_date"])
        if fields.get("owner"):
            qual.owner = fields["owner"]
        if fields.get("supplier_name"):
            qual.supplier_name = fields["supplier_name"]

        # 5. 元数据：置信度 + 待人工确认标记 + OCR 文本
        meta = dict(qual.metadata_json or {})
        meta.update({
            "extract_confidence": confidence,
            "need_review": need_review,
            "ocr_text": ocr_text[:2000],  # 截断保存，避免过大
            "extracted_at": datetime.utcnow().isoformat(),
        })
        qual.metadata_json = meta
        await session.commit()

        return {
            "qualification_id": str(qual.id),
            "fields": fields,
            "confidence": confidence,
            "need_review": need_review,
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _parse_llm_output(self, raw: str) -> dict:
        """解析 LLM 输出的 JSON（容错：去 markdown 围栏 + 提取首个 JSON 对象）"""
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning(f"LLM 资质字段提取返回非 JSON: {text[:200]}")
            return {}
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 资质字段 JSON 解析失败: {e}")
            return {}

    @staticmethod
    def _clamp(v, lo: float, hi: float) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(lo, min(hi, f))

    @staticmethod
    def _normalize_qual_type(v) -> QualificationType:
        if isinstance(v, QualificationType):
            return v
        key = str(v or "").strip().lower()
        for t in QualificationType:
            if t.value == key:
                return t
        return QualificationType.ENTERPRISE

    @staticmethod
    def _parse_date(v):
        """解析日期字符串为 date 对象（容错：仅 YYYY-MM-DD）"""
        if not v:
            return None
        from datetime import date
        s = str(v).strip()[:10]
        try:
            from datetime import datetime
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


_qualification_service: Optional[QualificationService] = None


def get_qualification_service() -> QualificationService:
    global _qualification_service
    if _qualification_service is None:
        _qualification_service = QualificationService()
    return _qualification_service
