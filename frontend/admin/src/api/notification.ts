/**
 * 通知中心 API 封装：对应后端 /api/v1/notifications/*
 *
 * 端点：
 *  - GET  /notifications               通知列表（?is_read=&limit=&offset=）
 *  - GET  /notifications/unread-count    未读数
 *  - POST /notifications/{id}/read      单条标记已读
 *  - POST /notifications/read-all       全部标记已读
 */
import { request } from "@/utils/request";
import type { NotificationItem } from "@/types";

/** 通知列表查询参数 */
export interface ListNotificationsParams {
  is_read?: boolean;
  limit?: number;
  offset?: number;
}

/** 通知列表 */
export function getNotifications(params?: ListNotificationsParams) {
  return request.get<NotificationItem[]>(`/notifications`, { params });
}

/** 未读数 */
export function getUnreadCount() {
  return request.get<{ count: number }>(`/notifications/unread-count`);
}

/** 标记单条已读 */
export function markRead(id: string) {
  return request.post<{ message: string }>(`/notifications/${id}/read`);
}

/** 全部标记已读 */
export function markAllRead() {
  return request.post<{ message: string }>(`/notifications/read-all`);
}
