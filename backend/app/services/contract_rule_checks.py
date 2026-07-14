"""合同多维风险扫描：确定性规则检查器

参考 lib-v0.2 contract_risk_service.py 的风险检查思路，适配当前项目 Contract 模型。

7 类检查：
1. check_field_completeness       字段完整性
2. check_attachment_completeness  附件完整性
3. check_amount_consistency       金额一致性（line_total vs contract.amount，容差 2% 或 100 元）
4. check_schedule_risks            履约提醒（质保过期/即将到期、付款节点逾期/即将到期 7 天内）
5. check_duplicate_contract        重复合同（合同编号相同 or 项目+客户+金额完全一致）
6. check_ocr_consistency_data     OCR 一致性数据准备（LLM 语义判定在 contract_review_service 中完成）

设计原则：
- 金额一致性、重复合同、履约提醒属于确定性检查（硬规则）
- OCR 一致性需要 LLM 语义判定（在 contract_review_service 中调用 LLM）
- 风险关键词扫描仅作确定性兜底

注意：当前项目 Contract 模型实际字段为
  title / counterparty / amount / sign_date / effective_date / expire_date /
  project_id / document_id / metadata_json / is_deleted
合同编号、甲方、附件清单、明细行、质保期、付款节点等扩展字段
统一存储在 metadata_json 中（参考 lib-v0.2 字段约定）。
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractRisk, RiskLevel

# ============================================================
# 容差与阈值配置
# ============================================================
_AMOUNT_TOLERANCE_PCT = 0.02  # 2% 容差
_AMOUNT_TOLERANCE_ABS = 100.0  # 或 100 元绝对容差（取较大者）
_SCHEDULE_WARNING_DAYS = 7  # 7 天内到期预警


# ============================================================
# 字段访问辅助：从 metadata_json 读取扩展字段
# ============================================================

def _get_metadata(contract: Contract) -> dict:
    """安全获取 metadata_json（永不为 None）"""
    return contract.metadata_json or {}


def _get_contract_no(contract: Contract) -> Optional[str]:
    """合同编号：存于 metadata_json.contract_no"""
    return _get_metadata(contract).get("contract_no")


def _get_party_a(contract: Contract) -> Optional[str]:
    """甲方：存于 metadata_json.party_a"""
    return _get_metadata(contract).get("party_a")


def _get_party_b(contract: Contract) -> Optional[str]:
    """乙方：优先使用 counterparty 字段，回退 metadata_json.party_b"""
    return contract.counterparty or _get_metadata(contract).get("party_b")


def _get_attachments(contract: Contract) -> List[Any]:
    """附件清单：metadata_json.attachments 或 attachment_keys"""
    meta = _get_metadata(contract)
    return meta.get("attachments") or meta.get("attachment_keys") or []


def _build_risk(
    rule_code: str,
    category: str,
    level: RiskLevel,
    title: str,
    description: str,
    suggestion: Optional[str] = None,
    confidence: float = 1.0,
    **extra,
) -> dict:
    """构造统一格式的风险 dict。

    输出结构兼容 contract_review_service._persist_risks 期望的字段
    （rule_code / rule_source / category / level / title / description /
       suggestion / confidence / evidence），同时保留 risk_type / risk_level
    作为 task spec 的兼容字段。
    """
    risk: Dict[str, Any] = {
        "rule_code": rule_code,
        "rule_source": "rule_engine",
        "category": category,
        "level": level,
        "title": title,
        "description": description,
        "suggestion": suggestion,
        "confidence": confidence,
        "evidence": [],
        # task spec 兼容字段
        "risk_type": rule_code.lower(),
        "risk_level": level,
    }
    if extra:
        risk["metadata"] = extra
    return risk


def _parse_date(value: Any) -> Optional[date]:
    """将多种格式的日期值归一化为 date"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            return None
    return None


# ============================================================
# 1. 字段完整性
# ============================================================

