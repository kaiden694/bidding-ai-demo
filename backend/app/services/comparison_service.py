"""参数偏离比对服务（AI 主导）

遵循 v1.2 设计方案"AI 优先，避免硬规则"原则：
- LLM 完成参数提取、参数对齐、同义判定、偏离结论
- 仅对数值范围比较、单位换算、容差区间做轻量确定性校验（value_check.py）
- 每条结论绑定证据链（chunk_id + 原文片段）

不包含任何固定参数映射规则、关键词命中规则或 YAML 规则包。
"""
import json
import re
import uuid
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.rag.retriever import get_rag_retriever
from app.models.comparison import ComparisonTask, ComparisonResult, ComparisonVerdict
from app.models.document import DocumentChunk
from app.models.feedback import FeedbackTargetType
from app.models.product import Product
from app.services.feedback_service import get_feedback_service
from app.utils.value_check import compare_numeric

# Phase 1 直接取文档切块喂给 LLM；Phase 2 将用 RAG 检索聚焦相关切块
_MAX_CHUNKS = 30
_CHUNK_CONTENT_LIMIT = 800
_LLM_MAX_TOKENS = 4096

SYSTEM_PROMPT = (
    "你是参数比对专家，对比招标文件参数和规格书/产品参数，"
    "识别同义表达、数值偏离、缺失项。必须引用原文片段作为证据。\n\n"
    "你的任务：\n"
    "1. 从【招标文件参数片段】中提取全部技术参数要求；\n"
    "2. 从【规格书/产品参数】中提取对应响应值；\n"
    "3. 对两侧参数做同义对齐（同一参数的不同表述归并到同一 param_name）；\n"
    "4. 逐条判定：一致(match)、偏离(deviation)、缺失(missing，招标有规格侧无)、"
    "多余(extra，规格侧有招标无)、待确认(need_confirm，语义近似需人工补证)；\n"
    "5. 每条结论必须引用原文片段作为证据，tender_evidence 与 spec_evidence 中的 "
    "chunk_id 必须来自提供的片段编号（如 [chunk_id=...] / [spec-N]）；\n"
    "6. 数值参数尽量给出 tolerance_pct（百分比容差，可空）。\n\n"
    "若提供了【专家历史修正案例】，请参考其判定倾向（如同义合并的经验、"
    "容差区间的处理），但不要照搬，仍需基于当前参数语义独立判定。\n\n"
    "仅输出如下 JSON，不要任何额外解释或 Markdown：\n"
    "{\n"
    '  "results": [\n'
    '    {\n'
    '      "param_name": "统一参数名（已同义合并）",\n'
    '      "tender_value": "招标要求值",\n'
    '      "spec_value": "规格/产品响应值",\n'
    '      "verdict": "match|deviation|missing|extra|need_confirm",\n'
    '      "confidence": 0.0到1.0的浮点数,\n'
    '      "reason": "判定理由（同义合并/偏离方向/缺失原因等）",\n'
    '      "tolerance_pct": 5.0,\n'
    '      "tender_evidence": [{"chunk_id": "...", "content": "原文片段", "page_number": 1}],\n'
    '      "spec_evidence": [{"chunk_id": "...", "content": "原文片段", "page_number": 1}]\n'
    "    }\n"
    "  ]\n"
    "}"
)

_VERDICT_MAP = {
    "match": ComparisonVerdict.MATCH,
    "deviation": ComparisonVerdict.DEVIATION,
    "missing": ComparisonVerdict.MISSING,
    "extra": ComparisonVerdict.EXTRA,
    "need_confirm": ComparisonVerdict.NEED_CONFIRM,
}


