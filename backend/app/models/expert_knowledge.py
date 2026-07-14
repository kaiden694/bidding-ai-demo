"""专家知识资产模型（P3-14 多租户 scope）

设计要点：
- ExpertRule：可演化的专家经验资产（prompt 模板 / 校准规则 / 关键词字典 / 结构范例等）
  - scope: global / tenant / org 三级可见范围
  - tenant_id / org_id：多租户隔离（与现有 TenantMixin 一致）
- 同一 key 在同一 (scope, tenant_id, org_id) 三元组内唯一

参考 lib-v0.2 expert_rule_service.py：
- _scoped_id: tenant_id+org_id+raw_id 指纹后取后 12 位（用于跨租户去重）
- _apply_scope: 联合过滤（global 可见 + tenant 内 + org 内）
- _apply_owned_scope: 仅返回当前租户自有数据
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import String, Text, Boolean, Enum, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin


class ExpertScope(str, enum.Enum):
    """专家知识可见范围"""
    GLOBAL = "global"     # 全局可见（所有租户）
    TENANT = "tenant"     # 租户内可见
    ORG = "org"           # 组织内可见


class ExpertRule(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """专家知识规则（可演化的经验资产，AI-first 原则）

    用途示例：
    - calibration_threshold: 校准相似度阈值（key=calibration_threshold, value={"threshold": 0.90}）
    - prompt_template: LLM prompt 模板（key=tender_parse_part_b, value={"prompt": "..."}）
    - keyword_dict: 关键词字典（key=disqualifying_keywords, value={"keywords": ["废标", ...]}）
    - structure_example: 结构识别范例（key=table_recognition, value={"examples": [...]}）
    - rrf_params: RRF 检索参数（key=rrf_k, value={"k": 60.0, "weight": 1.08}）
    """
    __tablename__ = "expert_rule"

    # 多租户隔离
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # 可见范围
    scope: Mapped[ExpertScope] = mapped_column(
        Enum(ExpertScope, name="expert_scope"),
        default=ExpertScope.TENANT, index=True,
    )
    # 业务字段
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 例: calibration_threshold / tender_parse_part_b / disqualifying_keywords
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # JSON 编码的值（prompt / threshold / dict 等）
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    # 文本值（用于 prompt 模板等大文本）
    text_value: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # 版本（用于可演进追踪）
    version: Mapped[str] = mapped_column(String(32), default="1.0")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        # 同一 (scope, tenant_id, org_id, key) 三元组内唯一
        UniqueConstraint(
            "scope", "tenant_id", "org_id", "key",
            name="uq_expert_rule_scope_tenant_org_key",
        ),
        Index("ix_expert_rule_tenant_org", "tenant_id", "org_id"),
    )


# 兼容别名：ExpertMemory 与 ExpertRule 共用同一表（参考 lib-v0.2 ExpertMemory）
ExpertMemory = ExpertRule
