// 公共类型定义

export interface UserInfo {
  id: string;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  is_admin: boolean;
  organization_id: string | null;
  role_codes: string[];
  permission_codes: string[];
}

export interface LoginRequest {
  username: string;
  password: string;
}

/** 后端 auth.py TokenResponse 实际响应字段 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user_id: string;
  username: string;
  full_name: string | null;
  is_admin: boolean;
  permissions: string[];
}

/** 后端 auth.py /auth/me UserInfoResponse 实际响应字段 */
export interface UserInfoResponse {
  user_id: string;
  username: string;
  full_name: string | null;
  is_admin: boolean;
  role_id: string | null;
  organization_id: string | null;
  permissions: string[];
}

export interface PageResult<T> {
  items: T[];
  total: number;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions?: Permission[];
}

export interface Permission {
  id: string;
  code: string;
  name: string;
  module: string;
  description: string | null;
}

export interface PermissionGroup {
  module: string;
  permissions: Permission[];
}

export interface Organization {
  id: string;
  name: string;
  code: string;
  parent_id: string | null;
  description: string | null;
  children?: Organization[];
}

export interface User {
  id: string;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  is_admin: boolean;
  organization_id: string | null;
  roles: Role[];
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  username: string | null;
  method: string;
  path: string;
  status_code: number;
  action: string | null;
  resource_type: string | null;
  resource_id: string | null;
  ip: string | null;
  user_agent: string | null;
  request_body: any;
  response_body: any;
  duration_ms: number | null;
  created_at: string;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  version: string;
  is_active: boolean;
  tags: any[] | null;
  metadata_json: any;
  created_at: string;
}

export interface GeneralKnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  category: string;
  visibility: string;
  tags: string[] | null;
  version: string;
  is_published: boolean;
  created_at: string;
}

export interface Qualification {
  id: string;
  name: string;
  qual_type: string;
  cert_number: string | null;
  issuer: string | null;
  scope: string | null;
  issue_date: string | null;
  expire_date: string | null;
  company_id: string | null;
  company_name: string | null;
  company_type: string | null;
  owner: string | null;
  supplier_name: string | null;
  document_id: string | null;
  is_valid: boolean;
  metadata_json: any;
  created_at: string;
}

export interface QualificationAlert {
  id: string;
  qualification_id: string;
  alert_date: string;
  expire_date: string | null;
  days_remaining: number;
  severity: string;
  notified: boolean;
}

export interface ProductCategory {
  id: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  children?: ProductCategory[];
}

export interface Product {
  id: string;
  name: string;
  model: string | null;
  brand: string | null;
  category_id: string | null;
  company_id: string | null;
  company_name: string | null;
  company_type: string | null;
  specs: ProductSpec[];
  is_published: boolean;
}

export interface ProductSpec {
  name: string;
  value: string;
  unit: string;
  tolerance: string;
  remarks: string;
}

export interface FeedbackRecord {
  id: string;
  target_type: string;
  target_id: string;
  context_key: string | null;
  context_text: string | null;
  original_verdict: string;
  corrected_verdict: string;
  correction_reason: string;
  corrected_by: string | null;
  is_active: boolean;
  metadata_json: any;
  created_at: string;
}

export interface FeedbackStats {
  total: number;
  active: number;
  by_target_type: Record<string, number>;
  correction_rate: number;
}

// ---- 知识库切块（T3.3） ----
export interface KnowledgeChunk {
  id: string;
  knowledge_base_id: string | null;
  title: string | null;
  content: string;
  category: string | null;
  tags: Record<string, any> | null;
  page_number: number | null;
  chunk_type: string | null;
  metadata_json: Record<string, any> | null;
}

/** 切块简要（filter 端点返回） */
export interface KnowledgeChunkBrief {
  id: string;
  chunk_index: number | null;
  title: string | null;
  content: string;
  page_number: number | null;
  section: string | null;
  metadata_json: Record<string, any> | null;
}

/** 导入/重建进度（KnowledgeService.get_import_status 返回） */
export interface ImportStatus {
  status: string; // pending / running / completed / failed
  total?: number;
  processed?: number;
  failed?: number;
  message?: string;
  [key: string]: any;
}

/** 语义检索结果项 */
export interface SearchResultItem {
  id?: string;
  name?: string;
  query?: string;
  content?: string;
  score?: number;
  [key: string]: any;
}

// ---- 产品中心（补全字段） ----
/** 产品分类（含 code） */
export interface ProductCategoryItem {
  id: string;
  name: string;
  code: string;
  parent_id: string | null;
  description: string | null;
  sort_order?: number;
  children?: ProductCategoryItem[];
}

/** 产品完整字段（对应后端 ProductOut） */
export interface ProductItem {
  id: string;
  name: string;
  code: string | null;
  category_id: string | null;
  model: string | null;
  brand: string | null;
  manufacturer: string | null;
  description: string | null;
  specs: ProductSpec[] | null;
  is_published: boolean;
  created_at: string;
}

