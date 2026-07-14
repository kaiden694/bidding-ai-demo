/**
 * 标书起草 API 封装：对应后端 /api/v1/bid-templates/* 与 /api/v1/projects/{id}/bid-draft
 *
 * 端点：
 *  模板：
 *   - GET  /bid-templates            模板列表（?category=）
 *   - POST /bid-templates            创建模板
 *   - DELETE /bid-templates/{id}     删除模板
 *   - POST /bid-templates/{id}/fill  模板填充（变量替换）
 *  草稿：
 *   - GET  /projects/{id}/bid-draft           获取草稿
 *   - POST /projects/{id}/bid-draft           创建草稿
 *   - PUT  /projects/{id}/bid-draft           更新草稿
 *   - POST /projects/{id}/bid-draft/generate  AI 生成章节
 */
import { request } from "@/utils/request";
import type {
  BidTemplate,
  BidDraft,
  GenerateSectionPayload,
} from "@/types";

/** 模板列表查询参数 */
export interface ListTemplatesParams {
  category?: string;
}

/** 模板列表 */
export function getBidTemplates(params?: ListTemplatesParams) {
  return request.get<BidTemplate[]>(`/bid-templates`, { params });
}

/** 创建模板 */
export function createBidTemplate(data: Partial<BidTemplate>) {
  return request.post<BidTemplate>(`/bid-templates`, data);
}

/** 删除模板 */
export function deleteBidTemplate(id: string) {
  return request.delete<{ message: string }>(`/bid-templates/${id}`);
}

/** 模板变量填充 */
export function fillTemplate(id: string, variables: Record<string, string>) {
  return request.post<{ content: string }>(`/bid-templates/${id}/fill`, {
    variables,
  });
}

/** 获取项目草稿 */
export function getBidDraft(projectId: string) {
  return request.get<BidDraft>(`/projects/${projectId}/bid-draft`);
}

/** 创建草稿 */
export function createBidDraft(projectId: string, data: Partial<BidDraft>) {
  return request.post<BidDraft>(`/projects/${projectId}/bid-draft`, data);
}

/** 更新草稿 */
export function updateBidDraft(projectId: string, data: Partial<BidDraft>) {
  return request.put<BidDraft>(`/projects/${projectId}/bid-draft`, data);
}

/** AI 生成章节 */
export function generateSection(projectId: string, data: GenerateSectionPayload) {
  return request.post<{ content: string }>(
    `/projects/${projectId}/bid-draft/generate`,
    data,
  );
}
