"""T7.2 审计日志完整性测试

测试：
- POST/PUT/DELETE 操作后 audit_log 表有记录
- 记录包含 user_id / action / resource / status
- GET 请求不记录审计
- 审计日志筛选有效
"""
import asyncio
import uuid
import pytest
from sqlalchemy import select, desc


async def _get_audit_logs(session, limit=20):
    """查询最近的审计日志"""
    from app.models.audit import AuditLog
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def test_post_creates_audit_log(client, admin_token):
    """POST 操作应创建审计日志"""
    from app.core.database import AsyncSessionLocal

    # 创建一个项目（POST）
    project_name = f"audit_test_{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/projects",
        json={"name": project_name, "code": f"code_{uuid.uuid4().hex[:6]}"},
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code in (200, 201), resp.text

    # 等待异步审计写入
    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as session:
        logs = await _get_audit_logs(session, limit=20)
        # 应有 create 类型的日志
        create_logs = [l for l in logs if l.action == "create" and l.resource == "project"]
        assert len(create_logs) > 0, "POST /projects 后应有 create 审计日志"


async def test_audit_log_contains_user_info(client, admin_token):
    """审计日志应包含 user_id 和 username"""
    from app.core.database import AsyncSessionLocal
    from app.models.audit import AuditLog

    # 触发一次写操作
    resp = await client.post(
        "/api/v1/roles",
        json={"code": f"audit_{uuid.uuid4().hex[:6]}", "name": "审计测试角色", "description": "test"},
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 201, resp.text

    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as session:
        stmt = select(AuditLog).where(AuditLog.resource == "role").order_by(desc(AuditLog.created_at)).limit(5)
        logs = (await session.execute(stmt)).scalars().all()
        assert len(logs) > 0
        log = logs[0]
        assert log.user_id is not None, "审计日志应记录 user_id"
        assert log.username == "admin", f"审计日志应记录 username=admin，实际 {log.username}"
        assert log.action is not None
        assert log.resource is not None
        assert log.status is not None


async def test_get_not_audited(client, admin_token):
    """GET 请求不应记录审计日志"""
    from app.core.database import AsyncSessionLocal
    from app.models.audit import AuditLog
    from sqlalchemy import func

    # 记录当前审计日志数
    async with AsyncSessionLocal() as session:
        count_before = (await session.execute(select(func.count(AuditLog.id)))).scalar()

    # 执行多次 GET
    for _ in range(5):
        await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {admin_token['token']}"},
        )
        await client.get(
            "/api/v1/roles",
            headers={"Authorization": f"Bearer {admin_token['token']}"},
        )

    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as session:
        count_after = (await session.execute(select(func.count(AuditLog.id)))).scalar()

    # GET 不应产生新审计日志（容忍 ±1 误差，因可能有其他异步任务）
    assert count_after - count_before <= 1, f"GET 请求不应产生审计日志，before={count_before} after={count_after}"


async def test_audit_log_filter_by_action(client, admin_token):
    """审计日志按 action 筛选有效"""
    # 触发一次写操作
    await client.post(
        "/api/v1/projects",
        json={"name": f"filter_test_{uuid.uuid4().hex[:6]}", "code": f"fc_{uuid.uuid4().hex[:6]}"},
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    await asyncio.sleep(0.3)

    # 按 action=create 筛选
    resp = await client.get(
        "/api/v1/audit-logs?action=create&limit=5",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # 所有返回的日志 action 应为 create
    for log in data:
        assert log["action"] == "create", f"筛选 action=create 但返回 action={log['action']}"


async def test_audit_log_filter_by_resource(client, admin_token):
    """审计日志按 resource 筛选有效"""
    resp = await client.get(
        "/api/v1/audit-logs?resource=user&limit=5",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for log in data:
        assert log["resource"] == "user", f"筛选 resource=user 但返回 resource={log['resource']}"


async def test_audit_log_export_csv(client, admin_token):
    """审计日志 CSV 导出"""
    resp = await client.get(
        "/api/v1/audit-logs/export",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "\ufeff" in content or "时间" in content, "CSV 应含 BOM 或表头"
    assert "Content-Disposition" in resp.headers


async def test_audit_log_records_status_code(client, admin_token):
    """审计日志应记录操作状态（成功/失败）"""
    from app.core.database import AsyncSessionLocal
    from app.models.audit import AuditLog

    # 触发一个失败操作（用无效数据）
    await client.post(
        "/api/v1/projects",
        json={"invalid": "data"},  # 缺少必填字段
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )

    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.resource == "project")
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )
        logs = (await session.execute(stmt)).scalars().all()
        # 应该有失败状态的日志
        failed_logs = [l for l in logs if l.status == "failed"]
        assert len(failed_logs) > 0, "应有 failed 状态的审计日志（来自 422 请求）"


async def test_non_admin_cannot_view_audit_logs(client, role_tokens):
    """非 admin 角色不能查看审计日志（无 audit_log:view 权限）"""
    token = role_tokens["presales"]["token"]
    resp = await client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
