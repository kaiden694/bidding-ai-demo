/**
 * 项目管理 API 封装：对应后端 /api/v1/projects/* 与 /api/v1/admin/status-rules
 *
 * 主要端点：
 *  项目状态机：
 *   - POST /projects/{id}/transition        状态流转
 *   - GET  /projects/{id}/transitions        流转历史
 *   - GET  /projects/{id}/next-statuses      可用下一状态
 *   - GET  /projects/{id}/recommend-next-status  AI 推荐下一状态
 *  状态规则：
 *   - GET  /admin/status-rules               状态规则列表
 *   - PUT  /admin/status-rules               更新状态规则
 */
import { request } from "@/utils/request";
import type {
  ProjectItem,
  ProjectTransition,
  ProjectStatusRule,
} from "@/types";

// ===================== 项目状态机 =====================

/** 项目状态流转请求体 */
export interface TransitionPayload {
  to_status: string;
  reason?: string;
}

/** 流转项目状态 */
export function transitionProject(id: string, data: TransitionPayload) {
  return request.post<ProjectTransition>(`/projects/${id}/transition`, data);
}

/** 获取项目流转历史 */
export function getProjectTransitions(id: string) {
  return request.get<ProjectTransition[]>(`/projects/${id}/transitions`);
}

/** 获取项目可流转的下一状态 */
export function getProjectNextStatuses(id: string) {
  return request.get<string[]>(`/projects/${id}/next-statuses`);
}

/** AI 推荐下一状态 */
export function recommendNextStatus(id: string) {
  return request.get<{ recommended_status: string; reason?: string }>(
    `/projects/${id}/recommend-next-status`,
  );
}

// ===================== 项目列表 =====================

/** 项目列表查询参数 */
export interface ListProjectsParams {
  keyword?: string;
  status?: string;
  skip?: number;
  limit?: number;
}

/** 项目列表 */
export function listProjects(params?: ListProjectsParams) {
  return request.get<ProjectItem[]>(`/projects`, { params });
}

/** 项目详情 */
export function getProject(id: string) {
  return request.get<ProjectItem>(`/projects/${id}`);
}

// ===================== 状态规则 =====================

/** 获取状态规则 */
export function getStatusRules() {
  return request.get<ProjectStatusRule[]>(`/admin/status-rules`);
}

/** 更新状态规则 */
export function updateStatusRules(data: { rules: ProjectStatusRule[] }) {
  return request.put<{ message: string }>(`/admin/status-rules`, data);
}