def check_field_completeness(contract: Contract) -> List[dict]:
    """1. 字段完整性风险检查

    检查合同必要字段是否完整：
    - 模型字段：合同名称（title）、乙方（counterparty）、签订/生效/到期日期、合同金额（amount）
    - metadata_json 扩展字段：合同编号（contract_no）、甲方（party_a）
    """
    risks: List[dict] = []

    # 模型实际字段
    model_fields = [
        ("title", "合同名称"),
        ("counterparty", "乙方"),
        ("sign_date", "签订日期"),
        ("effective_date", "生效日期"),
        ("expire_date", "到期日期"),
        ("amount", "合同金额"),
    ]
    for field, label in model_fields:
        value = getattr(contract, field, None)
        if value is None or value == "":
            risks.append(_build_risk(
                rule_code=f"FIELD_INCOMPLETE_{field}",
                category="字段完整性",
                level=RiskLevel.MEDIUM,
                title=f"缺少必要字段：{label}",
                description=f"合同缺少必要字段：{label}（{field}）",
                suggestion=f"建议补充 {label} 信息",
                field_name=field,
            ))

    # metadata_json 扩展字段
    meta = _get_metadata(contract)
    meta_fields = [
        ("contract_no", "合同编号"),
        ("party_a", "甲方"),
    ]
    for field, label in meta_fields:
        value = meta.get(field)
        if value is None or value == "":
            risks.append(_build_risk(
                rule_code=f"FIELD_INCOMPLETE_{field}",
                category="字段完整性",
                level=RiskLevel.MEDIUM,
                title=f"缺少必要字段：{label}",
                description=f"合同缺少必要字段：{label}（metadata_json.{field}）",
                suggestion=f"建议补充 {label} 信息",
                field_name=field,
            ))

    return risks


# ============================================================
# 2. 附件完整性
# ============================================================

def check_attachment_completeness(
    session_db: Optional[AsyncSession], contract: Contract
) -> List[dict]:
    """2. 附件完整性风险检查

    基于 metadata_json.attachments / attachment_keys 检查附件清单是否为空。
    若需更深度的附件存在性校验（查询 Document 表），请在 async 上下文中扩展。
    """
    risks: List[dict] = []
    attachments = _get_attachments(contract)
    if not attachments:
        risks.append(_build_risk(
            rule_code="ATTACHMENT_MISSING",
            category="附件完整性",
            level=RiskLevel.LOW,
            title="合同未关联附件文档",
            description="合同未关联任何附件文档（metadata_json.attachments 为空）",
            suggestion="建议上传并关联合同扫描件、附件等文档",
        ))
    return risks


# ============================================================
# 3. 金额一致性
# ============================================================

def check_amount_consistency(contract: Contract) -> List[dict]:
    """3. 金额一致性风险检查

    检查明细行金额之和与合同总金额（contract.amount）是否一致。
    容差：max(amount * 2%, 100 元)。
    明细行来源：metadata_json.line_items / items，每项支持 amount / total / subtotal 字段。
    """
    risks: List[dict] = []
    if contract.amount is None:
        return risks

    meta = _get_metadata(contract)
    line_items = meta.get("line_items") or meta.get("items") or []
    if not line_items:
        return risks

    try:
        line_total = sum(
            float(
                item.get("amount", 0)
                or item.get("total", 0)
                or item.get("subtotal", 0)
                or 0
            )
            for item in line_items
            if isinstance(item, dict)
        )
        contract_total = float(contract.amount)
    except (TypeError, ValueError):
        return risks

    if line_total == 0:
        return risks

    diff = abs(line_total - contract_total)
    tolerance = max(contract_total * _AMOUNT_TOLERANCE_PCT, _AMOUNT_TOLERANCE_ABS)

    if diff > tolerance:
        risks.append(_build_risk(
            rule_code="AMOUNT_MISMATCH",
            category="金额一致性",
            level=RiskLevel.HIGH,
            title="明细金额与合同总金额不一致",
            description=(
                f"明细金额之和 {line_total:.2f} 与合同总金额 {contract_total:.2f} "
                f"差异 {diff:.2f} 超过容差 {tolerance:.2f}"
            ),
            suggestion="建议核对明细行金额与合同总金额，确认是否存在录入错误或漏项",
            line_total=line_total,
            contract_total=contract_total,
            diff=diff,
            tolerance=tolerance,
        ))

    return risks


# ============================================================
# 4. 履约提醒（质保期 / 付款节点）
# ============================================================

