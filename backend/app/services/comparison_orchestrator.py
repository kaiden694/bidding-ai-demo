"""AI 比对四阶段协调器（P0-1）

参考 lib-v0.2 ai_comparator.py 的四阶段流程：
1. 构建语义索引：LLM 从招标文件切块一次性提取参数清单（param_name + tender_value + 证据定位）
2. 并发分项对比：asyncio.gather + asyncio.wait_for(60s) 对每项参数独立 LLM 判定，
   命中校准缓存（相似度 > 0.90）直接采用历史判定跳过 LLM
3. 综合总结：LLM 综合全表生成"差异总览 + 推荐选型"
4. 汇总写入：ComparisonResult + EvidenceSpan + FeedbackRecord(校准源)

设计原则（v1.2 §13 AI 优先）：
- 每项参数独立 prompt（招标要求 + 规格响应 + 召回证据 + 语义等价原则）
- 校准缓存作为可演进知识资产，不是硬规则
- 证据链绑定 evidence_span_id 实现全链路可追溯
- LLM 响应统一走 parse_llm_json 多重容错
"""
import asyncio
import json
import uuid
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding.client import get_embedding_client
from app.ai.llm.client import get_llm_client
from app.ai.llm.response_parser import (
    parse_llm_json,
    parse_llm_json_field,
    ensure_chinese,
    get_force_chinese_system_prompt,
)
from app.ai.retrieval.hybrid import hybrid_search
from app.ai.retrieval.quality_service import refine
from app.models.comparison import ComparisonTask, ComparisonResult, ComparisonVerdict
from app.models.document import DocumentChunk
from app.models.product import Product
from app.services.calibration_service import get_calibration_service
from app.services.evidence_service import get_evidence_service
from app.utils.value_check import compare_numeric

# 超时与并发上限
_ITEM_TIMEOUT_SECONDS = 60          # 单项参数 LLM 调用超时
_MAX_CONCURRENCY = 5                # 并发 LLM 调用上限（避免压垮 provider）
_LLM_MAX_TOKENS = 4096
_PARAM_EXTRACTION_TOKENS = 4096
_SUMMARY_TOKENS = 2048

# 文档切块取数上限
_MAX_TENDER_CHUNKS = 30
_MAX_SPEC_CHUNKS = 30
_CHUNK_CONTENT_LIMIT = 800
_RECALL_TOP_K = 5

# 校准相似度阈值（低于此值不采用历史判定）
_CALIBRATION_MIN_SIM = 0.90

_VERDICT_MAP = {
    "match": ComparisonVerdict.MATCH,
    "deviation": ComparisonVerdict.DEVIATION,
    "missing": ComparisonVerdict.MISSING,
    "extra": ComparisonVerdict.EXTRA,
    "need_confirm": ComparisonVerdict.NEED_CONFIRM,
    "一致": ComparisonVerdict.MATCH,
    "偏离": ComparisonVerdict.DEVIATION,
    "缺失": ComparisonVerdict.MISSING,
    "多余": ComparisonVerdict.EXTRA,
    "待确认": ComparisonVerdict.NEED_CONFIRM,
}


# ============================================================
# Prompt 模板
# ============================================================
# 阶段 1：从招标文件切块中提取参数清单
EXTRACT_PARAMS_PROMPT = (
    "你是参数提取专家。从给定的【招标文件片段】中提取全部技术参数要求，"
    "每条参数必须给出 param_name（统一参数名）、tender_value（招标要求值）、"
    "tender_evidence（含 chunk_id 与原文片段）。\n\n"
    "要求：\n"
    "1. 同一参数的不同表述归并到同一 param_name；\n"
    "2. tender_evidence.chunk_id 必须来自提供的片段编号；\n"
    "3. tender_value 保留原文表述（数值 + 单位 + 容差）；\n"
    "4. 数值参数可附 tolerance_pct（百分比容差）。\n\n"
    "仅输出如下 JSON：\n"
    '{"results": [{"param_name": "...", "tender_value": "...", '
    '"tolerance_pct": null, "tender_evidence": [{"chunk_id": "...", "content": "原文片段", "page_number": 1}]}]}'
    + get_force_chinese_system_prompt()
)

