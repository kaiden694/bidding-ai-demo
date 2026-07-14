"""所有 ORM 模型汇总导入（确保 metadata 注册完整）"""
from app.models.base import (
    UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, CreatedByMixin,
)
from app.models.user import Organization, Permission, Role, User
from app.models.project import Project, ProjectStatus, Milestone
from app.models.project_state import ProjectStatusTransition, ProjectStatusRule
from app.models.document import (
    Document, DocumentType, DocumentChunk, DocParseStatus,
    KnowledgeBase, KnowledgeChunk,
)
from app.models.contract import Contract, ContractRisk, RiskLevel, ReviewStatus
from app.models.qualification import Qualification, QualificationType
from app.models.comparison import ComparisonTask, ComparisonResult, ComparisonVerdict
from app.models.audit import AuditLog
from app.models.product import (
    ProductCategory, Product, ProductChunk,
)
from app.models.general_knowledge import (
    GeneralKnowledgeBase, GeneralKnowledgeChunk, GeneralDocCategory,
)
from app.models.assistant import (
    AssistantConversation, AssistantMessage, AssistantScope,
)
from app.models.feedback import (
    FeedbackRecord, FeedbackTargetType, QualificationAlert,
)
from app.models.llm_provider import LLMProvider, LLMUsageLog
from app.models.embedding_provider import EmbeddingProvider
from app.models.ocr_provider import OCRProvider, OCRProviderType
from app.models.company import Company, CompanyType
from app.models.notification import (
    Notification, NotificationType, TodoTask, TodoStatus, EmailLog,
)
from app.models.todo_rule import TodoRule
from app.models.comment import (
    Comment, CommentEntityType, Mention,
)
from app.models.bid_draft import (
    BidTemplate, BidTemplateCategory, BidDraft, BidDraftStatus,
)
from app.models.sso import SSOConfig, UserSSOLink
from app.models.evidence import (
    EvidenceSourceFile as SourceFile,
    EvidenceDocumentPage as DocumentPage,
    EvidenceExtractionRun as ExtractionRun,
    EvidenceSpan,
)
from app.models.expert_knowledge import ExpertRule, ExpertMemory, ExpertScope

__all__ = [
    "UUIDPKMixin", "TimestampMixin", "SoftDeleteMixin", "TenantMixin", "CreatedByMixin",
    "Organization", "Permission", "Role", "User",
    "Project", "ProjectStatus", "Milestone",
    "ProjectStatusTransition", "ProjectStatusRule",
    "Document", "DocumentType", "DocumentChunk", "DocParseStatus",
    "KnowledgeBase", "KnowledgeChunk",
    "Contract", "ContractRisk", "RiskLevel", "ReviewStatus",
    "Qualification", "QualificationType",
    "ComparisonTask", "ComparisonResult", "ComparisonVerdict",
    "AuditLog",
    "ProductCategory", "Product", "ProductChunk",
    "GeneralKnowledgeBase", "GeneralKnowledgeChunk", "GeneralDocCategory",
    "AssistantConversation", "AssistantMessage", "AssistantScope",
    "FeedbackRecord", "FeedbackTargetType", "QualificationAlert",
    "LLMProvider", "LLMUsageLog",
    "EmbeddingProvider",
    "OCRProvider", "OCRProviderType",
    "Company", "CompanyType",
    "Notification", "NotificationType", "TodoTask", "TodoStatus", "EmailLog",
    "TodoRule",
    "Comment", "CommentEntityType", "Mention",
    "BidTemplate", "BidTemplateCategory", "BidDraft", "BidDraftStatus",
    "SSOConfig", "UserSSOLink",
    "SourceFile", "DocumentPage", "ExtractionRun", "EvidenceSpan",
    "ExpertRule", "ExpertMemory", "ExpertScope",
]