// ---------- 系统管理（与后端 schema 严格对齐）----------
/** 用户管理列表/详情（后端 UserOut）*/
export interface UserOut {
  id: string;
  username: string;
  email: string | null;
  phone: string | null;
  full_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  role_id: string | null;
  organization_id: string | null;
  created_at: string;
}

/** 角色管理列表/详情（后端 RoleOut）*/
export interface RoleOut {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
}

/** 组织管理（后端 OrganizationOut）*/
export interface OrganizationOut {
  id: string;
  name: string;
  code: string;
  parent_id: string | null;
  sort_order: number;
  created_at: string;
}

/** 组织树节点（后端 OrganizationTreeNode）*/
export interface OrganizationTreeNode extends OrganizationOut {
  children: OrganizationTreeNode[];
}

/** 角色-权限关联项（后端 GET /roles/{id}/permissions 返回元素）*/
export interface RolePermissionItem {
  id: string;
  code: string;
  name: string;
  module: string;
}

/** 审计日志条目（后端 GET /audit-logs 返回元素）*/
export interface AuditLogItem {
  id: string;
  user_id: string | null;
  username: string | null;
  action: string | null;
  resource: string | null;
  resource_id: string | null;
  ip: string | null;
  user_agent: string | null;
  before_value: any;
  after_value: any;
  detail: string | null;
  status: string | null;
  created_at: string | null;
}

/** 用户批量导入结果（后端 POST /users/batch-import）*/
export interface BatchImportResult {
  success: number;
  failed: { username: string; reason: string }[];
}

// ===================== Phase 3：项目状态机 / 待办 / 通知 / 评论 / 标书 / LLM =====================

/** 项目状态机的 10 状态（与后端 ProjectStatus 枚举对齐） */
export const PROJECT_STATUSES = [
  "drafting",
  "qualified",
  "bid_preparing",
  "bid_submitted",
  "bid_evaluating",
  "awarded",
  "contract_signing",
  "contract_executing",
  "delivered",
  "closed",
] as const;

export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

/** 项目状态中文名映射 */
export const PROJECT_STATUS_LABELS: Record<string, string> = {
  drafting: "立项起草",
  qualified: "资格预审",
  bid_preparing: "标书编制",
  bid_submitted: "投标提交",
  bid_evaluating: "评标中",
  awarded: "中标",
  contract_signing: "合同签订",
  contract_executing: "合同执行",
  delivered: "交付验收",
  closed: "项目归档",
};

/** 项目状态标签类型映射（用于 el-tag 颜色） */
export const PROJECT_STATUS_TAG_TYPES: Record<
  string,
  "info" | "warning" | "primary" | "success" | "danger"
> = {
  drafting: "info",
  qualified: "warning",
  bid_preparing: "primary",
  bid_submitted: "primary",
  bid_evaluating: "warning",
  awarded: "success",
  contract_signing: "primary",
  contract_executing: "primary",
  delivered: "success",
  closed: "info",
};

/** 项目（对应后端 ProjectOut） */
export interface ProjectItem {
  id: string;
  name: string;
  code: string | null;
  status: string;
  client_name: string | null;
  deadline: string | null;
  owner: string | null;
  description: string | null;
  metadata_json: Record<string, any> | null;
  created_at: string;
}

/** 项目状态流转记录（对应后端 ProjectTransitionOut） */
export interface ProjectTransition {
  id: string;
  project_id: string;
  from_status: string | null;
  to_status: string;
  reason: string | null;
  operator_id: string | null;
  operator_name: string | null;
  created_at: string;
}

/** 状态规则（对应后端 StatusRuleOut） */
export interface ProjectStatusRule {
  id: string;
  from_status: string;
  to_status: string;
  role_required: string | null;
  reason_required: boolean;
  is_active: boolean;
}

/** 待办事项（对应后端 TodoOut） */
export interface TodoItem {
  id: string;
  project_id: string | null;
  title: string;
  description: string | null;
  status: string; // pending / in_progress / done
  priority: string | null;
  assignee: string | null;
  due_date: string | null;
  created_at: string;
  updated_at?: string | null;
}

/** 通知（对应后端 NotificationOut） */
export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  content: string | null;
  entity_type: string | null;
  entity_id: string | null;
  is_read: boolean;
  created_at: string;
}

/** 评论（对应后端 CommentOut） */
export interface CommentItem {
  id: string;
  project_id: string;
  entity_type: string;
  entity_id: string;
  content: string;
  parent_id: string | null;
  author_id: string;
  author_name: string | null;
  analysis: string | null;
  created_at: string;
  children?: CommentItem[];
}

/** 标书模板（对应后端 BidTemplateOut） */
export interface BidTemplate {
  id: string;
  name: string;
  category: string | null;
  content: string;
  variables: string[] | null;
  description: string | null;
  created_at: string;
}