# 阶段 2：单参数对比 prompt（运行时拼接招标要求 + 召回规格响应 + 证据）
COMPARE_ITEM_PROMPT_TEMPLATE = (
    "你是参数比对专家。请基于以下信息判定单个参数的偏离状态：\n\n"
    "【招标要求】\n{tender_value}\n\n"
    "【规格/产品响应片段】\n{spec_text}\n\n"
    "【召回证据】\n{evidence_text}\n\n"
    "判定规则：\n"
    "1. 优先使用语义等价原则（同义表达、单位换算、容差区间内）→ match；\n"
    "2. 数值/单位可换算时做容差判定 → match / deviation；\n"
    "3. 规格侧无对应 → missing；规格侧多出 → extra；语义近似无法确定 → need_confirm；\n"
    "4. 必须引用原文片段作为证据（spec_evidence.chunk_id 必须来自上方规格片段编号）。\n\n"
    "仅输出如下 JSON：\n"
    '{{"verdict": "match|deviation|missing|extra|need_confirm", '
    '"spec_value": "...", "confidence": 0.0到1.0, "reason": "判定理由", '
    '"tolerance_pct": null, '
    '"spec_evidence": [{{"chunk_id": "...", "content": "原文片段", "page_number": 1}}]}}'
    + get_force_chinese_system_prompt()
)

# 阶段 3：综合总结 prompt
SUMMARY_PROMPT_TEMPLATE = (
    "你是参数比对专家。基于以下比对全表，生成差异总览与推荐选型：\n\n"
    "{comparison_table}\n\n"
    "要求：\n"
    "1. 差异总览：按 verdict 分组列出关键偏离项；\n"
    "2. 推荐选型：综合判定（推荐/有条件推荐/不推荐），给出依据；\n"
    "3. 风险提示：列出高风险偏离项。\n\n"
    "仅输出如下 JSON：\n"
    '{{"diff_overview": "差异总览文本", '
    '"recommendation": "推荐/有条件推荐/不推荐", '
    '"recommendation_reason": "推荐理由", '
    '"risk_items": ["风险项1", "风险项2"]}}'
    + get_force_chinese_system_prompt()
)


