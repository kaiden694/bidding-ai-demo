/**
 * 系统管理 API 封装：对应后端 /api/v1/{users,roles,permissions,organizations,audit-logs}/*
 *
 * 后端响应拦截器已返回 response.data，因此 request.get<T>(...) 直接得到 T。
 * 401/403 由拦截器统一处理，调用方无需再 catch 这些状态码。
 */
import { request } from "@/utils/request";
import type {
  UserOut,
  RoleOut,
  OrganizationOut,
  OrganizationTreeNode,
  RolePermissionItem,
  AuditLogItem,
  BatchImportResult,
  Permission,
  PermissionGroup,
} from "@/types";

// ===================== 用户 =====================

/** 用户列表参数 */
export interface ListUsersParams {
  keyword?: string;
  skip?: number;
  limit?: number;
}

/** 创建用户请求体（后端 UserCreate）*/
export interface UserCreatePayload {
  username: string;
  password: string;
  email?: string | null;
  phone?: string | null;
  full_name?: string | null;
  role_id?: string | null;
  organization_id?: string | null;
}

/** 更新用户请求体（后端 UserUpdate）*/
export interface UserUpdatePayload {
  email?: string | null;
  phone?: string | null;
  full_name?: string | null;
  role_id?: string | null;
  organization_id?: string | null;
  is_active?: boolean;
}

/** 用户列表（分页 + 关键字搜索） */
export function listUsers(params?: ListUsersParams) {
  return request.get<UserOut[]>("/users", { params });
}

/** 用户详情 */
export function getUser(userId: string) {
  return request.get<UserOut>(`/users/${userId}`);
}

/** 创建用户 */
export function createUser(data: UserCreatePayload) {
  return request.post<UserOut>("/users", data);
}

/** 更新用户 */
export function updateUser(userId: string, data: UserUpdatePayload) {
  return request.put<UserOut>(`/users/${userId}`, data);
}

/** 禁用用户（软删除） */
export function disableUser(userId: string) {
  return request.delete<{ message: string }>(`/users/${userId}`);
}

/** 重置密码 */
export function resetPassword(userId: string, newPassword: string) {
  return request.post<{ message: string }>(`/users/${userId}/reset-password`, {
    new_password: newPassword,
  });
}

/** CSV 批量导入用户（CSV 表头：username,password,email,phone,full_name） */
export function batchImportUsers(formData: FormData) {
  return request.upload<BatchImportResult>("/users/batch-import", formData);
}

// ===================== 角色 =====================

/** 创建角色请求体（后端 RoleCreate）*/
export interface RoleCreatePayload {
  code: string;
  name: string;
  description?: string | null;
}

/** 更新角色请求体（后端 RoleUpdate，系统角色不允许改 code）*/
export interface RoleUpdatePayload {
  name?: string;
  description?: string | null;
}

/** 角色列表 */
export function listRoles() {
  return request.get<RoleOut[]>("/roles");
}

/** 创建角色 */
export function createRole(data: RoleCreatePayload) {
  return request.post<RoleOut>("/roles", data);
}

/** 更新角色 */
export function updateRole(roleId: string, data: RoleUpdatePayload) {
  return request.put<RoleOut>(`/roles/${roleId}`, data);
}

/** 删除角色（系统内置角色不可删除） */
export function deleteRole(roleId: string) {
  return request.delete<{ message: string }>(`/roles/${roleId}`);
}

/** 获取角色已分配的权限点列表 */
export function getRolePermissions(roleId: string) {
  return request.get<RolePermissionItem[]>(`/roles/${roleId}/permissions`);
}

/** 分配权限给角色（覆盖式：先清空再写入） */
export function assignRolePermissions(roleId: string, permissionIds: string[]) {
  return request.put<{ message: string }>(`/roles/${roleId}/permissions`, {
    permission_ids: permissionIds,
  });
}

// ===================== 权限 =====================

/** 所有权限点列表 */
export function listPermissions() {
  return request.get<Permission[]>("/permissions");
}

/** 按模块分组的权限点 */
export function listPermissionsGrouped() {
  return request.get<PermissionGroup[]>("/permissions/grouped");
}

// ===================== 组织 =====================

/** 创建组织请求体（后端 OrganizationCreate）*/
export interface OrganizationCreatePayload {
  name: string;
  code: string;
  parent_id?: string | null;
  sort_order?: number;
  description?: string | null;
}

/** 更新组织请求体（后端 OrganizationUpdate，支持移动 parent_id）*/
export interface OrganizationUpdatePayload {
  name?: string;
  code?: string;
  parent_id?: string | null;
  sort_order?: number;
}

/** 组织平铺列表 */
export function listOrganizations() {
  return request.get<OrganizationOut[]>("/organizations");
}

/** 组织树 */
export function getOrganizationTree() {
  return request.get<OrganizationTreeNode[]>("/organizations/tree");
}

/** 创建组织 */
export function createOrganization(data: OrganizationCreatePayload) {
  return request.post<OrganizationOut>("/organizations", data);
}

/** 更新组织（含移动 parent_id） */
export function updateOrganization(orgId: string, data: OrganizationUpdatePayload) {
  return request.put<OrganizationOut>(`/organizations/${orgId}`, data);
}

/** 删除组织（软删除） */
export function deleteOrganization(orgId: string) {
  return request.delete<{ message: string }>(`/organizations/${orgId}`);
}

// ===================== 审计日志 =====================

/** 审计日志查询参数 */
export interface ListAuditLogsParams {
  user_id?: string;
  action?: string;
  resource?: string;
  resource_id?: string;
  start?: string;
  end?: string;
  skip?: number;
  limit?: number;
}

/** 审计日志列表（分页 + 多维筛选） */
export function listAuditLogs(params?: ListAuditLogsParams) {
  return request.get<AuditLogItem[]>("/audit-logs", { params });
}

/**
 * 导出审计日志 CSV（后端返回 text/csv 流）。
 * 通过 axios 以 blob 方式获取（携带 JWT），再由调用方触发下载。
 */
export function exportAuditLogs(params: {
  user_id?: string;
  action?: string;
  resource?: string;
  start?: string;
  end?: string;
}) {
  return request.get<Blob>("/audit-logs/export", {
    params,
    responseType: "blob",
  });
}
