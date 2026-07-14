"""N+1 查询检测测试

通过监听 SQLAlchemy `before_cursor_execute` 事件，统计每个 HTTP 请求触发的 SQL 查询数。
若列表端点的查询数随返回行数线性增长，则存在 N+1 问题（典型原因：循环内 lazy-load 关联）。

阈值规则：
- 每个 GET 列表端点查询数 ≤ MAX_QUERIES_PER_LIST（含 1 次 auth 的 get_current_user 查询）
- list_users 在 N 行数据下查询数应保持稳定（与行数无关）
"""
import uuid
from contextlib import contextmanager
from typing import List

import pytest
import pytest_asyncio
from sqlalchemy import event

from app.core import database as db_module
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User

# 测试数据规模（≥5 行，足以暴露 N+1：1+N 远超阈值）
TEST_USER_COUNT = 5
# 每个列表端点查询数阈值（含 1 次 auth 查询 + 1 次列表 + 1 次 selectin 关联 + 2 余量）
MAX_QUERIES_PER_LIST = 5


@contextmanager
def count_queries():
    """统计 SQL 查询数上下文管理器

    监听 async_engine.sync_engine 的 before_cursor_execute 事件，
    返回 (counter, statements)，statements 用于失败时打印诊断信息。
    """
    counter = {"count": 0}
    statements: List[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        counter["count"] += 1
        statements.append(statement)

    sync_engine = db_module.async_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter, statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", before_cursor_execute)


async def _seed_test_users(n: int) -> list:
    """创建 n 个测试用户（真实 commit，跨请求可见），返回 user_id 列表"""
    user_ids = []
    async with AsyncSessionLocal() as session:
        for i in range(n):
            user = User(
                username=f"n1test_{uuid.uuid4().hex[:8]}",
                hashed_password=hash_password("Test123456!"),
                full_name=f"N1测试用户_{i}",
                is_active=True,
                is_admin=False,
            )
            session.add(user)
        await session.commit()

        # 重新查询拿 id（commit 后实例可能 expired）
        result = await session.execute(
            User.__table__.select().where(User.username.like("n1test_%"))
        )
        user_ids = [row.id for row in result.all()]
    return user_ids


async def _cleanup_test_users(user_ids: list):
    """软删除测试用户（避免影响其他测试）"""
    if not user_ids:
        return
    async with AsyncSessionLocal() as session:
        for uid in user_ids:
            user = await session.get(User, uid)
            if user:
                user.is_active = False
                user.is_deleted = True
        await session.commit()


@pytest_asyncio.fixture
async def seeded_users():
    """创建 N 个测试用户供 list 端点使用（真实 commit）"""
    user_ids = await _seed_test_users(TEST_USER_COUNT)
    yield user_ids
    await _cleanup_test_users(user_ids)


# ============ 测试 1：列表端点查询数阈值 ============
# (endpoint, max_queries, description)
LIST_ENDPOINTS = [
    ("/api/v1/users", 4, "用户列表（含 role selectin 加载）"),
    ("/api/v1/projects", 4, "项目列表（无 eager 关联）"),
    ("/api/v1/roles", 4, "角色列表（含 permission selectin）"),
    ("/api/v1/permissions", 3, "权限点列表（无关联）"),
    ("/api/v1/organizations", 4, "组织列表"),
    ("/api/v1/qualifications", 4, "资质列表"),
    ("/api/v1/audit-logs", 4, "审计日志列表"),
]


@pytest.mark.parametrize(
    "endpoint, max_queries, desc",
    LIST_ENDPOINTS,
    ids=[e[2] for e in LIST_ENDPOINTS],
)
async def test_list_endpoint_query_count_below_threshold(
    client, admin_token, seeded_users, endpoint, max_queries, desc
):
    """验证列表端点查询数 ≤ 阈值

    前置：seeded_users 提供 N=5 行用户数据，确保列表非空。
    阈值含 1 次 auth 查询（get_current_user 调用 db.get）。
    超过阈值 → 疑似 N+1（每行触发额外查询）。
    """
    headers = {"Authorization": f"Bearer {admin_token['token']}"}
    with count_queries() as (counter, statements):
        resp = await client.get(endpoint, headers=headers)
    # 端点必须正常返回 200，否则查询数无意义（如 403 时根本没查列表）
    assert resp.status_code == 200, (
        f"{endpoint} 期望 200，实际 {resp.status_code}：{resp.text[:200]}"
    )
    query_count = counter["count"]
    assert query_count <= max_queries, (
        f"{desc} 检测到可能的 N+1 查询："
        f"查询数 {query_count} 超过阈值 {max_queries}（含 1 次 auth）。\n"
        "SQL 列表：\n" + "\n---\n".join(s[:200] for s in statements)
    )


# ============ 测试 2：list_users 查询数与行数无关（核心 N+1 检测）============
async def test_list_users_query_count_independent_of_rows(
    client, admin_token, seeded_users
):
    """关键检测：list_users 的查询数不应随返回行数增长

    场景：admin 调 list_users，返回至少 admin + N 个测试用户 = N+1 行。
    期望查询数：
      - 1 次 get_current_user（auth）
      - 1 次 SELECT users
      - 1 次 SELECT roles WHERE id IN (...) （role selectin）
      共 3 次。

    若每行触发额外查询（N+1），查询数应为 1+N 行 → 远超 5。
    阈值 5 给 N=5 的余量：1 (auth) + 1 (list) + 1 (selectin) + 2 余量。
    """
    headers = {"Authorization": f"Bearer {admin_token['token']}"}
    with count_queries() as (counter, statements):
        resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    # 确保有数据触发关联加载（至少 admin + N 测试用户）
    assert len(rows) >= TEST_USER_COUNT, (
        f"测试数据未生效：期望 ≥ {TEST_USER_COUNT} 行，实际 {len(rows)} 行"
    )
    query_count = counter["count"]
    assert query_count <= MAX_QUERIES_PER_LIST, (
        f"list_users 检测到 N+1：返回 {len(rows)} 行触发 {query_count} 次查询"
        f"（阈值 {MAX_QUERIES_PER_LIST}，应与行数无关）。\n"
        "SQL 列表：\n" + "\n---\n".join(s[:200] for s in statements)
    )


# ============ 测试 3：detail 端点查询数 ============
async def test_get_user_detail_query_count(client, admin_token, admin_user_id):
    """验证详情端点查询数 ≤ 阈值

    GET /api/v1/users/{id} 应触发：
      - 1 次 get_current_user（auth）
      - 1 次 db.get(User, id)
      共 2 次。阈值 3 含余量。
    """
    headers = {"Authorization": f"Bearer {admin_token['token']}"}
    with count_queries() as (counter, statements):
        resp = await client.get(f"/api/v1/users/{admin_user_id}", headers=headers)
    assert resp.status_code == 200
    assert counter["count"] <= 3, (
        f"get_user_detail 查询数 {counter['count']} 超阈值 3。\n"
        + "\n---\n".join(s[:200] for s in statements)
    )


@pytest_asyncio.fixture
async def admin_user_id(admin_token):
    """从 admin_token 提取 user_id 供 detail 端点测试使用"""
    return str(admin_token["user"].id)
