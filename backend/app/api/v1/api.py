"""API 路由聚合：所有 v1 端点统一挂载"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    documents, comparison, contracts, projects, knowledge,
    products, general_knowledge, assistant, auth,
    users, roles, organizations, permissions,
    audit_logs, qualifications, feedback, project_state,
    admin_llm, admin_embedding, admin_ocr, notifications, todos, comments, bid_drafts,
    sso, tender_parse, reports, company,
)

api_router = APIRouter()
# 认证
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 用户/角色/组织/权限管理（Phase 2）
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(roles.router, prefix="/roles", tags=["角色管理"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["组织管理"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["权限管理"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["审计日志"])

# 业务模块（前台/后台共用，按权限区分可见）
api_router.include_router(documents.router, prefix="/documents", tags=["文档管理"])
api_router.include_router(comparison.router, prefix="/comparison", tags=["参数偏离比对"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["合同风险扫描"])
api_router.include_router(projects.router, prefix="/projects", tags=["招投标项目"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["历史知识库"])

# 资质台账（T4.2 + T4.4：CRUD + 字段提取 + 上传证书 + 预警查询）
api_router.include_router(qualifications.router, prefix="/qualifications", tags=["资质台账"])

# 语义反馈闭环（T5.4：修正记录 + 召回统计）
api_router.include_router(feedback.router, prefix="/feedback", tags=["语义反馈闭环"])

# 产品中心（产品分类管理 + 比对选型来源）
api_router.include_router(products.router, prefix="/products", tags=["产品中心"])

# 通用知识库（企业资料/政策法规）
api_router.include_router(general_knowledge.router, prefix="/general-knowledge", tags=["通用知识库"])

# AI 助手（前台/后台共用）
api_router.include_router(assistant.router, prefix="/assistant", tags=["AI 助手"])

# 项目状态机（Phase 3 T1：状态流转 + 审计 + AI 辅助推荐）
api_router.include_router(project_state.router, prefix="", tags=["项目状态机"])

# 站内信 + 待办任务（Phase 3 T2：里程碑/待办/通知模块）
api_router.include_router(notifications.router, prefix="/notifications", tags=["站内信"])
api_router.include_router(todos.router, prefix="", tags=["待办任务"])

# 协作评论 + @提及 + AI 情感分析（Phase 3 T6）
api_router.include_router(comments.router, prefix="", tags=["协作评论"])

# LLM 提供商管理 + 健康检查 + 用量统计（Phase 3 T3：多 LLM 负载均衡）
api_router.include_router(admin_llm.router, prefix="/admin", tags=["LLM 管理"])

# Embedding 提供商管理 + 健康检查（OpenAI 兼容接口，运行时热加载）
api_router.include_router(admin_embedding.router, prefix="/admin", tags=["Embedding 管理"])

# OCR 提供商管理 + 健康检查（MinerU / PaddleOCR 等多种在线服务）
api_router.include_router(admin_ocr.router, prefix="/admin", tags=["OCR 管理"])

# 公司主数据管理（产品 / 资质的多公司维度：自营 / 合作 / 竞品）
api_router.include_router(company.router, prefix="/companies", tags=["公司管理"])

# 标书起草辅助（Phase 3 T4：模板管理 + AI 生成草稿章节 + 模板变量填充）
api_router.include_router(bid_drafts.router, prefix="", tags=["标书起草辅助"])

# SSO/OIDC 单点登录（Phase 3 T5：多 IdP 配置 + 自动创建用户 + 本地 JWT 签发）
api_router.include_router(sso.router, prefix="", tags=["SSO 单点登录"])

# 招标文档结构化解析（参考 lib-v0.2 bidding_service：TOC + 13 维度并行 LLM 提取）
api_router.include_router(tender_parse.router, prefix="", tags=["招标文档解析"])

# 多产品对比报告（横向 A4 Word 导出）
api_router.include_router(reports.router, prefix="", tags=["报告"])
