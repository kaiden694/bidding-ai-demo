"""
合同风险扫描服务（T4，Phase 1 MVP）

设计立场（v1.2 §13 "AI 优先，避免硬规则"）：
- ❌ 禁止 YAML 规则包、禁止 "if 关键词 in 文本 then 报风险" 的硬规则
- ✅ LLM 全文语义分析：风险识别/等级/修改建议/证据链均由 LLM 产出
- ✅ 审查要点清单（来自 ai_asset_service）作为 Prompt 上下文，非硬规则
- ✅ RAG 召回历史合同案例作为参考
- ✅ 仅对"日期过期、必备条款存在性"做轻量确定性校验
      —— 这是事实性/结构性检查（合同是否过期、是否缺少必备条款），
         不涉及条款内容的风险判定，内容风险判定仍由 LLM 完成
"""
import json
import logging
import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.rag.retriever import get_rag_retriever
from app.models.contract import Contract, ContractRisk, ReviewStatus, RiskLevel
from app.models.document import DocumentChunk
from app.models.feedback import FeedbackTargetType
from app.services.ai_asset_service import get_ai_asset_service
from app.services.feedback_service import get_feedback_service

logger = logging.getLogger(__name__)


# ============================================================
# 轻量确定性校验（仅事实性/结构性，不涉及条款内容风险判定）
# ============================================================

# 必备条款清单：仅用于"是否存在"的结构性检查；
# 当某条款在全文中缺失时，仅报告"缺少必备条款"这一结构性缺陷，
# 条款内容是否有风险仍由 LLM 判定。
REQUIRED_CLAUSES: List[dict] = [
    {"name": "付款条款", "keywords": ["付款", "支付", "价款", "合同价款"]},
    {"name": "交付与验收", "keywords": ["交付", "交货", "验收"]},
    {"name": "违约责任", "keywords": ["违约责任", "违约金", "违约"]},
    {"name": "争议解决与管辖", "keywords": ["争议解决", "管辖", "仲裁", "诉讼"]},
    {"name": "合同效期", "keywords": ["生效", "终止", "有效期", "期限"]},
]


def is_date_expired(date_value) -> bool:
    """检查日期是否过期（基于合同实际日期字段，非文本提取）

    属于事实性校验：合同到期日是否早于当前日期。
    """
    if date_value is None:
        return False
    if isinstance(date_value, str):
        try:
            date_value = date.fromisoformat(date_value[:10])
        except (ValueError, TypeError):
            return False
    if isinstance(date_value, datetime):
        date_value = date_value.date()
    if not isinstance(date_value, date):
        return False
    return date_value < date.today()


def check_required_clause_exists(text: str, clause_keywords: List[str]) -> bool:
    """检查必备条款是否存在（结构性存在性检查，非风险判定）

    仅判断文本中是否出现条款标题/章节（如"违约责任"），不判断条款内容风险。
    条款内容的风险判定仍由 LLM 完成。
    """
    if not text or not clause_keywords:
        return False
    return any(kw in text for kw in clause_keywords)


# ============================================================
# LLM Prompt
# ============================================================

SYSTEM_PROMPT = (
    "你是合同法务审查专家，对合同全文进行语义分析，"
    "识别付款/交付/违约/效期/资质/知识产权/管辖/保密等维度的风险。"
    "必须引用原文条款作为证据。禁止仅靠关键词命中。"
    "请基于条款的实际语义判断风险，给出具体、可执行的修改建议。"
)

USER_PROMPT_TEMPLATE = """请对以下合同进行全文语义风险审查。

【审查要点清单】（作为审查视角的参考，需结合实际条款语义判断，非硬规则匹配）：
{checklist}

【历史合同案例参考】（RAG 召回，仅供对比参考，非强制依据）：
{cases}

【专家历史修正案例】（参考其判定倾向，不照搬，仍需基于当前条款语义独立判断）：
{feedback}

【合同正文切块】（每块标注 chunk_id 与页码，便于证据引用）：
{chunks}

请按以下 JSON 结构输出风险点（仅输出 JSON，不要额外文字）：
{{
  "risks": [
    {{
      "category": "付款条款|交付与验收|违约责任|效期与终止|知识产权与保密|管辖与争议解决|资质|其他",
      "level": "high|medium|low|info",
      "title": "风险标题（简短一句话）",
      "description": "风险描述（基于原文语义，说明为什么是风险）",
      "suggestion": "修改建议（具体可执行的条款修改方向）",
      "confidence": 0.0到1.0之间的置信度,
      "evidence": [
        {{
          "chunk_id": "引用的切块ID",
          "content": "原文片段（直接引用，便于定位）",
          "page_number": 页码
        }}
      ]
    }}
  ]
}}

要求：
1. 仅报告有实际语义风险的问题，不要凑数
2. 每条风险必须附至少一条 evidence（引用真实存在的 chunk_id）
3. level 严格按 high/medium/low/info 取值
4. 置信度 confidence 反映你对风险判断的把握
5. 如果合同无明显风险，返回 {{"risks": []}}
"""