def check_schedule_risks(
    contract: Contract, today: Optional[date] = None
) -> List[dict]:
    """4. 履约提醒风险检查

    检查（基于 metadata_json）：
    - 质保期（warranty_expire_date）是否过期或即将到期（7 天内）
    - 付款节点（payment_schedule[*].due_date）是否逾期或即将到期（7 天内）
    """
    risks: List[dict] = []
    if today is None:
        today = date.today()

    meta = _get_metadata(contract)

    # 4.1 质保期检查
    warranty_expire = meta.get("warranty_expire_date")
    w_date = _parse_date(warranty_expire)
    if w_date is not None:
        days_left = (w_date - today).days
        if days_left < 0:
            risks.append(_build_risk(
                rule_code="WARRANTY_EXPIRED",
                category="履约提醒",
                level=RiskLevel.MEDIUM,
                title="质保期已过期",
                description=f"质保期已于 {w_date} 过期（已过期 {abs(days_left)} 天）",
                suggestion="确认是否需要续保或重新签订质保协议",
                expire_date=str(w_date),
                days_overdue=abs(days_left),
            ))
        elif days_left <= _SCHEDULE_WARNING_DAYS:
            risks.append(_build_risk(
                rule_code="WARRANTY_EXPIRING",
                category="履约提醒",
                level=RiskLevel.LOW,
                title="质保期即将到期",
                description=f"质保期将于 {w_date} 到期（剩余 {days_left} 天）",
                suggestion="建议尽快安排质保续期或验收",
                expire_date=str(w_date),
                days_left=days_left,
            ))

    # 4.2 付款节点检查
    payment_schedule = meta.get("payment_schedule") or []
    if isinstance(payment_schedule, list):
        for i, payment in enumerate(payment_schedule):
            if not isinstance(payment, dict):
                continue
            pay_date_raw = payment.get("due_date") or payment.get("date")
            p_date = _parse_date(pay_date_raw)
            if p_date is None:
                continue
            days_left = (p_date - today).days
            amount = payment.get("amount", 0)
            milestone = payment.get("milestone") or payment.get("title") or f"付款节点 {i + 1}"
            is_paid = bool(payment.get("paid", False))

            if days_left < 0 and not is_paid:
                risks.append(_build_risk(
                    rule_code="PAYMENT_OVERDUE",
                    category="履约提醒",
                    level=RiskLevel.HIGH,
                    title=f"付款节点逾期：{milestone}",
                    description=(
                        f"付款节点 '{milestone}' 已逾期"
                        f"（金额 {amount}，逾期 {abs(days_left)} 天）"
                    ),
                    suggestion="建议尽快安排付款或与对方协商延期",
                    due_date=str(p_date),
                    days_overdue=abs(days_left),
                    amount=amount,
                    milestone=milestone,
                ))
            elif 0 <= days_left <= _SCHEDULE_WARNING_DAYS and not is_paid:
                risks.append(_build_risk(
                    rule_code="PAYMENT_EXPIRING",
                    category="履约提醒",
                    level=RiskLevel.MEDIUM,
                    title=f"付款节点即将到期：{milestone}",
                    description=(
                        f"付款节点 '{milestone}' 即将到期"
                        f"（金额 {amount}，剩余 {days_left} 天）"
                    ),
                    suggestion="建议提前准备付款流程",
                    due_date=str(p_date),
                    days_left=days_left,
                    amount=amount,
                    milestone=milestone,
                ))

    return risks


# ============================================================
# 5. 重复合同（异步，需查库）
# ============================================================

