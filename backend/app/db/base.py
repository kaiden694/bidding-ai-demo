"""模型聚合：导入所有模型以注册到 Base.metadata（供 init_db / Alembic 使用）"""
from app.models import (  # noqa: F401
    Organization, Permission, Role, User,
    Project, ProjectStatus, Milestone,
    ProjectStatusTransition, ProjectStatusRule,
    Document, DocumentType, DocumentChunk, DocParseStatus,
    KnowledgeBase, KnowledgeChunk,
    Contract, ContractRisk, RiskLevel, ReviewStatus,
    Qualification, QualificationType,
    ComparisonTask, ComparisonResult, ComparisonVerdict,
    AuditLog,
    ProductCategory, Product, ProductChunk,
    GeneralKnowledgeBase, GeneralKnowledgeChunk, GeneralDocCategory,
    AssistantConversation, AssistantMessage, AssistantScope,
    FeedbackRecord, QualificationAlert,
)