class ContractReviewService:
    """合同风险扫描服务（AI 主导）"""

    # 单次审查最大切块数（控制 token）
    MAX_CHUNKS = 40
    # 历史案例召回数
    CASE_TOP_K = 3
    # 历史专家修正召回数（few-shot）
    FEEDBACK_TOP_K = 3
    # 单块正文截断长度
    CHUNK_CONTENT_LIMIT = 800

    def __init__(self):
        self._llm = get_llm_client()
        self._rag = get_rag_retriever()
        self._asset = get_ai_asset_service()
        self._feedback = get_feedback_service()

    async def review(
        self,
        session: AsyncSession,
        contract: Contract,
    ) -> List[ContractRisk]:
        """主流程：
        1. 获取合同正文切块（通过 contract.document_id）
        2. 从 ai_asset_service 获取审查要点清单（6 大维度）
        3. RAG 召回历史合同案例作为参考
        4. 召回相似历史专家修正作为 few-shot（T5.3）
        5. LLM Prompt：全文语义分析，输出结构化风险 JSON（含证据链）
        6. 轻量确定性校验：日期过期、必备条款存在性
        7. 写入 ContractRisk
        """
        # 1. 获取合同正文切块
        chunks = await self._load_contract_chunks(session, contract)

        llm_risks: List[dict] = []
        if not chunks:
            logger.warning("合同 %s 无正文切块，跳过 LLM 语义分析", contract.id)
        else:
            # 2. 获取审查要点清单（6 大维度）
            checklist = self._asset.get_checklist()
            # 3. RAG 召回历史合同案例
            cases = await self._retrieve_history_cases(session, contract, chunks)
            # 4. 召回相似历史专家修正（few-shot）
            feedback_examples = await self._recall_feedback_examples(
                session, contract, chunks
            )
            # 5. LLM 全文语义分析
            llm_risks = await self._analyze_with_llm(
                contract, chunks, checklist, cases, feedback_examples
            )

        # 6. 轻量确定性校验（日期过期 / 必备条款缺失，仅事实/结构性）
        deterministic_risks = self._deterministic_checks(contract, chunks)

        # 7. 合并 + 写入 ContractRisk
        merged = self._merge_risks(llm_risks, deterministic_risks)
        risk_models = await self._persist_risks(session, contract, merged)

        # 更新合同审查状态
        contract.review_status = ReviewStatus.REVIEWING
        await session.commit()
        return risk_models

    # ------------------------------------------------------------------
    # 反馈召回（T5.3：few-shot 注入）
    # ------------------------------------------------------------------
    async def _recall_feedback_examples(
        self,
        session: AsyncSession,
        contract: Contract,
        chunks: List[DocumentChunk],
    ) -> List[dict]:
        """召回与本次合同审查上下文相似的历史专家修正

        - 用合同标题 + 首批切块内容作为查询文本
        - 召回失败不阻断主流程
        """
        query_parts = []
        if contract.title:
            query_parts.append(contract.title[:120])
        if chunks:
            query_parts.append((chunks[0].content or "")[:200])
        query_text = "\n".join(p for p in query_parts if p)
        if not query_text.strip():
            return []
        try:
            records = await self._feedback.recall_similar_feedback(
                session,
                target_type=FeedbackTargetType.CONTRACT,
                query_text=query_text,
                top_k=self.FEEDBACK_TOP_K,
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

    # -------- 切块加载 --------

    async def _load_contract_chunks(
        self, session: AsyncSession, contract: Contract
    ) -> List[DocumentChunk]:
        if not contract.document_id:
            return []
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == contract.document_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(self.MAX_CHUNKS)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # -------- RAG 历史案例召回 --------

    async def _retrieve_history_cases(
        self, session: AsyncSession, contract: Contract, chunks: List[DocumentChunk]
    ) -> List[dict]:
        """RAG 召回历史合同案例作为参考"""
        query = contract.title or "合同风险审查"
        if chunks:
            query = (chunks[0].content or query)[:120]
        try:
            return await self._rag.search_knowledge(
                session, query, category="合同", top_k=self.CASE_TOP_K
            )
        except Exception as e:
            logger.warning("RAG 召回历史合同案例失败: %s", e)
            return []

    # -------- LLM 全文语义分析 --------

    async def _analyze_with_llm(
        self,
        contract: Contract,
        chunks: List[DocumentChunk],
        checklist,
        cases: List[dict],
        feedback_examples: List[dict],
    ) -> List[dict]:
        checklist_text = self._format_checklist(checklist)
        cases_text = self._format_cases(cases)
        chunks_text = self._format_chunks(chunks)
        feedback_text = self._format_feedback_examples(feedback_examples)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            checklist=checklist_text,
            cases=cases_text or "（无历史案例召回）",
            feedback=feedback_text or "（无专家历史修正召回）",
            chunks=chunks_text,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = await self._llm.chat(messages, temperature=0.2, max_tokens=4096)
            return self._parse_risks_json(raw)
        except Exception as e:
            logger.error("LLM 合同风险分析失败: %s", e)
            return []

    @staticmethod
    def _format_feedback_examples(examples: List[dict]) -> str:
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
                f"[案例{i}] 条款/风险维度：{ctx_key}\n"
                f"  上下文：{ctx_text}\n"
                f"  原判定：{original} → 修正为：{corrected}\n"
                f"  修正理由：{reason}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _format_checklist(checklist) -> str:
        if not checklist:
            return "（未配置审查要点清单）"
        lines = []
        for c in checklist:
            points = "\n".join(f"  - {p}" for p in c.points)
            lines.append(f"[{c.category}]（建议关注等级：{c.severity_hint}）\n{points}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_cases(cases: List[dict]) -> str:
        if not cases:
            return ""
        lines = []
        for i, c in enumerate(cases, 1):
            title = c.get("title") or c.get("section") or "历史案例"
            content = (c.get("content") or "")[:300]
            lines.append(f"[案例{i}] {title}\n{content}")
        return "\n\n".join(lines)

    @classmethod
    def _format_chunks(cls, chunks: List[DocumentChunk]) -> str:
        lines = []
        for c in chunks:
            content = (c.content or "")[:cls.CHUNK_CONTENT_LIMIT]
            page = c.page_number if c.page_number is not None else "-"
            lines.append(f"[chunk_id={c.id} | 页码={page}]\n{content}")
        return "\n\n".join(lines)

    @staticmethod
    def _parse_risks_json(raw: str) -> List[dict]:
        """解析 LLM 输出的风险 JSON（容错处理 markdown 包裹）"""
        if not raw:
            return []
        text = raw.strip()
        # 去掉 markdown 代码块包裹
        if text.startswith("```"):
            lines = text.split("\n")
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 { ... } 片段
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning("LLM 风险 JSON 解析失败: %s", text[:200])
                    return []
            else:
                logger.warning("LLM 风险 JSON 解析失败: %s", text[:200])
                return []
        risks = data.get("risks") if isinstance(data, dict) else None
        if not isinstance(risks, list):
            return []
        return [r for r in risks if isinstance(r, dict)]

    # -------- 轻量确定性校验（事实/结构性） --------

    def _deterministic_checks(
        self, contract: Contract, chunks: List[DocumentChunk]
    ) -> List[dict]:
        """轻量确定性校验：日期过期 / 必备条款缺失

        仅事实性/结构性检查，不涉及条款内容风险判定（内容风险由 LLM）。
        """
        risks: List[dict] = []
        today_str = date.today().isoformat()

        # 1. 日期过期检查（基于合同实际日期字段，非文本提取）
        if is_date_expired(contract.expire_date):
            risks.append({
                "category": "效期与终止",
                "level": "high",
                "title": "合同已过期",
                "description": (
                    f"合同到期日 {contract.expire_date} 早于当前日期 {today_str}，"
                    "合同已失效。"
                ),
                "suggestion": "确认是否需要续签或重新签订合同。",
                "confidence": 1.0,
                "evidence": [],
                "rule_source": "deterministic",
                "rule_code": "DATE_EXPIRED",
            })

        # 2. 必备条款存在性检查（仅检查"是否存在"，不判断内容风险）
        full_text = "\n".join((c.content or "") for c in chunks)
        for clause in REQUIRED_CLAUSES:
            if not check_required_clause_exists(full_text, clause["keywords"]):
                risks.append({
                    "category": clause["name"],
                    "level": "medium",
                    "title": f"缺少必备条款：{clause['name']}",
                    "description": (
                        f"合同全文未识别到 {clause['name']} 相关条款，"
                        "可能存在结构性缺失。"
                    ),
                    "suggestion": f"建议补充 {clause['name']} 相关条款，明确双方权责。",
                    "confidence": 0.7,
                    "evidence": [],
                    "rule_source": "deterministic",
                    "rule_code": f"MISSING_CLAUSE_{clause['name']}",
                })

        return risks

    # -------- 合并与持久化 --------

    def _merge_risks(
        self, llm_risks: List[dict], deterministic_risks: List[dict]
    ) -> List[dict]:
        merged: List[dict] = []
        for r in llm_risks:
            r.setdefault("rule_source", "llm")
            r.setdefault("rule_code", None)
            merged.append(r)
        merged.extend(deterministic_risks)
        return merged

    async def _persist_risks(
        self, session: AsyncSession, contract: Contract, risks: List[dict]
    ) -> List[ContractRisk]:
        """写入 ContractRisk（先清除该合同未确认的历史风险，再写入新风险）

        保留法务已确认（is_confirmed=True）的风险，避免重复扫描丢失人工结论。
        """
        # 清除未确认的历史风险（幂等：重新扫描替换 AI 结论）
        await session.execute(
            delete(ContractRisk).where(
                ContractRisk.contract_id == contract.id,
                ContractRisk.is_confirmed.is_(False),
            )
        )
        models: List[ContractRisk] = []
        for r in risks:
            level = self._normalize_level(r.get("level"))
            evidence = self._normalize_evidence(r.get("evidence"))
            model = ContractRisk(
                contract_id=contract.id,
                rule_code=r.get("rule_code"),
                rule_source=r.get("rule_source") or "llm",
                category=r.get("category"),
                level=level,
                title=r.get("title") or "未命名风险",
                description=r.get("description"),
                suggestion=r.get("suggestion"),
                confidence=self._normalize_confidence(r.get("confidence")),
                evidence=evidence,
                metadata_json={"source": r.get("rule_source") or "llm"},
            )
            session.add(model)
            models.append(model)
        # flush 以拿到主键，commit 在 review() 末尾执行
        await session.flush()
        return models

    # -------- 字段归一化 --------

    @staticmethod
    def _normalize_level(level) -> RiskLevel:
        if isinstance(level, RiskLevel):
            return level
        if isinstance(level, str):
            v = level.lower().strip()
            mapping = {
                "high": RiskLevel.HIGH,
                "medium": RiskLevel.MEDIUM,
                "low": RiskLevel.LOW,
                "info": RiskLevel.INFO,
            }
            if v in mapping:
                return mapping[v]
        return RiskLevel.MEDIUM

    @staticmethod
    def _normalize_confidence(c) -> Optional[float]:
        if c is None:
            return None
        try:
            v = float(c)
        except (TypeError, ValueError):
            return None
        if v < 0:
            return 0.0
        if v > 1:
            return 1.0
        return v

    @staticmethod
    def _normalize_evidence(evidence) -> Optional[list]:
        if not isinstance(evidence, list):
            return None
        out = []
        for e in evidence:
            if not isinstance(e, dict):
                continue
            out.append({
                "chunk_id": e.get("chunk_id"),
                "content": e.get("content"),
                "page_number": e.get("page_number"),
            })
        return out or None


_service: Optional[ContractReviewService] = None


def get_contract_review_service() -> ContractReviewService:
    global _service
    if _service is None:
        _service = ContractReviewService()
    return _service
