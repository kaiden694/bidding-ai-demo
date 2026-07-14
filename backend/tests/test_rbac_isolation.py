"""T7.1 权限隔离测试

覆盖：
1. 未认证访问受保护端点 → 401
2. admin 访问所有端点 → 非 401/403
3. 各非 admin 角色访问无权限端点 → 403
4. 各非 admin 角色访问有权限端点 → 非 403

权限矩阵来自 app/db/base_data.py 的 DEFAULT_ROLE_PERMISSIONS。
"""
import uuid
import pytest

# ---- 端点定义：(method, path, required_permission, body) ----
# body 为 None 表示无 body；带占位 UUID 的端点用 404 期望（有权限时）
FAKE_UUID = "00000000-0000-0000-0000-000000000001"

ENDPOINTS = [
    # (method, path, permission, body)
    # 用户管理
    ("GET", "/api/v1/users", "user:view", None),
    ("POST", "/api/v1/users", "user:create", {"username": f"t_{uuid.uuid4().hex[:6]}", "password": "Test123!", "email": "t@t.com"}),
    ("GET", f"/api/v1/users/{FAKE_UUID}", "user:view", None),
    ("PUT", f"/api/v1/users/{FAKE_UUID}", "user:update", {"full_name": "updated"}),
    ("DELETE", f"/api/v1/users/{FAKE_UUID}", "user:delete", None),
    ("POST", f"/api/v1/users/{FAKE_UUID}/reset-password", "user:reset_password", {"new_password": "New123!"}),
    # 角色管理
    ("GET", "/api/v1/roles", "role:view", None),
    ("POST", "/api/v1/roles", "role:create", {"code": f"r_{uuid.uuid4().hex[:6]}", "name": "测试角色", "description": "test"}),
    ("PUT", f"/api/v1/roles/{FAKE_UUID}", "role:update", {"name": "updated"}),
    ("DELETE", f"/api/v1/roles/{FAKE_UUID}", "role:update", None),
    ("PUT", f"/api/v1/roles/{FAKE_UUID}/permissions", "role:assign_permissions", {"permission_ids": []}),
    ("GET", f"/api/v1/roles/{FAKE_UUID}/permissions", "role:view", None),
    # 权限管理
    ("GET", "/api/v1/permissions", "role:view", None),
    ("GET", "/api/v1/permissions/grouped", "role:view", None),
    # 组织管理
    ("GET", "/api/v1/organizations", "organization:view", None),
    ("GET", "/api/v1/organizations/tree", "organization:view", None),
    ("POST", "/api/v1/organizations", "organization:create", {"name": "测试组织", "code": f"o_{uuid.uuid4().hex[:6]}"}),
    ("PUT", f"/api/v1/organizations/{FAKE_UUID}", "organization:update", {"name": "updated"}),
    ("DELETE", f"/api/v1/organizations/{FAKE_UUID}", "organization:delete", None),
    # 审计日志
    ("GET", "/api/v1/audit-logs", "audit_log:view", None),
    ("GET", "/api/v1/audit-logs/export", "audit_log:export", None),
    # 项目
    ("GET", "/api/v1/projects", "project:view", None),
    ("POST", "/api/v1/projects", "project:create", {"name": "测试项目", "code": f"p_{uuid.uuid4().hex[:6]}"}),
    ("GET", f"/api/v1/projects/{FAKE_UUID}", "project:view", None),
    # 文档
    ("GET", "/api/v1/documents", "document:view", None),
    ("POST", f"/api/v1/documents/{FAKE_UUID}/parse", "document:parse", None),
    # 合同
    ("GET", "/api/v1/contracts", "contract:view", None),
    ("POST", "/api/v1/contracts", "contract:create", {"name": "测试合同", "project_id": FAKE_UUID}),
    ("GET", f"/api/v1/contracts/{FAKE_UUID}", "contract:view", None),
    ("POST", f"/api/v1/contracts/{FAKE_UUID}/review", "contract:review", {"contract_id": FAKE_UUID}),
    ("GET", f"/api/v1/contracts/{FAKE_UUID}/export", "contract:export", None),
    # 参数偏离比对（注意：后端无 GET /comparison 列表端点）
    ("POST", "/api/v1/comparison", "comparison:create", {"project_id": FAKE_UUID, "spec_document_id": FAKE_UUID}),
    ("GET", f"/api/v1/comparison/{FAKE_UUID}", "comparison:view", None),
    ("GET", f"/api/v1/comparison/{FAKE_UUID}/export", "comparison:export", None),
    # 知识库
    ("GET", "/api/v1/knowledge/bases", "knowledge:view", None),
    ("POST", "/api/v1/knowledge/bases", "knowledge:create", {"name": "测试KB", "category": "test"}),
    ("GET", f"/api/v1/knowledge/bases/{FAKE_UUID}", "knowledge:view", None),
    ("PATCH", f"/api/v1/knowledge/bases/{FAKE_UUID}", "knowledge:create", {"description": "updated"}),
    ("DELETE", f"/api/v1/knowledge/bases/{FAKE_UUID}", "knowledge:delete", None),
    ("POST", f"/api/v1/knowledge/bases/{FAKE_UUID}/import", "knowledge:import", None),
    ("POST", f"/api/v1/knowledge/bases/{FAKE_UUID}/reindex", "knowledge:reindex", None),
    ("GET", f"/api/v1/knowledge/bases/{FAKE_UUID}/import-status", "knowledge:view", None),
    ("POST", f"/api/v1/knowledge/bases/{FAKE_UUID}/switch-version", "knowledge:create", {"version": "2.0"}),
    ("GET", f"/api/v1/knowledge/bases/{FAKE_UUID}/chunks", "knowledge:view", None),
    ("POST", f"/api/v1/knowledge/bases/{FAKE_UUID}/chunks/filter", "knowledge:view", {"tag_key": "t", "tag_value": "v"}),
    ("PATCH", f"/api/v1/knowledge/chunks/{FAKE_UUID}/tags", "knowledge:create", {"tags": {}}),
    ("POST", "/api/v1/knowledge/search", "knowledge:view", {"query": "test"}),
    # 通用知识库
    ("GET", "/api/v1/general-knowledge", "general_knowledge:view", None),
    ("POST", "/api/v1/general-knowledge", "general_knowledge:create", {"name": "测试GKB", "category": "test", "visibility": "all"}),
    ("GET", f"/api/v1/general-knowledge/{FAKE_UUID}", "general_knowledge:view", None),
    ("DELETE", f"/api/v1/general-knowledge/{FAKE_UUID}", "general_knowledge:delete", None),
    ("POST", "/api/v1/general-knowledge/search", "general_knowledge:view", {"query": "test"}),
    ("POST", f"/api/v1/general-knowledge/{FAKE_UUID}/import", "general_knowledge:import", None),
    ("POST", f"/api/v1/general-knowledge/{FAKE_UUID}/reindex", "general_knowledge:create", None),
    ("GET", f"/api/v1/general-knowledge/{FAKE_UUID}/import-status", "general_knowledge:view", None),
    # 资质
    ("GET", "/api/v1/qualifications", "qualification:view", None),
    ("POST", "/api/v1/qualifications", "qualification:create", {"name": "测试资质", "qual_type": "ISO9001"}),
    ("GET", f"/api/v1/qualifications/{FAKE_UUID}", "qualification:view", None),
    ("GET", "/api/v1/qualifications/expiring", "qualification:view", None),
    ("GET", "/api/v1/qualifications/alerts", "qualification:view", None),
    ("PATCH", f"/api/v1/qualifications/{FAKE_UUID}", "qualification:update", {"name": "updated"}),
    ("DELETE", f"/api/v1/qualifications/{FAKE_UUID}", "qualification:delete", None),
    ("POST", f"/api/v1/qualifications/{FAKE_UUID}/extract", "qualification:extract", None),
    ("POST", f"/api/v1/qualifications/{FAKE_UUID}/upload-certificate", "qualification:update", None),
    # 产品中心
    ("GET", "/api/v1/products", "product:view", None),
    ("POST", "/api/v1/products", "product:create", {"name": "测试产品"}),
    ("GET", "/api/v1/products/categories", "product:view", None),
    ("POST", "/api/v1/products/categories", "product:create", {"name": "测试分类"}),
    ("GET", f"/api/v1/products/{FAKE_UUID}", "product:view", None),
    ("POST", f"/api/v1/products/{FAKE_UUID}/publish", "product:publish", None),
    ("POST", "/api/v1/products/search", "product:view", {"query": "test"}),
    # 反馈
    ("GET", "/api/v1/feedback/stats", "feedback:view", None),
    ("POST", "/api/v1/feedback", "feedback:create", {"target_type": "comparison", "target_id": FAKE_UUID, "original_verdict": "compliant", "corrected_verdict": "non_compliant", "correction_reason": "test"}),
    ("POST", "/api/v1/feedback/recall", "feedback:view", {"target_type": "comparison", "context_text": "test"}),
    # AI 助手
    ("GET", "/api/v1/assistant/conversations", "assistant:view_history", None),
    ("POST", "/api/v1/assistant/chat", "assistant:chat", {"query": "test"}),
]

