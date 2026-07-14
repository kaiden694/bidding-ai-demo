/**
 * LLM 管理 API 封装：对应后端
 *  /api/v1/admin/llm-providers
 *  /api/v1/admin/llm-providers/health
 *  /api/v1/admin/llm-usage/stats
 *
 * 端点：
 *  - GET    /admin/llm-providers               提供商列表
 *  - POST   /admin/llm-providers               创建提供商
 *  - PUT    /admin/llm-providers/{id}          更新提供商
 *  - DELETE /admin/llm-providers/{id}          删除提供商
 *  - GET    /admin/llm-providers/health        运行时状态概览（含熔断信息）
 *  - POST   /admin/llm-providers/{id}/health-check  手动健康检查
 *  - GET    /admin/llm-usage/stats            用量统计
 */
import { request } from "@/utils/request";
import type {
  LLMProvider,
  LLMProviderStatus,
  LLMHealthCheckResult,
  LLMUsageStats,
} from "@/types";

/** 创建/更新提供商请求体 */
export interface LLMProviderPayload {
  name: string;
  base_url: string;
  api_key?: string; // 更新时可选（留空不修改）
  model: string;
  weight?: number;
  is_active?: boolean;
  is_healthy?: boolean;
  metadata_json?: Record<string, any> | null;
}

/** 提供商列表 */
export function getLLMProviders() {
  return request.get<LLMProvider[]>(`/admin/llm-providers`);
}

/** 创建提供商 */
export function createLLMProvider(data: LLMProviderPayload) {
  return request.post<LLMProvider>(`/admin/llm-providers`, data);
}

/** 更新提供商 */
export function updateLLMProvider(id: string, data: LLMProviderPayload) {
  return request.put<LLMProvider>(`/admin/llm-providers/${id}`, data);
}

/** 删除提供商 */
export function deleteLLMProvider(id: string) {
  return request.delete<void>(`/admin/llm-providers/${id}`);
}

/** 单个健康检查 */
export function healthCheckProvider(id: string) {
  return request.post<LLMHealthCheckResult>(
    `/admin/llm-providers/${id}/health-check`,
  );
}

/** 运行时状态概览（含熔断信息） */
export function getLLMHealth() {
  return request.get<LLMProviderStatus[]>(`/admin/llm-providers/health`);
}

/** 用量统计 */
export function getLLMUsageStats(params?: { days?: number }) {
  return request.get<LLMUsageStats>(`/admin/llm-usage/stats`, { params });
}