/** 标书草稿（对应后端 BidDraftOut） */
export interface BidDraft {
  id: string;
  project_id: string;
  template_id: string | null;
  title: string | null;
  content: string;
  sections: BidDraftSection[] | null;
  status: string | null;
  created_at: string;
  updated_at?: string | null;
}

/** 草稿章节 */
export interface BidDraftSection {
  title: string;
  content: string;
  category?: string;
}

/** AI 生成章节请求体 */
export interface GenerateSectionPayload {
  section_title: string;
  category?: string;
  context?: string;
}

/** LLM 提供商（对应后端 LLMProviderOut，api_key 脱敏） */
export interface LLMProvider {
  id: string;
  name: string;
  base_url: string;
  api_key: string; // 脱敏后的 api_key（前4+后4）
  model: string;
  weight: number;
  is_healthy: boolean;
  is_active: boolean;
  last_check_at: string | null;
  consecutive_failures: number;
  circuit_breaker_until: string | null;
  metadata_json: Record<string, any> | null;
  created_at: string;
  updated_at: string | null;
}

/** LLM 运行时状态（含熔断信息，来自内存缓存） */
export interface LLMProviderStatus {
  id: string | null;
  name: string | null;
  base_url: string | null;
  model: string | null;
  weight: number;
  is_healthy: boolean;
  is_active: boolean;
  is_fallback: boolean;
  consecutive_failures: number;
  circuit_breaker_until: string | null;
  in_circuit_break: boolean;
}

/** LLM 健康检查结果 */
export interface LLMHealthCheckResult {
  id: string | null;
  name: string | null;
  is_healthy: boolean;
  error: string | null;
  last_check_at: string | null;
}

/** LLM 单个 provider 用量统计 */
export interface LLMProviderUsageStat {
  provider_name: string | null;
  model: string | null;
  total_calls: number;
  success_count: number;
  failure_count: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms: number;
}

/** LLM 用量统计聚合 */
export interface LLMUsageStats {
  days: number;
  total_calls: number;
  total_failures: number;
  total_tokens_in: number;
  total_tokens_out: number;
  providers: LLMProviderUsageStat[];
}

/** Embedding 提供商（对应后端 EmbeddingProviderOut，api_key 脱敏） */
export interface EmbeddingProvider {
  id: string;
  name: string;
  base_url: string;
  api_key: string; // 脱敏后的 api_key
  model: string;
  dim: number;
  is_active: boolean;
  is_healthy: boolean;
  last_check_at: string | null;
  consecutive_failures: number;
  metadata_json: Record<string, any> | null;
  created_at: string;
  updated_at: string | null;
}

/** Embedding 健康检查结果 */
export interface EmbeddingHealthCheckResult {
  id: string;
  name: string;
  is_healthy: boolean;
  dim: number | null;
  latency_ms: number | null;
  error: string | null;
  last_check_at: string | null;
}

/** Embedding 当前生效 provider 状态（内存缓存） */
export interface EmbeddingProviderStatus {
  id: string | null;
  name: string | null;
  base_url: string | null;
  model: string | null;
  dim: number;
  is_healthy: boolean;
  is_active: boolean;
  is_fallback: boolean;
  consecutive_failures: number;
}

/** OCR 服务类型枚举 */
export type OCRProviderType = "mineru" | "paddleocr" | "local" | "other";

/** OCR 提供商（对应后端 OCRProviderOut，api_key 脱敏） */
export interface OCRProvider {
  id: string;
  name: string;
  provider_type: OCRProviderType;
  base_url: string;
  api_key: string; // 脱敏后的 api_key
  model: string | null;
  is_active: boolean;
  is_healthy: boolean;
  last_check_at: string | null;
  consecutive_failures: number;
  metadata_json: Record<string, any> | null;
  created_at: string;
  updated_at: string | null;
}

/** OCR 健康检查结果 */
export interface OCRHealthCheckResult {
  id: string;
  name: string;
  provider_type: OCRProviderType;
  is_healthy: boolean;
  latency_ms: number | null;
  error: string | null;
  last_check_at: string | null;
}

/** OCR 当前生效 provider 状态 */
export interface OCRProviderStatus {
  is_active: boolean;
  id: string | null;
  name: string | null;
  provider_type: OCRProviderType | null;
  base_url: string | null;
  model: string | null;
  is_healthy: boolean;
  consecutive_failures: number;
}

/** 公司类型枚举 */
export type CompanyType = "self" | "partner" | "competitor" | "other";

/** 公司主数据 */
export interface Company {
  id: string;
  name: string;
  short_name: string | null;
  code: string | null;
  company_type: CompanyType;
  company_type_label: string | null;
  description: string | null;
  metadata_json: Record<string, any> | null;
  created_at: string;
  updated_at: string | null;
}

/** 公司精简信息（下拉选择器用） */
export interface CompanyBrief {
  id: string;
  name: string;
  short_name: string | null;
  company_type: CompanyType;
}