# ---- 角色-权限矩阵（来自 base_data.py DEFAULT_ROLE_PERMISSIONS）----
ROLE_PERMISSIONS = {
    "presales": {
        "project:view", "project:create", "project:update",
        "document:view", "document:upload", "document:parse",
        "comparison:view", "comparison:create", "comparison:export",
        "product:view", "knowledge:view", "general_knowledge:view",
        "qualification:view", "assistant:chat", "assistant:view_history",
        "contract:view",
    },
    "legal": {
        "project:view", "document:view",
        "contract:view", "contract:create", "contract:review", "contract:export",
        "comparison:view", "qualification:view", "knowledge:view", "general_knowledge:view",
        "feedback:view", "feedback:create", "assistant:chat", "assistant:view_history",
    },
    "procurement": {
        "project:view", "document:view", "document:upload",
        "contract:view", "contract:create",
        "qualification:view", "qualification:create", "qualification:update",
        "product:view", "product:create", "product:update", "feedback:view",
        "assistant:chat",
    },
    "pm": {
        "project:view", "project:create", "project:update",
        "document:view", "document:upload", "document:parse",
        "comparison:view", "comparison:create", "comparison:export",
        "contract:view", "contract:review", "product:view", "qualification:view",
        "knowledge:view", "general_knowledge:view",
        "feedback:view", "feedback:create", "assistant:chat", "assistant:view_history",
    },
    "compliance": {
        "project:view", "document:view",
        "contract:view", "contract:review", "contract:export",
        "comparison:view", "comparison:export", "qualification:view",
        "knowledge:view", "general_knowledge:view",
        "feedback:view", "feedback:create", "assistant:chat",
    },
}


