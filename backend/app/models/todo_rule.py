"""
待办自动生成规则模型（Phase 3 T2）

设计要点（v1.2 §13 AI 优先）：
- 待办自动生成规则可配置（DB 存储），不硬编码 if-else
- 触发条件为项目状态（trigger_status），到状态后自动生成对应待办
- assignee_role 指定分配给哪个角色（角色 code，如 presales/legal/pm）
"""
from typing import Optional

from sqlalchemy import String, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDPKMixin, TimestampMixin
from app.core.database import Base


class TodoRule(Base, UUIDPKMixin, TimestampMixin):
    """待办自动生成规则（状态变更触发）

    一条规则表示：项目进入 trigger_status 状态时，自动生成一条待办：
    - todo_title / todo_description：待办内容
    - assignee_role：分配给哪个角色（角色 code）
    - due_days：几日后到期
    - is_active=False 可临时禁用
    """
    __tablename__ = "todo_rule"

    trigger_status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # 触发状态
    todo_title: Mapped[str] = mapped_column(String(256), nullable=False)  # 待办标题
    todo_description: Mapped[Optional[str]] = mapped_column(Text)
    assignee_role: Mapped[Optional[str]] = mapped_column(String(64))  # 分配给哪个角色
    due_days: Mapped[Optional[int]] = mapped_column(Integer)  # 几天后到期
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
