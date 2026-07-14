"""
AI 资产管理服务（v1.2 替代硬规则包）
- 审查要点清单（合同各维度审查 Prompt 模板）
- Prompt 模板库（比对/风险/助手各场景）
- 参数同义词典（RAG 召回辅助，最终判定仍由 LLM）
- 行业范本库（标准条款/标准参数表）

设计立场（见设计方案 §13）：
- 这些是"可在线编辑、版本化、专家修正回写"的知识资产，不是代码里的硬规则
- 所有"判断"仍由 LLM 完成，资产只提供"判断标准与上下文"
"""
from typing import Optional, List
from pydantic import BaseModel


class ReviewChecklist(BaseModel):
    """审查要点清单（合同风险扫描用，作为 Prompt 上下文，非硬规则）"""
    category: str                 # 付款/交付/违约/效期/资质/知识产权/管辖/保密...
    points: List[str]             # 审查要点描述（自然语言，交给 LLM 理解）
    severity_hint: str = "medium"  # 提示等级（非强制，LLM 综合判断）


class PromptTemplate(BaseModel):
    """Prompt 模板（版本化）"""
    scene: str                    # comparison / risk_review / assistant / bid_drafting
    version: str = "1.0"
    system_prompt: str
    user_prompt_template: str     # 含占位符 {tender} {spec} {evidence} 等
    is_active: bool = True


# 预置审查要点清单（作为知识库种子，可在线编辑演进）
DEFAULT_REVIEW_CHECKLIST: List[ReviewChecklist] = [
    ReviewChecklist(
        category="付款条款",
        points=[
            "付款方式是否与项目性质匹配（预付款比例是否过高）",
            "付款节点是否与交付/验收节点绑定",
            "是否有明确的付款时效与违约利息约定",
        ],
        severity_hint="high",
    ),
    ReviewChecklist(
        category="交付与验收",
        points=[
            "交付时间是否明确且可执行",
            "验收标准与验收周期是否清晰",
            "是否有拒收/退换货条款及期限",
        ],
        severity_hint="medium",
    ),
    ReviewChecklist(
        category="违约责任",
        points=[
            "违约责任是否对等（双方违约成本是否平衡）",
            "违约金比例是否合理（过高或过低）",
            "是否有免责/限责条款损害我方利益",
        ],
        severity_hint="high",
    ),
    ReviewChecklist(
        category="效期与终止",
        points=[
            "合同生效与终止条件是否明确",
            "是否有单方终止权及提前通知期限",
            "终止后的责任与结算条款是否清晰",
        ],
        severity_hint="medium",
    ),
    ReviewChecklist(
        category="资质与许可",
        points=[
            "合同双方资质要求是否明确（如施工资质、行业许可）",
            "是否有资质挂靠或借用资质的合规风险",
            "资质等级是否与项目规模匹配",
        ],
        severity_hint="high",
    ),
    ReviewChecklist(
        category="知识产权与保密",
        points=[
            "知识产权归属是否清晰（尤其定制开发场景）",
            "保密范围、期限、违约责任是否明确",
            "是否有竞业限制或排他性条款",
        ],
        severity_hint="medium",
    ),
    ReviewChecklist(
        category="管辖与争议解决",
        points=[
            "管辖法院或仲裁机构是否对我方有利",
            "适用法律是否明确",
        ],
        severity_hint="low",
    ),
]


class AIAssetService:
    """AI 资产管理（Phase 2 入库到知识库，Phase 1 先内存预置）"""

    def __init__(self):
        self._checklists = {c.category: c for c in DEFAULT_REVIEW_CHECKLIST}
        self._prompts: dict[str, PromptTemplate] = {}

    def get_checklist(self, category: Optional[str] = None) -> List[ReviewChecklist]:
        if category:
            return [self._checklists[category]] if category in self._checklists else []
        return list(self._checklists.values())

    def get_prompt(self, scene: str) -> Optional[PromptTemplate]:
        return self._prompts.get(scene)

    def register_prompt(self, tpl: PromptTemplate):
        """注册/更新 Prompt 模板（Phase 2 持久化到 DB + 版本管理）"""
        self._prompts[tpl.scene] = tpl


_ai_asset: Optional[AIAssetService] = None


def get_ai_asset_service() -> AIAssetService:
    global _ai_asset
    if _ai_asset is None:
        _ai_asset = AIAssetService()
    return _ai_asset
