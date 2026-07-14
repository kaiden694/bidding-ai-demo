/**
 * OCR 提供商管理 API 封装：对应后端
 *  /api/v1/admin/ocr-providers
 *
 * 端点：
 *  - GET    /admin/ocr-providers               提供商列表
 *  - GET    /admin/ocr-providers/active        当前生效 provider
 *  - POST   /admin/ocr-providers               创建提供商
 *  - PUT    /admin/ocr-providers/{id}          更新提供商
 *  - DELETE /admin/ocr-providers/{id}          删除提供商
 *  - POST   /admin/ocr-providers/{id}/health-check  手动健康检查
 */
import { request } from "@/utils/request";
import type {
  OCRProvider,
  OCRProviderStatus,
  OCRHealthCheckResult,
  OCRProviderType,
} from "@/types";

/** 创建/更新提供商请求体 */
export interface OCRProviderPayload {
  name: string;
  provider_type?: OCRProviderType;
  base_url?: string;
  api_key?: string; // 更新时可选（留空不修改）
  model?: string | null;
  is_active?: boolean;
  metadata_json?: Record<string, any> | null;
}

/** OCR 服务类型标签映射 */
export const OCR_PROVIDER_TYPE_LABELS: Record<OCRProviderType, string> = {
  mineru: "MinerU",
  paddleocr: "PaddleOCR",
  local: "本地 rapidocr",
  other: "其他",
};

/** OCR 服务类型标签颜色 */
export const OCR_PROVIDER_TYPE_COLORS: Record<OCRProviderType, string> = {
  mineru: "primary",
  paddleocr: "success",
  local: "info",
  other: "warning",
};

/** 提供商列表 */
export function getOCRProviders() {
  return request.get<OCRProvider[]>(`/admin/ocr-providers`);
}

/** 当前生效 provider */
export function getActiveOCRProvider() {
  return request.get<OCRProviderStatus>(`/admin/ocr-providers/active`);
}

/** 创建提供商 */
export function createOCRProvider(data: OCRProviderPayload) {
  return request.post<OCRProvider>(`/admin/ocr-providers`, data);
}

/** 更新提供商 */
export function updateOCRProvider(id: string, data: OCRProviderPayload) {
  return request.put<OCRProvider>(`/admin/ocr-providers/${id}`, data);
}

/** 删除提供商 */
export function deleteOCRProvider(id: string) {
  return request.delete<void>(`/admin/ocr-providers/${id}`);
}

/** 单个健康检查 */
export function healthCheckOCRProvider(id: string) {
  return request.post<OCRHealthCheckResult>(
    `/admin/ocr-providers/${id}/health-check`,
  );
}
