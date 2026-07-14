"""
Casbin RBAC 权限引擎封装

设计要点（v1.2 AI 优先原则 §13）：
- 权限校验是确定性边界，非 AI 判断
- 策略来源：现有 role_permission 表（Role ↔ Permission 多对多）
- 策略模型：RBAC（用户 → 角色 → 权限点）
- 缓存：内存 enforcer + 变更时重载（Phase 1 无 Redis；Phase 2 可改 Redis 缓存）
- 域（domain）：通过 project_id 行级隔离实现，不进 Casbin 策略（简化模型）

策略模型说明：
- r = sub, obj, act           请求：用户ID, 资源, 操作
- p = sub, obj, act           策略：角色code, 资源, 操作
- g = _, _                    用户-角色映射
- m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
"""
from __future__ import annotations

from typing import Optional

import casbin
from casbin.model import Model
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import sync_engine, SyncSessionLocal
from app.models.user import User, Role, Permission, role_permission

# ---------- Casbin 模型定义 ----------
MODEL_TEXT = """
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
"""


def _build_model() -> Model:
    """构造 Casbin 模型"""
    m = Model()
    m.load_model_from_text(MODEL_TEXT)
    return m


class CasbinEnforcer:
    """Casbin 权限校验引擎（线程安全单例）

    - enforcer：内存 enforcer，启动时从 DB 加载策略
    - reload()：权限/角色变更后重载策略
    - check(user_id, role_code, obj, act)：权限校验
    """

    def __init__(self):
        self._enforcer: Optional[casbin.Enforcer] = None
        self._loaded = False

    def _load_from_db(self) -> casbin.Enforcer:
        """从 DB 加载策略到内存 enforcer"""
        m = _build_model()
        # 使用空 adapter（不持久化到 DB，策略从现有表加载）
        enforcer = casbin.Enforcer(m)

        with SyncSessionLocal() as session:
            # 1. 加载所有权限点 → 创建策略 p = role_code, permission_code, "allow"
            # role_permission 关联表：role_id ↔ permission_id
            # 注意：Role 模型不继承 SoftDeleteMixin（角色删除为物理删除），无需 is_deleted 过滤
            stmt = (
                select(Role.code, Permission.code)
                .join(role_permission, role_permission.c.role_id == Role.id)
                .join(Permission, Permission.id == role_permission.c.permission_id)
            )
            result = session.execute(stmt).all()
            for role_code, perm_code in result:
                enforcer.add_policy(role_code, perm_code, "allow")

            # 2. 加载所有用户-角色映射 g = user_id, role_code
            stmt2 = select(User.id, Role.code).join(Role, User.role_id == Role.id)
            for user_id, role_code in session.execute(stmt2).all():
                enforcer.add_role_for_user(str(user_id), role_code)

            # 3. 管理员拥有所有权限（admin 角色 super 权限）
            # 通过给 admin 角色添加 "*" 通配策略，matcher 已不支持通配
            # 改为：admin 用户直接拥有所有权限点
            admin_perms = session.execute(
                select(Permission.code)
            ).scalars().all()
            for perm_code in admin_perms:
                enforcer.add_policy("admin", perm_code, "allow")

        logger.info(f"Casbin 策略加载完成：{len(enforcer.get_policy())} 条策略，"
                    f"{len(enforcer.get_grouping_policy())} 条角色映射")
        return enforcer

    @property
    def enforcer(self) -> casbin.Enforcer:
        """获取 enforcer（懒加载）"""
        if not self._loaded:
            self._enforcer = self._load_from_db()
            self._loaded = True
        return self._enforcer

    def reload(self):
        """重载策略（权限/角色变更后调用）"""
        self._loaded = False
        _ = self.enforcer  # 触发重新加载
        logger.info("Casbin 策略已重载")

    def check(self, user_id: str, obj: str, act: str = "allow") -> bool:
        """权限校验

        Args:
            user_id: 用户 ID（字符串）
            obj: 权限点 code（如 "contract:review"）
            act: 操作（默认 "allow"）
        Returns:
            是否允许
        """
        try:
            return self.enforcer.enforce(user_id, obj, act)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Casbin 校验异常 user={user_id} obj={obj}: {e}")
            return False

    def get_user_permissions(self, user_id: str) -> list[str]:
        """获取用户拥有的权限点列表"""
        try:
            # 获取用户的角色
            roles = self.enforcer.get_roles_for_user(user_id)
            perms = []
            for role in roles:
                for policy in self.enforcer.get_permissions_for_user(role):
                    perms.append(policy[1])  # policy = [sub, obj, act]
            return list(set(perms))
        except Exception as e:  # noqa: BLE001
            logger.error(f"获取用户权限异常 user={user_id}: {e}")
            return []


# 单例
_enforcer: Optional[CasbinEnforcer] = None


def get_enforcer() -> CasbinEnforcer:
    """获取 Casbin 引擎单例"""
    global _enforcer
    if _enforcer is None:
        _enforcer = CasbinEnforcer()
    return _enforcer
