/**
 * 协作评论 API 封装：对应后端
 *  /api/v1/projects/{projectId}/comments
 *  /api/v1/comments/{id}
 *
 * 端点：
 *  - GET  /projects/{projectId}/comments     评论列表（?entity_type=&entity_id=）
 *  - POST /projects/{projectId}/comments     创建评论
 *  - DELETE /comments/{id}                   删除评论
 *  - POST /comments/{id}/analyze            AI 分析评论
 */
import { request } from "@/utils/request";
import type { CommentItem } from "@/types";

/** 创建评论请求体 */
export interface CreateCommentPayload {
  entity_type: string;
  entity_id: string;
  content: string;
  parent_id?: string;
}

/** 获取评论列表 */
export function getComments(
  projectId: string,
  params?: { entity_type?: string; entity_id?: string },
) {
  return request.get<CommentItem[]>(`/projects/${projectId}/comments`, {
    params,
  });
}

/** 创建评论 */
export function createComment(projectId: string, data: CreateCommentPayload) {
  return request.post<CommentItem>(`/projects/${projectId}/comments`, data);
}

/** 删除评论 */
export function deleteComment(id: string) {
  return request.delete<{ message: string }>(`/comments/${id}`);
}

/** AI 分析评论（语义解析） */
export function analyzeComment(id: string) {
  return request.post<{ analysis: string }>(`/comments/${id}/analyze`);
}
