"""默认种子数据：6 个系统角色 + 权限点清单 + 角色-权限默认分配"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ProjectStatus
from app.models.project_state import ProjectStatusRule
from app.models.todo_rule import TodoRule
from app.models.user import Role, Permission, role_permission

# ---------- 默认角色 ----------
DEFAULT_ROLES = [
    ("presales", "售前/招投标专员", "项目立项、标书起草、参数响应", True),
    ("legal", "法务", "合同条款审查、风险确认", True),
    ("procurement", "采购", "供应商资质管理、采购合同", True),
    ("pm", "项目经理", "项目全流程跟踪、里程碑", True),
    ("compliance", "合规审核", "终审、合规签批", True),
    ("admin", "系统管理员", "系统配置、用户/权限/模型管理", True),
]


# ---------- 权限点清单 ----------
# 格式：(code, name, module, description)
DEFAULT_PERMISSIONS = [
    # 项目
    ("project:view", "查看项目", "project", "查看招投标项目列表与详情"),
    ("project:create", "创建项目", "project", "创建新招投标项目"),
    ("project:update", "编辑项目", "project", "修改项目信息"),
    ("project:delete", "删除项目", "project", "删除项目（软删除）"),
    ("project:transition", "项目状态流转", "project", "变更项目状态"),
    ("project:manage_rules", "管理状态规则", "project", "配置状态转移矩阵"),
    # 文档
    ("document:view", "查看文档", "document", "查看文档列表与详情"),
    ("document:upload", "上传文档", "document", "上传招标/规格/合同等文档"),
    ("document:parse", "解析文档", "document", "触发文档解析与向量化"),
    ("document:delete", "删除文档", "document", "删除文档"),
    # 合同
    ("contract:view", "查看合同", "contract", "查看合同列表与详情"),
    ("contract:create", "创建合同", "contract", "创建合同记录"),
    ("contract:review", "合同风险审查", "contract", "触发合同风险扫描"),
    ("contract:export", "导出风险报告", "contract", "导出合同风险报告 Docx"),
    # 参数偏离比对
    ("comparison:view", "查看比对结果", "comparison", "查看参数偏离比对任务与结果"),
    ("comparison:create", "创建比对任务", "comparison", "创建参数偏离比对任务"),
    ("comparison:export", "导出偏离报告", "comparison", "导出偏离报告 Docx"),
    # 产品中心
    ("product:view", "查看产品", "product", "查看产品列表与详情"),
    ("product:create", "创建产品", "product", "创建新产品"),
    ("product:update", "编辑产品", "product", "修改产品信息"),
    ("product:delete", "删除产品", "product", "删除产品"),
    ("product:publish", "上架产品", "product", "上架/下架产品"),
    # 知识库
    ("knowledge:view", "查看知识库", "knowledge", "查看历史知识库与通用知识库"),
    ("knowledge:create", "创建知识库", "knowledge", "创建知识库"),
    ("knowledge:import", "批量导入", "knowledge", "批量导入知识库文档"),
    ("knowledge:reindex", "索引重建", "knowledge", "重建知识库向量索引"),
    ("knowledge:delete", "删除知识库", "knowledge", "删除知识库"),
    # 通用知识库
    ("general_knowledge:view", "查看通用知识库", "general_knowledge", "查看企业资料/政策法规"),
    ("general_knowledge:create", "创建通用知识库", "general_knowledge", "创建通用知识库条目"),
    ("general_knowledge:import", "批量导入", "general_knowledge", "批量导入通用知识库文档"),
    ("general_knowledge:delete", "删除通用知识库", "general_knowledge", "删除通用知识库"),
    # 资质
    ("qualification:view", "查看资质", "qualification", "查看资质台账"),
    ("qualification:create", "创建资质", "qualification", "创建资质记录"),
    ("qualification:update", "编辑资质", "qualification", "修改资质信息"),
    ("qualification:delete", "删除资质", "qualification", "删除资质记录"),
    ("qualification:extract", "字段提取", "qualification", "OCR+LLM 提取资质字段"),
    # 语义反馈闭环（专家修正 + 召回）
    ("feedback:view", "查看反馈", "feedback", "查看反馈记录与统计"),
    ("feedback:create", "记录修正", "feedback", "记录专家修正并进入召回库"),
    # AI 助手
    ("assistant:chat", "AI 助手问答", "assistant", "调用 AI 助手问答"),
    ("assistant:view_history", "查看会话历史", "assistant", "查看 AI 助手会话历史"),
    # 用户管理（管理员专属）
    ("user:view", "查看用户", "user", "查看用户列表"),
    ("user:create", "创建用户", "user", "创建新用户"),
    ("user:update", "编辑用户", "user", "修改用户信息"),
    ("user:delete", "禁用用户", "user", "禁用/启用用户"),
    ("user:reset_password", "重置密码", "user", "重置用户密码"),
    # 角色管理（管理员专属）
    ("role:view", "查看角色", "role", "查看角色列表"),
    ("role:create", "创建角色", "role", "创建新角色"),
    ("role:update", "编辑角色", "role", "修改角色信息"),
    ("role:assign_permissions", "分配权限", "role", "为角色分配权限点"),
    # 组织管理（管理员专属）
    ("organization:view", "查看组织", "organization", "查看组织树"),
    ("organization:create", "创建组织", "organization", "创建组织节点"),
    ("organization:update", "编辑组织", "organization", "修改组织节点"),
    ("organization:delete", "删除组织", "organization", "删除组织节点"),
    # 审计日志（管理员专属）
    ("audit_log:view", "查看审计日志", "audit_log", "查看操作审计日志"),
    ("audit_log:export", "导出审计日志", "audit_log", "导出审计日志 CSV/Excel"),
    # 系统配置（管理员专属）
    ("system:config", "系统配置", "system", "查看/修改系统配置"),
    # 站内信 + 待办（Phase 3 T2）
    ("notification:view", "查看通知", "notification", "查看站内信通知"),
    ("todo:create", "管理待办", "todo", "创建/更新待办任务"),
    ("todo:view", "查看待办", "todo", "查看待办任务列表"),
    # 协作评论（Phase 3 T6）
    ("comment:create", "发表评论", "comment", "发表协作评论"),
    ("comment:view", "查看评论", "comment", "查看项目评论"),
    ("comment:delete", "删除评论", "comment", "删除评论（作者或管理员）"),
    # 标书起草辅助（Phase 3 T4：模板管理 + AI 生成草稿章节 + 模板变量填充）
    ("bid:view", "查看标书", "bid", "查看标书模板和草稿"),
    ("bid:create", "管理标书", "bid", "创建/编辑标书模板和草稿"),
]


# ---------- 角色-权限默认分配 ----------
# 格式：(role_code, [permission_codes])
# admin 角色在 casbin.py 中自动拥有所有权限，这里不重复分配
DEFAULT_ROLE_PERMISSIONS = {
    "presales": [
        "project:view", "project:create", "project:update", "project:transition",
        "document:view", "document:upload", "document:parse",
        "comparison:view", "comparison:create", "comparison:export",
        "product:view",
        "knowledge:view",
        "general_knowledge:view",
        "qualification:view",
        "assistant:chat", "assistant:view_history",
        "contract:view",
        "notification:view", "todo:view", "todo:create",
        "comment:create", "comment:view",
        "bid:view", "bid:create",
    ],
    "legal": [
        "project:view",
        "document:view",
        "contract:view", "contract:create", "contract:review", "contract:export",
        "comparison:view",
        "qualification:view",
        "knowledge:view",
        "general_knowledge:view",
        "feedback:view", "feedback:create",
        "assistant:chat", "assistant:view_history",
        "notification:view", "todo:view", "todo:create",
        "comment:create", "comment:view",
    ],
    "procurement": [
        "project:view",
        "document:view", "document:upload",
        "contract:view", "contract:create",
        "qualification:view", "qualification:create", "qualification:update",
        "product:view", "product:create", "product:update",
        "feedback:view",
        "assistant:chat",
        "notification:view", "todo:view", "todo:create",
        "comment:create", "comment:view",
    ],
    "pm": [
        "project:view", "project:create", "project:update", "project:transition",
        "document:view", "document:upload", "document:parse",
        "comparison:view", "comparison:create", "comparison:export",
        "contract:view", "contract:review",
        "product:view",
        "qualification:view",
        "knowledge:view",
        "general_knowledge:view",
        "feedback:view", "feedback:create",
        "assistant:chat", "assistant:view_history",
        "notification:view", "todo:view", "todo:create",
        "comment:create", "comment:view",
        "bid:view", "bid:create",
    ],
    "compliance": [
        "project:view",
        "document:view",
        "contract:view", "contract:review", "contract:export",
        "comparison:view", "comparison:export",
        "qualification:view",
        "knowledge:view",
        "general_knowledge:view",
        "feedback:view", "feedback:create",
        "assistant:chat",
        "notification:view", "todo:view", "todo:create",
        "comment:create", "comment:view",
    ],
    # admin 拥有所有权限（在 casbin.py 中实现）
}


# ---------- 默认状态转移矩阵 ----------
# 格式：from_status -> [允许的下一状态列表]
# 依据招投标 10 状态机（v1.2 §3）：筹备→立项→文件解析→方案规划→标书起草→内审→投递→评标→中标/落标→归档
DEFAULT_STATUS_RULES: dict[ProjectStatus, list[ProjectStatus]] = {
    ProjectStatus.PREPARATION: [ProjectStatus.APPROVED],
    ProjectStatus.APPROVED: [ProjectStatus.FILE_PARSING],
    ProjectStatus.FILE_PARSING: [ProjectStatus.PLAN_DESIGN],
    ProjectStatus.PLAN_DESIGN: [ProjectStatus.BID_DRAFTING],
    ProjectStatus.BID_DRAFTING: [ProjectStatus.INTERNAL_REVIEW],
    ProjectStatus.INTERNAL_REVIEW: [ProjectStatus.BID_DRAFTING, ProjectStatus.SUBMITTED],
    ProjectStatus.SUBMITTED: [ProjectStatus.EVALUATION],
    ProjectStatus.EVALUATION: [ProjectStatus.AWARDED, ProjectStatus.LOST],
    ProjectStatus.AWARDED: [ProjectStatus.ARCHIVED],
    ProjectStatus.LOST: [ProjectStatus.ARCHIVED],
    ProjectStatus.ARCHIVED: [],  # 终态
}


# ---------- 默认待办自动生成规则 ----------
# 格式：trigger_status -> (todo_title, todo_description, assignee_role, due_days)
# 触发状态用 ProjectStatus 枚举，落库时存其 value（字符串）
DEFAULT_TODO_RULES: dict[ProjectStatus, tuple] = {
    ProjectStatus.FILE_PARSING: ("完成文档解析", "解析招标文件/规格书，完成向量化入库", "presales", 1),
    ProjectStatus.PLAN_DESIGN: ("完成参数偏离比对", "对照规格书完成参数偏离比对并出具报告", "presales", 3),
    ProjectStatus.BID_DRAFTING: ("起草标书", "依据方案规划起草投标标书", "presales", 7),
    ProjectStatus.INTERNAL_REVIEW: ("完成内审", "法务/合规完成标书内审", "legal", 3),
    ProjectStatus.SUBMITTED: ("跟踪评标结果", "投递后跟踪评标进度与结果", "pm", 14),
    ProjectStatus.AWARDED: ("签订合同", "中标后推进合同签订", "legal", 7),
}


async def seed_default_roles(session: AsyncSession):
    """若无角色则插入默认角色（幂等）"""
    result = await session.execute(select(Role).limit(1))
    if result.scalars().first() is not None:
        return
    for code, name, desc, is_sys in DEFAULT_ROLES:
        session.add(Role(code=code, name=name, description=desc, is_system=is_sys))
    await session.commit()


async def seed_default_permissions(session: AsyncSession):
    """插入缺失的权限点（per-permission 幂等，支持增量补齐）"""
    existing = await session.execute(select(Permission.code))
    existing_codes = {row[0] for row in existing.all()}
    for code, name, module, desc in DEFAULT_PERMISSIONS:
        if code in existing_codes:
            continue
        session.add(Permission(code=code, name=name, module=module, description=desc))
    await session.commit()


async def seed_default_role_permissions(session: AsyncSession):
    """分配角色-权限（幂等：仅分配未关联的）"""
    # 查询所有角色与权限点
    roles = {r.code: r for r in (await session.execute(select(Role))).scalars().all()}
    perms = {p.code: p for p in (await session.execute(select(Permission))).scalars().all()}

    for role_code, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles.get(role_code)
        if not role:
            continue
        for perm_code in perm_codes:
            perm = perms.get(perm_code)
            if not perm:
                continue
            # 幂等检查：是否已存在关联
            existing = await session.execute(
                select(role_permission).where(
                    role_permission.c.role_id == role.id,
                    role_permission.c.permission_id == perm.id,
                )
            )
            if existing.first() is None:
                await session.execute(
                    role_permission.insert().values(role_id=role.id, permission_id=perm.id)
                )
    await session.commit()


async def seed_default_status_rules(session: AsyncSession):
    """插入默认状态转移矩阵（幂等：per-rule 幂等插入）

    已存在 (from_status, to_status) 的规则跳过，避免重复。
    缺失的规则补齐；不会删除/禁用用户手动配置的规则。
    """
    # 收集已存在的规则键
    existing = await session.execute(
        select(ProjectStatusRule.from_status, ProjectStatusRule.to_status)
    )
    existing_keys = {(row[0], row[1]) for row in existing.all()}

    for from_status, to_statuses in DEFAULT_STATUS_RULES.items():
        for to_status in to_statuses:
            key = (from_status, to_status)
            if key in existing_keys:
                continue
            session.add(
                ProjectStatusRule(
                    from_status=from_status,
                    to_status=to_status,
                    is_active=True,
                )
            )
    await session.commit()


async def seed_todo_rules(session: AsyncSession):
    """插入默认待办自动生成规则（幂等：per-rule 幂等插入）

    已存在 (trigger_status, todo_title) 的规则跳过，避免重复。
    缺失的规则补齐；不会删除/禁用用户手动配置的规则。
    """
    existing = await session.execute(
        select(TodoRule.trigger_status, TodoRule.todo_title)
    )
    existing_keys = {(row[0], row[1]) for row in existing.all()}

    for trigger_status, (title, desc, role, due_days) in DEFAULT_TODO_RULES.items():
        key = (trigger_status.value, title)
        if key in existing_keys:
            continue
        session.add(
            TodoRule(
                trigger_status=trigger_status.value,
                todo_title=title,
                todo_description=desc,
                assignee_role=role,
                due_days=due_days,
                is_active=True,
            )
        )
    await session.commit()


async def seed_all(session: AsyncSession):
    """一次性种子化所有默认数据"""
    await seed_default_roles(session)
    await seed_default_permissions(session)
    await seed_default_role_permissions(session)
    await seed_default_status_rules(session)
    await seed_todo_rules(session)
