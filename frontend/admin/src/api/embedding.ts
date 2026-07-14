/**
 * Embedding 管理 API 封装：对应后端
 *  /api/v1/admin/embedding-providers
 *
 * 端点：
 *  - GET    /admin/embedding-providers               提供商列表
 *  - POST   /admin/embedding-providers               创建提供商
 *  - PUT    /admin/embedding-providers/{id}          更新提供商
 *  - DELETE /admin/embedding-providers/{id}          删除提供商
 *  - GET    /admin/embedding-providers/active        当前生效 provider（内存缓存）
 *  - POST   /admin/embedding-providers/{id}/health-check  手动健康检查
 */
import { request } from "@/utils/request";
import type {
  EmbeddingProvider,
  EmbeddingProviderStatus,
  EmbeddingHealthCheckResult,
} from "@/types";

/** 创建/更新提供商请求体 */
export interface EmbeddingProviderPayload {
  name: string;
  base_url: string;
  api_key?: string; // 更新时可选（留空不修改）
  model: string;
  dim?: number;
  is_active?: boolean;
  is_healthy?: boolean;
  metadata_json?: Record<string, any> | null;
}

/** 提供商列表 */
export function getEmbeddingProviders() {
  return request.get<EmbeddingProvider[]>(`/admin/embedding-providers`);
}

/** 当前生效 provider（内存缓存） */
export function getActiveEmbeddingProvider() {
  return request.get<EmbeddingProviderStatus>(`/admin/embedding-providers/active`);
}

/** 创建提供商 */
export function createEmbeddingProvider(data: EmbeddingProviderPayload) {
  return request.post<EmbeddingProvider>(`/admin/embedding-providers`, data);
}

/** 更新提供商 */
export function updateEmbeddingProvider(id: string, data: EmbeddingProviderPayload) {
  return request.put<EmbeddingProvider>(`/admin/embedding-providers/${id}`, data);
}

/** 删除提供商 */
export function deleteEmbeddingProvider(id: string) {
  return request.delete<void>(`/admin/embedding-providers/${id}`);
}

/** 单个健康检查 */
export function healthCheckEmbeddingProvider(id: string) {
  return request.post<EmbeddingHealthCheckResult>(
    `/admin/embedding-providers/${id}/health-check`,
  );
}
