"""★号废标风险识别服务（P2-11）

参考 lib-v0.2 的废标风险扫描设计：
1. T11.2 比对阶段对 is_disqualifying 条款缺失项生成专项"废标风险"
   - 从 tender_parse_service 解析出的 tech_spec 中筛 is_disqualifying=true 的条款
   - 对这些条款的比对结果（verdict != match）标记 is_disqualifying=true
2. T11.3 风险关键词扫描仅作确定性兜底
   - 当招标解析未识别出 is_disqualifying 字段时，用关键词扫描作为兜底
   - 关键词列表为可演进经验资产（TODO 存 ExpertMemory）

设计原则：
- AI-first：is_disqualifying 优先由 LLM 通过 tender_parse 输出
- 硬规则仅作兜底：关键词扫描只在 LLM 未输出 is_disqualifying 时启用
- 不阻断主流程：扫描失败不影响比对结果保存
"""
import re
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comparison import ComparisonResult, ComparisonTask, ComparisonVerdict
from app.models.document import Document

# 废标关键词（确定性兜底，仅当 LLM 未输出 is_disqualifying 时启用）
# TODO: 后续迁移到 ExpertMemory 作为可演进知识资产
_DISQUALIFYING_KEYWORDS = [
    "废标", "否决", "无效投标", "不予受理", "拒绝",
    "必须满足", "应当具备", "强制性", "实质性响应",
    "★", "※", "△",  # 招标文件常见强制性标记符号
]

# 招标解析结果中可能存放在 Document.metadata_json 的字段名
_TECH_SPEC_FIELD_CANDIDATES = ["tech_spec", "purchase_list", "qualification"]
_DISQUALIFYING_FIELD_CANDIDATES = ["is_disqualifying", "disqualifying", "is_dq"]


class DisqualifyingRiskService:
    """★号废标风险识别服务"""

    async def scan_and_mark(
        self, session: AsyncSession, task: ComparisonTask,
        results: List[ComparisonResult],
    ) -> int:
        """比对后扫描废标风险，标记 is_disqualifying 字段

        流程：
        1. 从 tender_doc.metadata_json 提取 tech_spec 列表（含 is_disqualifying 字段）
        2. 将 tech_spec 中的废标条款与比对结果按参数名匹配
        3. verdict != match 且对应废标条款 → 标记 is_disqualifying=True
        4. 兜底：用关键词扫描（仅当步骤 1-3 无法判定时）

        返回：被标记为废标风险的 ComparisonResult 数量
        """
        if not results:
            return 0

        try:
            # 1. 加载招标文档的解析结果
            tender_doc = await session.get(Document, task.tender_doc_id) if task.tender_doc_id else None
            tech_specs = self._extract_tech_specs(tender_doc) if tender_doc else []

            # 2. 构建"参数名 → is_disqualifying"映射
            disqualifying_param_map = self._build_disqualifying_map(tech_specs)

            marked_count = 0
            for cr in results:
                # 优先用解析结果判定
                is_dq = self._match_disqualifying(cr.param_name, disqualifying_param_map)
                # 兜底：关键词扫描
                if is_dq is None:
                    is_dq = self._keyword_scan(cr.param_name, cr.tender_value, cr.reason)
                # 仅当 verdict != match 时才标记为废标风险
                if is_dq and cr.verdict != ComparisonVerdict.MATCH:
                    cr.is_disqualifying = True
                    marked_count += 1
                    logger.info(
                        f"[DisqualifyingRisk] 标记废标风险: param={cr.param_name} verdict={cr.verdict.value}"
                    )
                else:
                    cr.is_disqualifying = False

            await session.flush()
            return marked_count
        except Exception as e:
            logger.warning(f"[DisqualifyingRisk] 扫描失败（不阻断）: {e}")
            return 0

    # ============================================================
    # 解析结果提取
    # ============================================================
    @staticmethod
    def _extract_tech_specs(tender_doc: Optional[Document]) -> List[dict]:
        """从 tender_doc.metadata_json 中提取 tech_spec / purchase_list / qualification

        tender_parse_service 将解析结果存放在 Document.metadata_json，
        其中 PART_B 解析结果包含 tech_spec 字段。
        """
        if not tender_doc or not tender_doc.metadata_json:
            return []
        meta = tender_doc.metadata_json
        if not isinstance(meta, dict):
            return []

        # 兼容两种存储方式：
        # 1. 直接 {tech_spec: [...], purchase_list: [...], qualification: [...]}
        # 2. 嵌套 {parse_result: {tech_spec: [...]}, ...}
        parse_result = meta.get("parse_result") or meta.get("tender_parse") or {}
        if not isinstance(parse_result, dict):
            parse_result = {}

        specs: List[dict] = []
        for field in _TECH_SPEC_FIELD_CANDIDATES:
            # 优先从 parse_result 取，再从顶层 meta 取
            value = parse_result.get(field) or meta.get(field)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        specs.append(item)
        return specs

    @staticmethod
    def _build_disqualifying_map(tech_specs: List[dict]) -> Dict[str, bool]:
        """构建参数名 → is_disqualifying 映射"""
        result: Dict[str, bool] = {}
        for spec in tech_specs:
            is_dq = None
            for field in _DISQUALIFYING_FIELD_CANDIDATES:
                if field in spec:
                    val = spec[field]
                    if isinstance(val, bool):
                        is_dq = val
                    elif isinstance(val, str):
                        is_dq = val.lower() in ("true", "1", "yes", "是")
                    if is_dq is not None:
                        break
            if is_dq is None:
                continue

            # 参数名候选字段
            for name_field in ("param", "name", "item", "title"):
                name = spec.get(name_field)
                if name and isinstance(name, str):
                    result[name.strip()] = is_dq
                    break
        return result

    # ============================================================
    # 匹配与兜底
    # ============================================================
    @staticmethod
    def _match_disqualifying(
        param_name: str, dq_map: Dict[str, bool]
    ) -> Optional[bool]:
        """参数名匹配废标映射

        返回：
        - True / False：明确判定
        - None：未匹配到，需走兜底
        """
        if not dq_map or not param_name:
            return None
        name = param_name.strip()
        # 精确匹配
        if name in dq_map:
            return dq_map[name]
        # 子串匹配（参数名包含或被包含）
        for k, v in dq_map.items():
            if k in name or name in k:
                return v
        return None

    @staticmethod
    def _keyword_scan(
        param_name: Optional[str],
        tender_value: Optional[str],
        reason: Optional[str],
    ) -> bool:
        """关键词扫描兜底（仅当 LLM 未输出 is_disqualifying 时启用）

        检查参数名 / 招标值 / 理由中是否包含废标关键词
        """
        for text in (param_name, tender_value, reason):
            if not text:
                continue
            for keyword in _DISQUALIFYING_KEYWORDS:
                if keyword in text:
                    return True
        return False


# ============================================================
# 单例
# ============================================================
_service: Optional[DisqualifyingRiskService] = None


def get_disqualifying_risk_service() -> DisqualifyingRiskService:
    global _service
    if _service is None:
        _service = DisqualifyingRiskService()
    return _service