class ComparisonService:
    """参数偏离比对服务"""

    def __init__(self):
        self._llm = get_llm_client()
        # Phase 2 将用 RAG 检索聚焦相关切块（当前直接取文档切块）
        self._rag = get_rag_retriever()
        self._feedback = get_feedback_service()

    async def compare(
        self, session: AsyncSession, task: ComparisonTask
    ) -> List[ComparisonResult]:
        """主流程：委托给 ComparisonOrchestrator 执行四阶段流程
        （语义索引 → 并发分项对比 → 综合总结 → 汇总写入）

        若 orchestrator 初始化失败则降级到旧的"单次 LLM 调用"流程作为兜底。
        """
        try:
            from app.services.comparison_orchestrator import get_comparison_orchestrator

            orchestrator = get_comparison_orchestrator()
            return await orchestrator.orchestrate(session, task)
        except Exception as e:
            # orchestrator 失败时降级到旧流程（仅当 orchestrator 自身初始化失败时）
            # 已运行到 orchestrate 内部抛错时，task.status 已被置为 failed
            from loguru import logger
            logger.warning(
                f"[ComparisonService] orchestrator 初始化失败，降级到单次 LLM 流程: {e}"
            )
            return await self._legacy_compare(session, task)

    async def _legacy_compare(
        self, session: AsyncSession, task: ComparisonTask
    ) -> List[ComparisonResult]:
        """旧流程兜底：单次 LLM 调用输出全部 results（无四阶段、无校准缓存）"""
        task.status = "running"
        task.progress = 0.1
        await session.commit()

        try:
            tender_chunks = await self._fetch_chunks(session, task.tender_doc_id)
            if not tender_chunks:
                raise ValueError("招标文件未解析出任何切块，请先解析文档")
            spec_side = await self._fetch_spec_side(session, task)

            feedback_examples = await self._recall_feedback_examples(
                session, tender_chunks, spec_side
            )

            messages = self._build_prompt(tender_chunks, spec_side, feedback_examples)
            task.progress = 0.3
            await session.commit()

            raw = await self._llm.chat(
                messages, temperature=0.1, max_tokens=_LLM_MAX_TOKENS
            )
            items = self._parse_results(raw)

            results: List[ComparisonResult] = []
            for it in items:
                cr = self._build_result(task, it)
                results.append(cr)
                session.add(cr)

            task.summary = self._summarize(results)
            task.status = "done"
            task.progress = 1.0
            await session.commit()
            return results
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            await session.commit()
            raise

    # ------------------------------------------------------------------
    # 反馈召回（T5.3：few-shot 注入）
    # ------------------------------------------------------------------
    async def _recall_feedback_examples(
        self,
        session: AsyncSession,
        tender_chunks: List[DocumentChunk],
        spec_side: dict,
    ) -> List[dict]:
        """召回与本次比对上下文相似的历史专家修正，作为 LLM few-shot

        - 用首批招标切块内容 + 首条 spec 项作为查询文本
        - 召回失败不阻断主流程
        """
        # 构造查询文本
        query_parts = []
        if tender_chunks:
            query_parts.append((tender_chunks[0].content or "")[:200])
        if spec_side["kind"] == "product":
            specs = spec_side.get("specs") or []
            if specs:
                first = specs[0]
                query_parts.append(
                    f"{first.get('name', '')}={first.get('value', '')}{first.get('unit', '')}"
                )
        elif spec_side["kind"] == "doc":
            chunks = spec_side.get("chunks") or []
            if chunks:
                query_parts.append((chunks[0].content or "")[:200])
        query_text = "\n".join(p for p in query_parts if p)
        if not query_text.strip():
            return []

        try:
            records = await self._feedback.recall_similar_feedback(
                session,
                target_type=FeedbackTargetType.COMPARISON,
                query_text=query_text,
                top_k=3,
            )
        except Exception:
            return []
        return [
            {
                "context_key": r.context_key,
                "context_text": (r.context_text or "")[:200],
                "original_verdict": r.original_verdict,
                "corrected_verdict": r.corrected_verdict,
                "correction_reason": r.correction_reason,
            }
            for r in records
        ]

    # ------------------------------------------------------------------
    # 数据获取
    # ------------------------------------------------------------------
    async def _fetch_chunks(
        self, session: AsyncSession, doc_id: Optional[uuid.UUID], limit: int = _MAX_CHUNKS
    ) -> List[DocumentChunk]:
        if doc_id is None:
            return []
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _fetch_spec_side(self, session: AsyncSession, task: ComparisonTask) -> dict:
        """响应侧来源：spec_doc_id（规格书切块）或 product_id（产品 specs）"""
        if task.spec_doc_id:
            chunks = await self._fetch_chunks(session, task.spec_doc_id)
            return {"kind": "doc", "chunks": chunks}
        if task.product_id:
            product = await session.get(Product, task.product_id)
            if not product:
                raise ValueError("产品不存在")
            return {"kind": "product", "product": product, "specs": product.specs or []}
        raise ValueError("未提供规格书文档或产品选型")

    # ------------------------------------------------------------------
    # Prompt 组装
    # ------------------------------------------------------------------
    def _build_prompt(
        self,
        tender_chunks: List[DocumentChunk],
        spec_side: dict,
        feedback_examples: Optional[List[dict]] = None,
    ) -> list[dict]:
        tender_text = self._format_chunks(tender_chunks)
        if spec_side["kind"] == "doc":
            spec_text = self._format_chunks(spec_side["chunks"])
            spec_label = "规格书参数片段"
        else:
            spec_text = self._format_specs(spec_side["specs"], spec_side["product"])
            spec_label = "产品参数（specs）"
        few_shot_text = self._format_feedback_examples(feedback_examples)
        sections = [
            f"【招标文件参数片段】\n{tender_text}",
            f"【{spec_label}】\n{spec_text}",
        ]
        if few_shot_text:
            sections.append(f"【专家历史修正案例】（参考判定倾向，不照搬）\n{few_shot_text}")
        sections.append("请按系统指令输出 JSON。")
        user = "\n\n".join(sections)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _format_feedback_examples(examples: Optional[List[dict]]) -> str:
        """格式化专家历史修正为 few-shot 文本"""
        if not examples:
            return ""
        lines = []
        for i, ex in enumerate(examples, 1):
            ctx_key = ex.get("context_key") or "-"
            ctx_text = (ex.get("context_text") or "").strip().replace("\n", " ")[:150]
            original = ex.get("original_verdict", "")
            corrected = ex.get("corrected_verdict", "")
            reason = (ex.get("correction_reason") or "").strip().replace("\n", " ")[:300]
            lines.append(
                f"[案例{i}] 参数/上下文：{ctx_key}\n"
                f"  上下文：{ctx_text}\n"
                f"  原判定：{original} → 修正为：{corrected}\n"
                f"  修正理由：{reason}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _format_chunks(chunks: List[DocumentChunk]) -> str:
        if not chunks:
            return "（无）"
        lines = []
        for c in chunks:
            page = f" 第{c.page_number}页" if c.page_number else ""
            section = f" 章节:{c.section}" if c.section else ""
            content = (c.content or "").strip()
            if len(content) > _CHUNK_CONTENT_LIMIT:
                content = content[:_CHUNK_CONTENT_LIMIT] + "…"
            lines.append(f"[chunk_id={c.id}{page}{section}]\n{content}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_specs(specs: List[dict], product: Product) -> str:
        lines = [
            f"产品：{product.name} 型号:{product.model or '-'} 品牌:{product.brand or '-'}"
        ]
        if not specs:
            lines.append("（无 specs 参数）")
            return "\n".join(lines)
        for i, s in enumerate(specs):
            name = s.get("name", "")
            value = s.get("value", "")
            unit = s.get("unit", "")
            tol = s.get("tolerance", "")
            remarks = s.get("remarks", "")
            line = f"[spec-{i}] {name}={value}{unit}".strip()
            if tol:
                line += f" 容差:{tol}"
            if remarks:
                line += f" 备注:{remarks}"
            lines.append(line)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM 输出解析与结果构建
    # ------------------------------------------------------------------
    def _parse_results(self, raw: str) -> List[dict]:
        text = (raw or "").strip()
        # 去除 markdown 代码块围栏
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM 返回非合法 JSON")
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 返回 JSON 解析失败: {e}")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError("LLM 返回缺少 results 数组")
        return results

    def _build_result(self, task: ComparisonTask, item: dict) -> ComparisonResult:
        tender_value = item.get("tender_value")
        spec_value = item.get("spec_value")
        verdict = self._normalize_verdict(item.get("verdict"))
        confidence = self._clamp_confidence(item.get("confidence"))
        reason = item.get("reason") or ""

        # 数值单位轻量校验：仅当两侧均为数值且单位可换算时，确定性结论优先于 LLM；
        # 非数值或单位不可比时保留 LLM 的语义判定。
        tol = self._to_float(item.get("tolerance_pct"))
        numeric_verdict = compare_numeric(tender_value, spec_value, tol)
        if numeric_verdict in ("match", "deviation"):
            note = "一致" if numeric_verdict == "match" else "偏离"
            if verdict.value != numeric_verdict:
                reason = (reason + f" [数值校验:{note}]").strip()
            verdict = _VERDICT_MAP[numeric_verdict]
            # 数值确定性结论可信度兜底
            confidence = max(confidence, 0.85)

        return ComparisonResult(
            task_id=task.id,
            param_name=(item.get("param_name") or "未命名参数").strip(),
            tender_value=self._to_text(tender_value),
            spec_value=self._to_text(spec_value),
            verdict=verdict,
            confidence=confidence,
            reason=reason or None,
            tender_evidence=self._normalize_evidence(item.get("tender_evidence")),
            spec_evidence=self._normalize_evidence(item.get("spec_evidence")),
        )

    @staticmethod
    def _normalize_verdict(v) -> ComparisonVerdict:
        if isinstance(v, ComparisonVerdict):
            return v
        key = str(v or "").strip().lower()
        return _VERDICT_MAP.get(key, ComparisonVerdict.NEED_CONFIRM)

    @staticmethod
    def _clamp_confidence(v) -> Optional[float]:
        f = ComparisonService._to_float(v)
        if f is None:
            return None
        return max(0.0, min(1.0, f))

    @staticmethod
    def _to_float(v) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_text(v) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @staticmethod
    def _normalize_evidence(ev) -> Optional[list]:
        if not ev or not isinstance(ev, list):
            return None
        cleaned = []
        for e in ev:
            if isinstance(e, dict):
                cleaned.append(e)
            else:
                cleaned.append({"content": str(e)})
        return cleaned or None

    @staticmethod
    def _summarize(results: List[ComparisonResult]) -> dict:
        summary = {
            "total": len(results),
            "match": 0,
            "deviation": 0,
            "missing": 0,
            "extra": 0,
            "need_confirm": 0,
        }
        for r in results:
            key = r.verdict.value if isinstance(r.verdict, ComparisonVerdict) else str(r.verdict)
            if key in summary:
                summary[key] += 1
        return summary


_comparison_service: Optional[ComparisonService] = None


def get_comparison_service() -> ComparisonService:
    global _comparison_service
    if _comparison_service is None:
        _comparison_service = ComparisonService()
    return _comparison_service