class ComparisonOrchestrator:
    """AI 比对四阶段协调器"""

    def __init__(self):
        self._llm = get_llm_client()
        self._embedding_client = get_embedding_client()
        self._calibration = get_calibration_service()
        self._evidence = get_evidence_service()

    # ============================================================
    # 主入口：四阶段流程
    # ============================================================
    async def orchestrate(
        self, session: AsyncSession, task: ComparisonTask
    ) -> List[ComparisonResult]:
        """四阶段主流程"""
        task.status = "running"
        task.progress = 0.05
        await session.commit()

        try:
            # ===== 阶段 1：构建语义索引 =====
            logger.info(f"[Orchestrator] T{task.id} 阶段1: 构建语义索引")
            params = await self._stage1_extract_params(session, task)
            if not params:
                raise ValueError("招标文件未提取出任何参数")
            task.progress = 0.25
            await session.commit()

            # ===== 阶段 2：并发分项对比 =====
            logger.info(
                f"[Orchestrator] T{task.id} 阶段2: 并发对比 {len(params)} 项参数"
            )
            results = await self._stage2_compare_items(session, task, params)
            task.progress = 0.75
            await session.commit()

            # ===== 阶段 3：综合总结 =====
            logger.info(f"[Orchestrator] T{task.id} 阶段3: 综合总结")
            summary = await self._stage3_summarize(session, results)
            task.progress = 0.90
            await session.commit()

            # ===== 阶段 4：汇总写入 =====
            logger.info(f"[Orchestrator] T{task.id} 阶段4: 汇总写入")
            await self._stage4_persist(session, task, results, summary)
            task.summary = summary
            task.status = "done"
            task.progress = 1.0
            await session.commit()
            return results
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            await session.commit()
            raise

    # ============================================================
    # 阶段 1：从招标文件提取参数清单（LLM 一次性提取）
    # ============================================================
    async def _stage1_extract_params(
        self, session: AsyncSession, task: ComparisonTask
    ) -> List[dict]:
        tender_chunks = await self._fetch_chunks(session, task.tender_doc_id, _MAX_TENDER_CHUNKS)
        if not tender_chunks:
            raise ValueError("招标文件未解析出任何切块，请先解析文档")

        tender_text = self._format_chunks(tender_chunks)
        messages = [
            {"role": "system", "content": EXTRACT_PARAMS_PROMPT},
            {"role": "user", "content": f"【招标文件片段】\n{tender_text}"},
        ]
        raw = await self._llm.chat(
            messages, temperature=0.1, max_tokens=_PARAM_EXTRACTION_TOKENS
        )
        items = parse_llm_json_field(raw, "results", default=[])
        if not isinstance(items, list):
            return []

        # 记录提取过程（证据链：source_file + extraction_run + spans）
        try:
            source_file = await self._evidence.get_or_create_source_file(
                session, domain="tender", source_table="document",
                source_id=task.tender_doc_id, file_name=f"tender_{task.tender_doc_id}",
            )
            extraction_run = await self._evidence.create_extraction_run(
                session, source_file_id=source_file.id,
                extractor_type="llm", model_name=self._llm_model_name(),
                prompt_text=EXTRACT_PARAMS_PROMPT, parser_version="orchestrator_v1",
            )
            # 为每条参数的 tender_evidence 创建 evidence_span
            for item in items:
                ev_list = item.get("tender_evidence") or []
                for ev in ev_list[:1]:  # 每条参数取首条证据落库
                    await self._evidence.create_evidence_span(
                        session, source_file_id=source_file.id,
                        quote_text=(ev.get("content") or "")[:1000],
                        page_number=ev.get("page_number"),
                        field_name=item.get("param_name"),
                        confidence=0.85,
                        extraction_run_id=extraction_run.id,
                    )
        except Exception as e:
            logger.warning(f"[Orchestrator] 阶段1 证据链落库失败（不阻断主流程）: {e}")

        return items

    # ============================================================
    # 阶段 2：并发分项对比（asyncio.gather + wait_for 60s + 校准缓存覆盖）
    # ============================================================
    async def _stage2_compare_items(
        self, session: AsyncSession, task: ComparisonTask, params: List[dict]
    ) -> List[ComparisonResult]:
        # 预取规格侧数据（避免每个 item 重复查询）
        spec_side = await self._fetch_spec_side(session, task)

        # 信号量限制并发
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def _compare_one(idx: int, param: dict) -> ComparisonResult:
            async with sem:
                return await asyncio.wait_for(
                    self._compare_single_item(session, task, idx, param, spec_side),
                    timeout=_ITEM_TIMEOUT_SECONDS,
                )

        # gather 并发执行
        tasks_list = [_compare_one(i, p) for i, p in enumerate(params)]
        gathered = await asyncio.gather(*tasks_list, return_exceptions=True)

        results: List[ComparisonResult] = []
        for idx, ret in enumerate(gathered):
            if isinstance(ret, Exception):
                logger.warning(
                    f"[Orchestrator] 参数#{idx} 对比失败: {ret}，降级为 need_confirm"
                )
                cr = self._build_fallback_result(task, params[idx], ret)
                results.append(cr)
                session.add(cr)
            else:
                results.append(ret)
                session.add(ret)
        return results

    async def _compare_single_item(
        self, session: AsyncSession, task: ComparisonTask,
        idx: int, param: dict, spec_side: dict,
    ) -> ComparisonResult:
        param_name = (param.get("param_name") or f"参数#{idx}").strip()
        tender_value = self._to_text(param.get("tender_value"))
        tender_evidence = param.get("tender_evidence") or []
        tolerance_pct = self._to_float(param.get("tolerance_pct"))

        # 校准缓存覆盖：相似度 > 阈值直接采用历史判定
        cache_hit = await self._find_calibration_cache(session, param_name, tender_value)
        if cache_hit:
            logger.info(
                f"[Orchestrator] 参数#{idx} {param_name} 命中校准缓存 (sim={cache_hit['similarity']:.3f})"
            )
            return self._build_result_from_cache(
                task, param_name, tender_value, tender_evidence, cache_hit, tolerance_pct
            )

        # 召回规格侧相关切块
        recalled = await self._recall_spec_evidence(
            session, task, spec_side, param_name, tender_value
        )
        spec_text = self._format_recall_chunks(recalled)
        evidence_text = self._format_recall_evidence(recalled)

        # 构造单参数对比 prompt
        prompt = COMPARE_ITEM_PROMPT_TEMPLATE.format(
            tender_value=tender_value or "（未明确）",
            spec_text=spec_text or "（无规格侧响应）",
            evidence_text=evidence_text or "（无召回证据）",
        )
        messages = [
            {"role": "system", "content": prompt},
        ]
        raw = await self._llm.chat(
            messages, temperature=0.1, max_tokens=_LLM_MAX_TOKENS
        )
        data = parse_llm_json(raw) or {}

        verdict_str = ensure_chinese(str(data.get("verdict") or "")).lower()
        # 把中文判定翻译回枚举 key
        verdict_key = self._normalize_verdict_key(verdict_str)
        verdict = _VERDICT_MAP.get(verdict_key, ComparisonVerdict.NEED_CONFIRM)
        confidence = self._clamp_confidence(data.get("confidence"))
        reason = ensure_chinese(data.get("reason") or "")
        spec_value = self._to_text(data.get("spec_value"))
        spec_evidence = data.get("spec_evidence") or []

        # 数值单位轻量校验：两侧均为数值且单位可换算 → 确定性结论优先
        numeric_verdict = compare_numeric(tender_value, spec_value, tolerance_pct)
        if numeric_verdict in ("match", "deviation"):
            note = "一致" if numeric_verdict == "match" else "偏离"
            if verdict.value != numeric_verdict:
                reason = (reason + f" [数值校验:{note}]").strip()
            verdict = _VERDICT_MAP[numeric_verdict]
            confidence = max(confidence or 0.0, 0.85)

        # 创建证据 span（spec 侧）
        evidence_span_id = await self._create_spec_evidence_span(
            session, task, param_name, spec_evidence, recalled
        )

        # 记录校准源（供未来命中）
        await self._record_calibration_cache(
            session, param_name, tender_value, verdict.value,
            reason, confidence or 0.8
        )

        return ComparisonResult(
            task_id=task.id,
            param_name=param_name,
            tender_value=tender_value,
            spec_value=spec_value,
            verdict=verdict,
            confidence=confidence,
            reason=reason or None,
            tender_evidence=self._normalize_evidence(tender_evidence),
            spec_evidence=self._normalize_evidence(spec_evidence),
            evidence_span_id=evidence_span_id,
        )

    # ============================================================
    # 阶段 3：综合总结（LLM 综合全表生成差异总览 + 推荐选型）
    # ============================================================
    async def _stage3_summarize(
        self, session: AsyncSession, results: List[ComparisonResult]
    ) -> dict:
        # 构建比对全表文本
        table_lines = ["| 参数 | 招标值 | 规格值 | 判定 | 置信度 | 理由 |"]
        table_lines.append("|---|---|---|---|---|---|")
        for r in results:
            verdict_zh = ensure_chinese(r.verdict.value)
            table_lines.append(
                f"| {r.param_name} | {(r.tender_value or '-')[:50]} | "
                f"{(r.spec_value or '-')[:50]} | {verdict_zh} | "
                f"{r.confidence or 0:.2f} | {(r.reason or '-')[:80]} |"
            )
        table = "\n".join(table_lines)

        messages = [
            {"role": "system", "content": SUMMARY_PROMPT_TEMPLATE.format(comparison_table=table)},
        ]
        raw = await self._llm.chat(
            messages, temperature=0.2, max_tokens=_SUMMARY_TOKENS
        )
        data = parse_llm_json(raw) or {}

        # 合并统计 + LLM 总结
        stats = self._summarize_stats(results)
        return {
            **stats,
            "diff_overview": ensure_chinese(data.get("diff_overview") or ""),
            "recommendation": ensure_chinese(data.get("recommendation") or ""),
            "recommendation_reason": ensure_chinese(data.get("recommendation_reason") or ""),
            "risk_items": [
                ensure_chinese(x) for x in (data.get("risk_items") or []) if x
            ],
        }

    # ============================================================
    # 阶段 4：汇总写入（含废标风险扫描）
    # ============================================================
    async def _stage4_persist(
        self, session: AsyncSession, task: ComparisonTask,
        results: List[ComparisonResult], summary: dict,
    ) -> None:
        # 确保所有结果已 add 到 session
        for r in results:
            if r not in session:
                session.add(r)

        # 废标风险扫描（P2-11 T11.2）：
        # 对 is_disqualifying=true 的条款，verdict != match 时标记为废标风险
        try:
            from app.services.disqualifying_risk_service import get_disqualifying_risk_service
            dq_service = get_disqualifying_risk_service()
            marked = await dq_service.scan_and_mark(session, task, results)
            if marked > 0:
                logger.info(f"[Orchestrator] T{task.id} 标记 {marked} 项废标风险")
                # 废标风险写入 summary
                summary["disqualifying_count"] = marked
                summary["disqualifying_params"] = [
                    r.param_name for r in results if r.is_disqualifying
                ]
        except Exception as e:
            logger.warning(f"[Orchestrator] 废标风险扫描失败（不阻断）: {e}")

        # summary 在主入口统一写入 task.summary
        logger.info(
            f"[Orchestrator] T{task.id} 完成: {len(results)} 条结果, "
            f"推荐={summary.get('recommendation', '-')}, "
            f"废标风险={summary.get('disqualifying_count', 0)}"
        )

    # ============================================================
    # 数据获取辅助
    # ============================================================
    async def _fetch_chunks(
        self, session: AsyncSession, doc_id: Optional[uuid.UUID], limit: int
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
            chunks = await self._fetch_chunks(session, task.spec_doc_id, _MAX_SPEC_CHUNKS)
            return {"kind": "doc", "chunks": chunks, "doc_id": task.spec_doc_id}
        if task.product_id:
            product = await session.get(Product, task.product_id)
            if not product:
                raise ValueError("产品不存在")
            return {"kind": "product", "product": product, "specs": product.specs or []}
        raise ValueError("未提供规格书文档或产品选型")

    async def _recall_spec_evidence(
        self, session: AsyncSession, task: ComparisonTask,
        spec_side: dict, param_name: str, tender_value: str,
    ) -> List[DocumentChunk]:
        """从规格侧召回与当前参数相关的切块"""
        # 构造查询文本
        query_text = f"{param_name} {tender_value or ''}".strip()
        if not query_text:
            return []

        # 优先走混合检索（向量 + 词法）
        if spec_side["kind"] == "doc":
            try:
                query_embedding = await self._embedding_client.embed_one(query_text)
            except Exception as e:
                logger.warning(f"[Orchestrator] embedding 失败，降级到词法召回: {e}")
                query_embedding = None

            try:
                recalled_raw = await hybrid_search(
                    session, DocumentChunk, query_text,
                    query_embedding=query_embedding,
                    top_k=_RECALL_TOP_K * 2,
                    filters={"document_id": spec_side["doc_id"]},
                )
                refined = await refine(recalled_raw, query_text, top_k=_RECALL_TOP_K)
                return [c for c, _ in refined]
            except Exception as e:
                logger.warning(f"[Orchestrator] 混合检索失败，降级取首批切块: {e}")

            # 降级：取前 N 个切块
            return spec_side["chunks"][:_RECALL_TOP_K]

        # 产品选型：直接过滤 specs（不做向量召回）
        return []

    # ============================================================
    # 校准缓存
    # ============================================================
    async def _find_calibration_cache(
        self, session: AsyncSession, param_name: str, tender_value: str,
    ) -> Optional[dict]:
        query_text = f"{param_name} {tender_value or ''}".strip()
        try:
            hit = await self._calibration.find_calibration(
                session, query_text=query_text, scope=param_name, top_k=3
            )
            if hit and hit.get("similarity", 0) >= _CALIBRATION_MIN_SIM:
                return hit
        except Exception as e:
            logger.warning(f"[Orchestrator] 校准缓存查询失败: {e}")
        return None

    async def _record_calibration_cache(
        self, session: AsyncSession, param_name: str, tender_value: str,
        judgment: str, reason: str, confidence: float,
    ) -> None:
        try:
            # 用 param_name + tender_value 作为 context_text（与查询文本对齐）
            context_text = f"{param_name} {tender_value or ''}".strip()
            await self._calibration.record_calibration(
                session, target_id=uuid.uuid4(),  # 占位，比对完成后回填 result_id
                context_text=context_text,
                judgment=judgment,
                original_verdict=judgment,  # orchestrator 输出即原判定
                reason=reason,
                scope=param_name,
                confidence=confidence,
            )
        except Exception as e:
            logger.warning(f"[Orchestrator] 校准源写入失败（不阻断）: {e}")

    def _build_result_from_cache(
        self, task: ComparisonTask, param_name: str, tender_value: Optional[str],
        tender_evidence: list, cache: dict, tolerance_pct: Optional[float],
    ) -> ComparisonResult:
        verdict_str = str(cache.get("judgment") or "").lower()
        verdict_key = self._normalize_verdict_key(verdict_str)
        verdict = _VERDICT_MAP.get(verdict_key, ComparisonVerdict.NEED_CONFIRM)
        confidence = max(float(cache.get("confidence") or 0.85), 0.85)
        reason = f"[校准缓存 sim={cache.get('similarity', 0):.3f}] " + (cache.get("reason") or "")

        return ComparisonResult(
            task_id=task.id,
            param_name=param_name,
            tender_value=tender_value,
            spec_value=None,  # 缓存命中时无新规格值
            verdict=verdict,
            confidence=confidence,
            reason=reason,
            tender_evidence=self._normalize_evidence(tender_evidence),
            spec_evidence=None,
            evidence_span_id=None,
        )

    # ============================================================
    # 证据 span 落库（spec 侧）
    # ============================================================
    async def _create_spec_evidence_span(
        self, session: AsyncSession, task: ComparisonTask,
        param_name: str, spec_evidence: list, recalled: List[DocumentChunk],
    ) -> Optional[uuid.UUID]:
        try:
            source_file = await self._evidence.get_or_create_source_file(
                session, domain="spec",
                source_table="document" if task.spec_doc_id else "product",
                source_id=task.spec_doc_id or task.product_id,
                file_name=f"spec_{task.spec_doc_id or task.product_id}",
            )
            # 优先用 LLM 输出的 spec_evidence
            if spec_evidence:
                ev = spec_evidence[0] if isinstance(spec_evidence, list) else {}
                span = await self._evidence.create_evidence_span(
                    session, source_file_id=source_file.id,
                    quote_text=(ev.get("content") or "")[:1000],
                    page_number=ev.get("page_number"),
                    field_name=param_name,
                    confidence=0.85,
                )
                return span.id
            # 降级：用召回的首个 chunk
            if recalled:
                first = recalled[0]
                span = await self._evidence.create_evidence_span(
                    session, source_file_id=source_file.id,
                    quote_text=(first.content or "")[:1000],
                    page_number=first.page_number,
                    field_name=param_name,
                    confidence=0.75,
                )
                return span.id
        except Exception as e:
            logger.warning(f"[Orchestrator] spec 证据 span 落库失败（不阻断）: {e}")
        return None

    # ============================================================
    # Fallback：单项对比失败时的兜底结果
    # ============================================================
    def _build_fallback_result(
        self, task: ComparisonTask, param: dict, err: Exception
    ) -> ComparisonResult:
        return ComparisonResult(
            task_id=task.id,
            param_name=(param.get("param_name") or "未命名参数").strip(),
            tender_value=self._to_text(param.get("tender_value")),
            spec_value=None,
            verdict=ComparisonVerdict.NEED_CONFIRM,
            confidence=0.3,
            reason=f"[对比失败兜底] {type(err).__name__}: {err}",
            tender_evidence=self._normalize_evidence(param.get("tender_evidence")),
            spec_evidence=None,
            evidence_span_id=None,
        )

    # ============================================================
    # 文本格式化辅助
    # ============================================================
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
    def _format_recall_chunks(chunks: List[DocumentChunk]) -> str:
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            page = f" 第{c.page_number}页" if c.page_number else ""
            content = (c.content or "").strip()
            if len(content) > _CHUNK_CONTENT_LIMIT:
                content = content[:_CHUNK_CONTENT_LIMIT] + "…"
            lines.append(f"[chunk_id={c.id}{page}]\n{content}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_recall_evidence(chunks: List[DocumentChunk]) -> str:
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            page = f" 第{c.page_number}页" if c.page_number else ""
            lines.append(f"- chunk_id={c.id}{page}: {(c.content or '')[:200]}")
        return "\n".join(lines)

    # ============================================================
    # 类型规整辅助
    # ============================================================
    @staticmethod
    def _normalize_verdict_key(s: str) -> str:
        s = (s or "").strip().lower()
        # 中文 → 英文 key
        zh_to_en = {
            "一致": "match", "偏离": "deviation", "缺失": "missing",
            "多余": "extra", "待确认": "need_confirm",
        }
        for zh, en in zh_to_en.items():
            if zh in s:
                return en
        return s

    @staticmethod
    def _to_text(v) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @staticmethod
    def _to_float(v) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_confidence(v) -> Optional[float]:
        f = ComparisonOrchestrator._to_float(v)
        if f is None:
            return None
        return max(0.0, min(1.0, f))

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
    def _summarize_stats(results: List[ComparisonResult]) -> dict:
        summary = {
            "total": len(results),
            "match": 0, "deviation": 0, "missing": 0, "extra": 0, "need_confirm": 0,
        }
        for r in results:
            key = r.verdict.value if isinstance(r.verdict, ComparisonVerdict) else str(r.verdict)
            if key in summary:
                summary[key] += 1
        return summary

    def _llm_model_name(self) -> str:
        """获取当前 LLM 模型名（用于证据链追溯）"""
        try:
            provider = self._llm._pick_provider()  # noqa: SLF001
            return provider.get("model") or "unknown"
        except Exception:
            return "unknown"


# ============================================================
# 单例
# ============================================================
_orchestrator: Optional[ComparisonOrchestrator] = None


def get_comparison_orchestrator() -> ComparisonOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ComparisonOrchestrator()
    return _orchestrator
