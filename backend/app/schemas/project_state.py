"""项目状态机 Schema（Phase 3 T1）"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.project import ProjectStatus


class TransitionRequest(BaseModel):
    """状态流转请求"""
    to_status: ProjectStatus
    reason: Optional[str] = None
    ai_suggestion: bool = False  # 是否采纳了 AI 推荐


class TransitionOut(BaseModel):
    """状态变更记录"""
    id: uuid.UUID
    project_id: uuid.UUID
    from_status: ProjectStatus
    to_status: ProjectStatus
    transition_by: Optional[uuid.UUID]
    reason: Optional[str]
    ai_suggestion: bool
    metadata_json: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NextStatusesResponse(BaseModel):
    """可流转的下一状态列表"""
    current_status: ProjectStatus
    next_statuses: list[ProjectStatus]


class RecommendNextStatusResponse(BaseModel):
    """AI 推荐的下一状态（辅助，非强制）"""
    recommended_status: Optional[ProjectStatus]
    reason: Optional[str]
    confidence: Optional[float]
    available_next_statuses: list[ProjectStatus]


class StatusRuleItem(BaseModel):
    """单条状态规则（用于批量更新）"""
    from_status: ProjectStatus
    to_status: ProjectStatus
    is_active: bool = True
    description: Optional[str] = None


class StatusRuleUpdate(BaseModel):
    """批量更新状态转移规则"""
    rules: list[StatusRuleItem]


class StatusRuleOut(BaseModel):
    """状态规则输出"""
    id: uuid.UUID
    from_status: ProjectStatus
    to_status: ProjectStatus
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
