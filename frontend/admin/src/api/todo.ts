/**
 * 待办事项 API 封装：对应后端 /api/v1/todos/* 与 /api/v1/projects/{id}/todos
 *
 * 端点：
 *  - GET  /todos                待办列表（?status=&limit=&offset=）
 *  - POST /todos                创建待办
 *  - PUT  /todos/{id}           更新待办
 *  - GET  /projects/{id}/todos  项目下待办
 */
import { request } from "@/utils/request";
import type { TodoItem } from "@/types";

/** 待办列表查询参数 */
export interface ListTodosParams {
  status?: string;
  limit?: number;
  offset?: number;
}

/** 待办列表 */
export function getTodos(params?: ListTodosParams) {
  return request.get<TodoItem[]>(`/todos`, { params });
}

/** 创建待办 */
export function createTodo(data: Partial<TodoItem>) {
  return request.post<TodoItem>(`/todos`, data);
}

/** 更新待办 */
export function updateTodo(id: string, data: Partial<TodoItem>) {
  return request.put<TodoItem>(`/todos/${id}`, data);
}

/** 项目下待办 */
export function getProjectTodos(projectId: string) {
  return request.get<TodoItem[]>(`/projects/${projectId}/todos`);
}