# ============ 测试 1：未认证访问 → 401 ============
@pytest.mark.parametrize(
    "method, path, perm, body",
    ENDPOINTS,
    ids=[f"{e[0]}_{e[1]}" for e in ENDPOINTS],
)
async def test_unauthenticated_returns_401(client, method, path, perm, body):
    """未认证访问所有受保护端点应返回 401"""
    resp = await client.request(method, path, json=body) if body else await client.request(method, path)
    assert resp.status_code == 401, f"未认证访问 {method} {path} 期望 401，实际 {resp.status_code}"


# ============ 测试 2：admin 访问所有端点 → 非 401/403 ============
@pytest.mark.parametrize(
    "method, path, perm, body",
    ENDPOINTS,
    ids=[f"admin_{e[0]}_{e[1]}" for e in ENDPOINTS],
)
async def test_admin_no_403(client, admin_token, method, path, perm, body):
    """admin 访问所有端点不应返回 401/403"""
    headers = {"Authorization": f"Bearer {admin_token['token']}"}
    resp = await client.request(method, path, json=body, headers=headers) if body else await client.request(method, path, headers=headers)
    assert resp.status_code not in (401, 403), f"admin 访问 {method} {path} 收到 {resp.status_code}"


# ============ 测试 3：各角色无权限端点 → 403 ============
def _generate_forbidden_cases():
    """生成各角色无权限的端点用例"""
    cases = []
    for role_code, perms in ROLE_PERMISSIONS.items():
        for method, path, required_perm, body in ENDPOINTS:
            if required_perm not in perms:
                cases.append((role_code, method, path, required_perm, body))
    return cases


@pytest.mark.parametrize(
    "role_code, method, path, required_perm, body",
    _generate_forbidden_cases(),
    ids=[f"{c[0]}_forbidden_{c[1]}_{c[2]}" for c in _generate_forbidden_cases()],
)
async def test_role_forbidden_returns_403(client, role_tokens, role_code, method, path, required_perm, body):
    """角色访问无权限端点应返回 403"""
    token = role_tokens[role_code]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.request(method, path, json=body, headers=headers) if body else await client.request(method, path, headers=headers)
    assert resp.status_code == 403, f"{role_code} 访问 {method} {path}（需 {required_perm}）期望 403，实际 {resp.status_code}"