async def check_duplicate_contract(
    session: AsyncSession, contract: Contract
) -> List[dict]:
    """5. 重复合同风险检查

    检查是否存在重复合同：
    - 合同编号相同（metadata_json.contract_no）
    - 或 项目 + 客户（counterparty）+ 金额 完全一致
    """
    risks: List[dict] = []
    if contract.id is None:
        return risks

    # 5.1 按合同编号查重
    contract_no = _get_contract_no(contract)
    if contract_no:
        stmt = select(Contract).where(
            and_(
                Contract.id != contract.id,
                Contract.is_deleted.is_(False),
            )
        )
        result = await session.execute(stmt)
        all_contracts = result.scalars().all()
        # contract_no 存于 metadata_json，需在 Python 层过滤
        duplicates_no = [
            c for c in all_contracts
            if _get_contract_no(c) == contract_no
        ]
        if duplicates_no:
            risks.append(_build_risk(
                rule_code="DUPLICATE_CONTRACT_NO",
                category="重复合同",
                level=RiskLevel.HIGH,
                title=f"存在相同合同编号的合同：{contract_no}",
                description=(
                    f"存在 {len(duplicates_no)} 个相同合同编号的合同：{contract_no}"
                ),
                suggestion="建议核查是否为重复录入，合并或废止重复合同",
                duplicate_count=len(duplicates_no),
                duplicate_ids=[str(d.id) for d in duplicates_no],
            ))

    # 5.2 按项目 + 客户 + 金额查重
    if contract.counterparty and contract.amount is not None:
        stmt = select(Contract).where(
            and_(
                Contract.counterparty == contract.counterparty,
                Contract.amount == contract.amount,
                Contract.id != contract.id,
                Contract.is_deleted.is_(False),
            )
        )
        if contract.project_id is not None:
            stmt = stmt.where(Contract.project_id == contract.project_id)
        result = await session.execute(stmt)
        duplicates_content = result.scalars().all()
        if duplicates_content:
            risks.append(_build_risk(
                rule_code="DUPLICATE_CONTRACT_CONTENT",
                category="重复合同",
                level=RiskLevel.MEDIUM,
                title="存在相同（客户+金额）的合同",
                description=(
                    f"存在 {len(duplicates_content)} 个相同（客户+金额）的合同："
                    f"客户={contract.counterparty}，金额={contract.amount}"
                ),
                suggestion="建议核查是否为重复签订，确认合同效力",
                duplicate_count=len(duplicates_content),
                duplicate_ids=[str(d.id) for d in duplicates_content],
            ))

    return risks


# ============================================================
# 6. OCR 一致性数据准备（不在此处判定，交 LLM 语义判定）
# ============================================================

def check_ocr_consistency_data(contract: Contract) -> Optional[dict]:
    """6. OCR 一致性数据准备

    准备 OCR 提取的字段与合同记录字段的对比数据。
    OCR 提取字段来源：metadata_json.ocr_extracted_fields。

    实际的语义等价判定（如"OCR 合同编号 HT-001" 是否与原文段 "合同编号：HT001" 语义等价）
    在 contract_review_service 中用 LLM 完成；本函数只准备对比数据，
    并对"完全字符串相等"做精确匹配预判，以减少 LLM 调用。
    """
    meta = _get_metadata(contract)
    ocr_fields = meta.get("ocr_extracted_fields") or {}
    if not ocr_fields:
        return None

    # 字段映射：ocr_key -> (合同字段取值函数, 中文标签)
    field_mapping = [
        ("contract_no", _get_contract_no, "合同编号"),
        ("party_a", _get_party_a, "甲方"),
        ("party_b", _get_party_b, "乙方"),
        ("amount", lambda c: c.amount, "合同金额"),
    ]

    comparisons = []
    for ocr_key, getter, label in field_mapping:
        ocr_value = ocr_fields.get(ocr_key)
        contract_value = getter(contract)
        if ocr_value is None or contract_value is None or contract_value == "":
            continue
        comparisons.append({
            "field": ocr_key,
            "label": label,
            "ocr_value": str(ocr_value),
            "contract_value": str(contract_value),
            "exact_match": str(ocr_value).strip() == str(contract_value).strip(),
        })

    if not comparisons:
        return None

    return {
        "risk_type": "ocr_consistency_check",
        "comparisons": comparisons,
        "needs_llm_check": any(not c["exact_match"] for c in comparisons),
    }


# ============================================================
# 聚合入口
# ============================================================

def check_all_sync(
    contract: Contract, today: Optional[date] = None
) -> List[dict]:
    """执行所有同步风险检查（1 / 2 / 3 / 4）

    异步检查（5. 重复合同、6. OCR 一致性数据准备）需要单独调用。
    """
    risks: List[dict] = []
    risks.extend(check_field_completeness(contract))
    risks.extend(check_attachment_completeness(None, contract))
    risks.extend(check_amount_consistency(contract))
    risks.extend(check_schedule_risks(contract, today))
    return risks


async def check_all_async(
    session: AsyncSession, contract: Contract, today: Optional[date] = None
) -> List[dict]:
    """执行所有风险检查（含异步：5. 重复合同）

    OCR 一致性（6）不在此聚合，因其需要 LLM 判定，由 contract_review_service 调用。
    """
    risks = check_all_sync(contract, today)
    risks.extend(await check_duplicate_contract(session, contract))
    return risks
