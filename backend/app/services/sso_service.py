"""
SSO/OIDC 服务层（Phase 3 T5：单点登录对接）

职责：
- get_authorization_url: 构建 IdP 授权页 URL（含 state 防 CSRF）
- handle_callback: code → token → userinfo → 用户映射 → 签发本地 JWT
- discover_endpoints: 调用 OIDC discovery，缓存到 SSOConfig
- 配置 CRUD：list/create/update/delete

设计要点：
- 用 httpx 异步调用 OIDC 端点，所有外部 HTTP 调用 10s 超时
- state 防 CSRF：随机生成，缓存 {provider_name, created_at, user_ip}，5 分钟过期
- 首次登录自动创建 User + UserSSOLink（基于 OIDC sub）
- 复用 app.core.security 的 create_access_token / create_refresh_token 签发本地 JWT
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.casbin import get_enforcer
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.sso import SSOConfig, UserSSOLink
from app.models.user import Role, User
from app.schemas.sso import (
    SSOConfigCreate,
    SSOConfigUpdate,
)

# 默认 OIDC scopes
DEFAULT_SCOPES = ["openid", "profile", "email"]

# state 有效期 5 分钟
STATE_TTL_SECONDS = 300

# 外部 HTTP 调用超时
HTTP_TIMEOUT_SECONDS = 10.0


class SSOService:
    """SSO/OIDC 单点登录服务"""

    # State 缓存（进程内存；多实例部署应改为 Redis）
    # state -> {provider_name, created_at, user_ip}
    _state_store: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 公开接口：获取授权 URL
    # ------------------------------------------------------------------
    async def get_authorization_url(
        self,
        db: AsyncSession,
        provider_name: str,
        redirect_uri: Optional[str] = None,
        user_ip: Optional[str] = None,
    ) -> dict:
        """构建 IdP 授权页 URL

        Args:
            db: 异步会话
            provider_name: SSO 配置名称
            redirect_uri: 覆盖配置中的回调地址（可选）
            user_ip: 用户 IP（用于 state 缓存审计）

        Returns:
            {"authorization_url": "...", "state": "...", "provider_name": "..."}
        """
        config = await self._get_config(db, provider_name, must_active=True)
        if config is None:
            raise ValueError(f"SSO 配置不存在或未启用: {provider_name}")

        # 若未配置 authorization_endpoint，触发 discovery
        if not config.authorization_endpoint:
            await self.discover_endpoints(db, config)

        # 重新读取（discovery 可能已更新端点）
        await db.refresh(config)
        if not config.authorization_endpoint:
            raise ValueError(
                f"无法获取 authorization_endpoint（provider={provider_name}），"
                f"请检查 issuer 或手动配置端点"
            )

        # 生成 state（防 CSRF）
        state = secrets.token_urlsafe(32)
        self._state_store[state] = {
            "provider_name": provider_name,
            "created_at": datetime.now(timezone.utc),
            "user_ip": user_ip,
        }
        # 清理过期 state
        self._cleanup_expired_states()

        # 实际使用的 redirect_uri
        effective_redirect = redirect_uri or config.redirect_uri

        # 构建 URL
        scopes = config.scopes or DEFAULT_SCOPES
        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": effective_redirect,
            "scope": " ".join(scopes),
            "state": state,
        }
        url = f"{config.authorization_endpoint}?{urlencode(params)}"
        return {
            "authorization_url": url,
            "state": state,
            "provider_name": provider_name,
        }

    # ------------------------------------------------------------------
    # 公开接口：处理回调
    # ------------------------------------------------------------------
    async def handle_callback(
        self,
        db: AsyncSession,
        provider_name: Optional[str],
        code: str,
        state: str,
    ) -> dict:
        """OIDC 回调处理

        步骤：
        1. 校验 state（防 CSRF）
        2. 用 code 换 token
        3. 用 access_token 获取 userinfo
        4. 查/创建 UserSSOLink + User
        5. 签发本地 JWT
        6. 返回 {access_token, refresh_token, token_type, user, permissions}
        """
        # 1. 校验 state
        state_data = self._state_store.pop(state, None)
        if state_data is None:
            raise ValueError("无效或已过期的 state（可能为 CSRF 攻击）")
        # 校验 provider 一致性
        resolved_provider = provider_name or state_data.get("provider_name")
        if not resolved_provider:
            raise ValueError("回调未提供 provider_name，且 state 中无 provider 信息")
        if provider_name and state_data.get("provider_name") != provider_name:
            raise ValueError("state 中的 provider 与请求的 provider 不一致")

        # 2. 加载配置
        config = await self._get_config(db, resolved_provider, must_active=True)
        if config is None:
            raise ValueError(f"SSO 配置不存在或未启用: {resolved_provider}")

        # 3. 用 code 换 token
        token_data = await self._exchange_code(config, code)
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError(
                f"未从 IdP 获取到 access_token: {token_data.get('error_description') or token_data}"
            )

        # 4. 获取 userinfo
        userinfo = await self._fetch_userinfo(config, access_token)
        sub = userinfo.get("sub")
        if not sub:
            raise ValueError("IdP userinfo 中缺少 sub 字段")

        # 5. 查/创建本地用户
        user = await self._resolve_user(db, config, resolved_provider, sub, userinfo)

        # 6. 签发本地 JWT
        local_access = create_access_token(
            str(user.id),
            {"username": user.username, "is_admin": user.is_admin},
        )
        local_refresh = create_refresh_token(str(user.id))

        # 7. 获取权限点列表
        perms = await self._get_user_permissions(user)

        return {
            "access_token": local_access,
            "refresh_token": local_refresh,
            "token_type": "bearer",
            "user_id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
            "permissions": perms,
        }

    # ------------------------------------------------------------------
    # 内部：code → token 交换
    # ------------------------------------------------------------------
    async def _exchange_code(self, config: SSOConfig, code: str) -> dict:
        """用 authorization_code 换 access_token

        POST token_endpoint
        Content-Type: application/x-www-form-urlencoded
        """
        if not config.token_endpoint:
            raise ValueError("token_endpoint 未配置，请先 discovery 或手动配置")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
        }
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    config.token_endpoint,
                    data=data,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    raise ValueError(
                        f"IdP token 端点返回 {resp.status_code}: {resp.text[:500]}"
                    )
                return resp.json()
        except httpx.RequestError as e:
            raise ValueError(f"无法连接 IdP token 端点: {e}")

    # ------------------------------------------------------------------
    # 内部：获取 userinfo
    # ------------------------------------------------------------------
    async def _fetch_userinfo(self, config: SSOConfig, access_token: str) -> dict:
        """用 access_token 获取用户信息"""
        if not config.userinfo_endpoint:
            raise ValueError("userinfo_endpoint 未配置，请先 discovery 或手动配置")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    config.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code != 200:
                    raise ValueError(
                        f"IdP userinfo 端点返回 {resp.status_code}: {resp.text[:500]}"
                    )
                return resp.json()
        except httpx.RequestError as e:
            raise ValueError(f"无法连接 IdP userinfo 端点: {e}")

    # ------------------------------------------------------------------
    # 内部：用户映射
    # ------------------------------------------------------------------
    async def _resolve_user(
        self,
        db: AsyncSession,
        config: SSOConfig,
        provider_name: str,
        sub: str,
        userinfo: dict,
    ) -> User:
        """根据 (provider_name, sub) 解析或创建本地用户

        - 已存在 UserSSOLink：返回关联的 User
        - 不存在且 auto_create_user=True：创建 User + UserSSOLink
        - 不存在且 auto_create_user=False：抛 403
        """
        # 查找现有 link
        stmt = (
            select(UserSSOLink)
            .where(
                UserSSOLink.provider_name == provider_name,
                UserSSOLink.sub == sub,
            )
        )
        result = await db.execute(stmt)
        link = result.scalars().first()

        if link is not None:
            user = await db.get(User, link.user_id)
            if user is None or user.is_deleted:
                raise ValueError("关联用户不存在或已删除")
            if not user.is_active:
                raise PermissionError("用户已禁用")
            return user

        # 无关联用户
        if not config.auto_create_user:
            raise PermissionError(
                f"用户未关联且 IdP [{provider_name}] 未启用自动创建用户"
            )

        # 创建新用户
        user = await self._create_user_from_userinfo(db, config, provider_name, sub, userinfo)
        return user

    async def _create_user_from_userinfo(
        self,
        db: AsyncSession,
        config: SSOConfig,
        provider_name: str,
        sub: str,
        userinfo: dict,
    ) -> User:
        """根据 userinfo 创建本地用户 + UserSSOLink

        - username: 优先用 email 前缀 或 preferred_username，否则取 sub 前 8 位
        - password: 随机生成（SSO 用户不使用密码登录）
        - 默认角色：若 config.default_role_code 配置则分配
        """
        email = userinfo.get("email")
        preferred_username = userinfo.get("preferred_username")
        name = userinfo.get("name")
        given_name = userinfo.get("given_name")
        family_name = userinfo.get("family_name")

        # 生成 username（确保唯一）
        base_username = (
            preferred_username
            or (email.split("@")[0] if email else None)
            or sub[:8]
        )
        username = await self._ensure_unique_username(db, base_username)

        # 生成 full_name
        full_name = name
        if not full_name:
            parts = [p for p in [given_name, family_name] if p]
            full_name = " ".join(parts) if parts else None

        # 解析默认角色
        role_id = None
        if config.default_role_code:
            role_stmt = select(Role).where(Role.code == config.default_role_code)
            role = (await db.execute(role_stmt)).scalars().first()
            if role is not None:
                role_id = role.id

        # 创建用户（随机密码，不可用密码登录）
        random_password = secrets.token_urlsafe(32)
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(random_password),
            full_name=full_name,
            is_active=True,
            is_admin=False,
            role_id=role_id,
        )
        db.add(user)
        await db.flush()  # 拿到 user.id

        # 创建 SSO 关联
        link = UserSSOLink(
            user_id=user.id,
            provider_name=provider_name,
            sub=sub,
        )
        db.add(link)
        await db.commit()
        await db.refresh(user)

        # 重新加载 Casbin 策略（让新用户-角色映射生效）
        try:
            get_enforcer().reload()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Casbin 策略重载失败（不影响 SSO 登录）: {e}")

        logger.info(
            f"SSO 自动创建用户: provider={provider_name} sub={sub} "
            f"username={username} role={config.default_role_code}"
        )
        return user

    async def _ensure_unique_username(self, db: AsyncSession, base: str) -> str:
        """确保 username 唯一：冲突则追加 _2/_3/..."""
        # 清洗：仅保留字母数字下划线，长度限制
        cleaned = "".join(c if (c.isalnum() or c in "_-") else "_" for c in base)
        if not cleaned:
            cleaned = "sso_user"
        cleaned = cleaned[:32]
        candidate = cleaned
        suffix = 1
        while True:
            stmt = select(User.id).where(User.username == candidate)
            existing = (await db.execute(stmt)).first()
            if existing is None:
                return candidate
            suffix += 1
            candidate = f"{cleaned[:24]}_{suffix}"

    async def _get_user_permissions(self, user: User) -> list[str]:
        """获取用户权限点列表"""
        if user.is_admin:
            from app.db.base_data import DEFAULT_PERMISSIONS
            return [code for code, _, _, _ in DEFAULT_PERMISSIONS]
        enforcer = get_enforcer()
        return enforcer.get_user_permissions(str(user.id))

    # ------------------------------------------------------------------
    # 内部：OIDC Discovery
    # ------------------------------------------------------------------
    async def discover_endpoints(
        self,
        db: AsyncSession,
        config: SSOConfig,
    ) -> dict:
        """调用 OIDC discovery 文档

        GET {issuer}/.well-known/openid-configuration
        缓存结果到 SSOConfig.discovery_cache + 更新端点字段
        """
        # 拼接 discovery URL（去除尾部斜杠）
        issuer = config.issuer.rstrip("/")
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(discovery_url)
                if resp.status_code != 200:
                    raise ValueError(
                        f"discovery 返回 {resp.status_code}: {resp.text[:500]}"
                    )
                doc = resp.json()
        except httpx.RequestError as e:
            raise ValueError(f"无法连接 IdP discovery 端点: {e}")

        # 更新端点字段
        if doc.get("authorization_endpoint"):
            config.authorization_endpoint = doc["authorization_endpoint"]
        if doc.get("token_endpoint"):
            config.token_endpoint = doc["token_endpoint"]
        if doc.get("userinfo_endpoint"):
            config.userinfo_endpoint = doc["userinfo_endpoint"]
        config.discovery_cache = doc
        config.discovery_cached_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(config)
        return doc

    # ------------------------------------------------------------------
    # 内部：state 清理
    # ------------------------------------------------------------------
    def _cleanup_expired_states(self) -> None:
        """清理过期 state"""
        now = datetime.now(timezone.utc)
        expired_keys = [
            k for k, v in self._state_store.items()
            if (now - v["created_at"]).total_seconds() > STATE_TTL_SECONDS
        ]
        for k in expired_keys:
            self._state_store.pop(k, None)

    # ------------------------------------------------------------------
    # 内部：加载配置
    # ------------------------------------------------------------------
    async def _get_config(
        self,
        db: AsyncSession,
        provider_name: str,
        must_active: bool = True,
    ) -> Optional[SSOConfig]:
        """按 provider_name 加载 SSO 配置"""
        stmt = select(SSOConfig).where(SSOConfig.provider_name == provider_name)
        config = (await db.execute(stmt)).scalars().first()
        if config is None:
            return None
        if must_active and not config.is_active:
            return None
        return config

    # ------------------------------------------------------------------
    # 公开接口：列出可用提供商
    # ------------------------------------------------------------------
    async def list_active_providers(self, db: AsyncSession) -> list[SSOConfig]:
        """列出已启用的 SSO 提供商（公开端点使用，仅返回 name + display_name）"""
        stmt = select(SSOConfig).where(SSOConfig.is_active.is_(True))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # 管理接口：配置 CRUD
    # ------------------------------------------------------------------
    async def list_configs(self, db: AsyncSession) -> list[SSOConfig]:
        """列出所有 SSO 配置"""
        stmt = select(SSOConfig).order_by(SSOConfig.created_at.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_config_by_id(self, db: AsyncSession, config_id) -> Optional[SSOConfig]:
        """按 id 加载 SSO 配置"""
        import uuid as _uuid
        try:
            cid = _uuid.UUID(str(config_id))
        except ValueError:
            return None
        return await db.get(SSOConfig, cid)

    async def create_config(self, db: AsyncSession, payload: SSOConfigCreate) -> SSOConfig:
        """创建 SSO 配置"""
        # 唯一性检查
        existing = await db.execute(
            select(SSOConfig).where(SSOConfig.provider_name == payload.provider_name)
        )
        if existing.scalars().first() is not None:
            raise ValueError(f"provider_name 已存在: {payload.provider_name}")

        data = payload.model_dump()
        # scopes 默认值
        if data.get("scopes") is None:
            data["scopes"] = DEFAULT_SCOPES
        config = SSOConfig(**data)
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    async def update_config(
        self,
        db: AsyncSession,
        config_id,
        payload: SSOConfigUpdate,
    ) -> SSOConfig:
        """更新 SSO 配置"""
        config = await self.get_config_by_id(db, config_id)
        if config is None:
            raise ValueError("SSO 配置不存在")

        data = payload.model_dump(exclude_unset=True)
        # 若更新了 issuer，需要清除缓存的 discovery
        if "issuer" in data and data["issuer"] != config.issuer:
            config.discovery_cache = None
            config.discovery_cached_at = None
            # 端点也会失效，清除
            config.authorization_endpoint = None
            config.token_endpoint = None
            config.userinfo_endpoint = None

        for k, v in data.items():
            setattr(config, k, v)
        await db.commit()
        await db.refresh(config)
        return config

    async def delete_config(self, db: AsyncSession, config_id) -> None:
        """删除 SSO 配置（物理删除；UserSSOLink 保留以避免破坏历史关联）"""
        config = await self.get_config_by_id(db, config_id)
        if config is None:
            raise ValueError("SSO 配置不存在")
        await db.delete(config)
        await db.commit()


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------
_sso_service: Optional[SSOService] = None


def get_sso_service() -> SSOService:
    """获取 SSOService 单例"""
    global _sso_service
    if _sso_service is None:
        _sso_service = SSOService()
    return _sso_service
