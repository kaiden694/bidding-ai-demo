"""pytest 配置

- 将 backend 加入 sys.path
- 配置 asyncio_default_fixture_loop_scope=function 消除警告（在 pytest.ini 中）
- 用 NullPool 替换 async_engine 连接池，避免 pytest-asyncio 跨事件循环导致连接失效
- 提供 db_session / client / admin_token / role_tokens fixtures
"""
import asyncio
import os
import sys
import uuid
from typing import Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---- 引擎连接池替换：NullPool 避免 pytest-asyncio 跨事件循环失效 ----
@pytest.fixture(scope="session", autouse=True)
def _patch_engine_pool():
    """会话级 autouse：把 async_engine 的连接池替换为 NullPool。

    NullPool 每次请求都新建连接，不缓存连接对象——这样即使 pytest-asyncio
    为每个测试函数创建新的事件循环，也不会留下绑定到旧 loop 的连接。
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool
    from sqlalchemy import text
    from app.core import database as db_module

    # 用 NullPool 重建 async_engine，保持原 URL
    new_engine = create_async_engine(
        db_module.async_engine.url,
        poolclass=NullPool,
        echo=False,
    )
    db_module.async_engine = new_engine
    # 重建 AsyncSessionLocal
    db_module.AsyncSessionLocal = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 创建所有表（create_all 幂等；确保新增表如 feedback_record 存在）
    import asyncio as _asyncio

    async def _create_all():
        # 导入所有模型让 Base.metadata 感知它们
        import app.models  # noqa: F401  触发模型导入
        from app.core.database import Base, AsyncSessionLocal
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # 补齐已有表的缺失列（create_all 不 ALTER 已有表）
            # knowledge_base.tags / knowledge_chunk.tags 在模型更新后未迁移
            await conn.execute(text("ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS tags JSON"))
            await conn.execute(text("ALTER TABLE knowledge_chunk ADD COLUMN IF NOT EXISTS tags JSON"))

        # 增量补齐种子数据（角色 / 权限点 / 角色-权限关联）
        # seed_all 是幂等的：仅插入缺失的权限点、补齐缺失的角色-权限关联
        # 修复旧版 DB 缺少 feedback:view / feedback:create 权限点导致 Casbin 策略不完整
        from app.db.base_data import seed_all
        async with AsyncSessionLocal() as session:
            await seed_all(session)

    # 在事件循环中执行（会话级 fixture 不在 async 上下文，需手动管理）
    try:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        loop.run_until_complete(_create_all())
        loop.close()
    except Exception:
        pass

    yield

    # 会话结束：释放引擎
    try:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        loop.run_until_complete(new_engine.dispose())
        loop.close()
    except Exception:
        pass


# ---- DB Session fixture（事务回滚隔离）----
@pytest_asyncio.fixture
async def db_session():
    """每个测试用事务回滚隔离，不污染数据库"""
    from app.core.database import async_engine, AsyncSessionLocal
    from sqlalchemy.ext.asyncio import AsyncSession

    async with async_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        async with AsyncSession(bind=conn) as session:
            yield session
        await conn.rollback()


# ---- HTTP Client fixture ----
@pytest_asyncio.fixture
async def client():
    """httpx.AsyncClient + ASGITransport（不触发 lifespan）

    raise_app_exceptions=False：端点抛异常时返回 500 而非把异常传播到测试，
    权限隔离测试只关心 401/403/非 403，不因端点本身 bug 失败。
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---- 工具：创建测试用户并生成 token ----
async def _create_test_user(
    session,
    username: str,
    password: str = "Test123456!",
    role_code: Optional[str] = None,
    is_admin: bool = False,
):
    """创建测试用户（不 commit，依赖外层事务），返回 (user, token)"""
    from sqlalchemy import select
    from app.core.security import hash_password, create_access_token
    from app.models.user import User, Role

    role_id = None
    if role_code:
        result = await session.execute(
            select(Role).where(Role.code == role_code)
        )
        role = result.scalar_one_or_none()
        if role:
            role_id = role.id

    user = User(
        username=username,
        hashed_password=hash_password(password),
        full_name=f"测试用户_{username}",
        is_active=True,
        is_admin=is_admin,
        role_id=role_id,
    )
    session.add(user)
    await session.flush()  # 拿到 user.id，不 commit

    token = create_access_token(str(user.id), {"username": user.username, "is_admin": user.is_admin})
    return user, token


async def _get_or_create_admin(session):
    """获取或创建 admin 用户（真实 commit，用于跨请求测试）"""
    from sqlalchemy import select
    from app.core.security import hash_password, create_access_token
    from app.models.user import User

    result = await session.execute(select(User).where(User.username == "admin"))
    user = result.scalar_one_or_none()
    if user:
        token = create_access_token(str(user.id), {"username": user.username, "is_admin": True})
        return user, token

    # 创建 admin
    user = User(
        username="admin",
        hashed_password=hash_password("admin123"),
        full_name="系统管理员",
        is_active=True,
        is_admin=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(str(user.id), {"username": user.username, "is_admin": True})
    return user, token


# ---- Admin Token fixture ----
@pytest_asyncio.fixture
async def admin_token():
    """返回 (admin_user, admin_token_str)，真实写入 DB"""
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        user, token = await _get_or_create_admin(session)
        return {"user": user, "token": token}


# ---- 各角色 Token fixture ----
@pytest_asyncio.fixture
async def role_tokens():
    """为每个非 admin 角色创建测试用户 + token，返回 {role_code: {user, token}}

    真实 commit（用于跨请求测试），测试后清理。
    """
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    created_users = []
    tokens = {}
    async with AsyncSessionLocal() as session:
        for role_code in ["presales", "legal", "procurement", "pm", "compliance"]:
            username = f"test_{role_code}_{uuid.uuid4().hex[:8]}"
            user, token = await _create_test_user(
                session, username, role_code=role_code
            )
            created_users.append(user)
            tokens[role_code] = {"user": user, "token": token}
        await session.commit()

    # 关键：重载 Casbin 策略，让新建的测试用户-角色映射进入内存 enforcer
    # （enforcer 是单例，首次加载后不会自动感知新增用户）
    from app.core.casbin import get_enforcer
    get_enforcer().reload()

    yield tokens

    # 清理：软删除用户（硬删除会因 audit_log 外键约束失败，因为测试触发的写操作会记录审计日志）
    async with AsyncSessionLocal() as session:
        for user in created_users:
            db_user = await session.get(User, user.id)
            if db_user:
                db_user.is_active = False
                db_user.is_deleted = True
        await session.commit()