# ============ 测试 4：各角色有权限端点 → 非 403 ============
def _generate_allowed_cases():
    """生成各角色有权限的端点用例"""
    cases = []
    for role_code, perms in ROLE_PERMISSIONS.items():
        for method, path, required_perm, body in ENDPOINTS:
            if required_perm in perms:
                cases.append((role_code, method, path, required_perm, body))
    return cases


@pytest.mark.parametrize(
    "role_code, method, path, required_perm, body",
    _generate_allowed_cases(),
    ids=[f"{c[0]}_allowed_{c[1]}_{c[2]}" for c in _generate_allowed_cases()],
)
async def test_role_allowed_not_403(client, role_tokens, role_code, method, path, required_perm, body):
    """角色访问有权限端点不应返回 403（401/422/404/500 等均可接受）"""
    token = role_tokens[role_code]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.request(method, path, json=body, headers=headers) if body else await client.request(method, path, headers=headers)
    assert resp.status_code != 403, f"{role_code} 访问有权限端点 {method} {path}（{required_perm}）收到 403"


# ============ 测试 5：GET 列表权限隔离 ============
async def test_presales_cannot_view_users(client, role_tokens):
    """售前角色不能访问用户管理列表"""
    token = role_tokens["presales"]["token"]
    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_legal_cannot_create_project(client, role_tokens):
    """法务角色不能创建项目"""
    token = role_tokens["legal"]["token"]
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "test", "code": "test_code_x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_procurement_can_view_users_not_create(client, role_tokens):
    """采购角色：不能查看用户（user:view 不在权限内）"""
    token = role_tokens["procurement"]["token"]
    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_compliance_cannot_create_qualification(client, role_tokens):
    """合规角色不能创建资质"""
    token = role_tokens["compliance"]["token"]
    resp = await client.post(
        "/api/v1/qualifications",
        json={"name": "test", "qual_type": "ISO"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ============ 测试 6：POST/PUT/DELETE 权限隔离 ============
async def test_pm_cannot_delete_user(client, role_tokens):
    """PM 角色不能删除用户"""
    token = role_tokens["pm"]["token"]
    resp = await client.delete(
        f"/api/v1/users/{FAKE_UUID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_presales_cannot_assign_permissions(client, role_tokens):
    """售前角色不能分配角色权限"""
    token = role_tokens["presales"]["token"]
    resp = await client.put(
        f"/api/v1/roles/{FAKE_UUID}/permissions",
        json={"permission_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_legal_cannot_extract_qualification(client, role_tokens):
    """法务角色不能触发资质字段提取"""
    token = role_tokens["legal"]["token"]
    resp = await client.post(
        f"/api/v1/qualifications/{FAKE_UUID}/extract",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_procurement_can_create_qualification(client, role_tokens):
    """采购角色可以创建资质（有 qualification:create 权限）"""
    token = role_tokens["procurement"]["token"]
    resp = await client.post(
        "/api/v1/qualifications",
        json={"name": f"test_qual_{uuid.uuid4().hex[:6]}", "qual_type": "ISO9001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 期望非 403（201 或 422 等均可）
    assert resp.status_code != 403, f"procurement 创建资质收到 403：{resp.text}"


async def test_admin_can_view_users(client, admin_token):
    """admin 可以查看用户列表"""
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200


async def test_admin_can_view_audit_logs(client, admin_token):
    """admin 可以查看审计日志"""
    resp = await client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200


async def test_admin_can_view_permissions(client, admin_token):
    """admin 可以查看权限点列表"""
    resp = await client.get(
        "/api/v1/permissions",
        headers={"Authorization": f"Bearer {admin_token['token']}"},
    )
    assert resp.status_code == 200


# ============ 测试 7：无效 token ============
async def test_invalid_token_returns_401(client):
    """无效 token 返回 401"""
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401


async def test_expired_token_returns_401(client):
    """过期 token 返回 401"""
    from app.core.security import create_access_token
    # 构造一个已过期的 token
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.core.config import settings
    expire = datetime.now(timezone.utc) - timedelta(minutes=1)
    payload = {"sub": str(uuid.uuid4()), "exp": expire, "type": "access", "username": "expired", "is_admin": False}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_no_auth_header_returns_401(client):
    """无 Authorization 头返回 401"""
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


async def test_malformed_auth_header_returns_401(client):
    """格式错误的 Authorization 头返回 401"""
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": "NotBearer abc"},
    )
    assert resp.status_code == 401
