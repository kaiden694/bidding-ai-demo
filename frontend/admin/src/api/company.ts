/**
 * 公司主数据 API 封装：对应后端
 *  /api/v1/companies
 *
 * 端点：
 *  - GET    /companies               公司列表（支持 company_type / keyword 筛选）
 *  - GET    /companies/brief         精简列表（下拉选择器用）
 *  - GET    /companies/{id}          获取单个公司
 *  - POST   /companies               创建公司
 *  - PUT    /companies/{id}          更新公司
 *  - DELETE /companies/{id}          删除公司（软删除）
 */
import { request } from "@/utils/request";
import type { Company, CompanyBrief, CompanyType } from "@/types";

/** 创建/更新公司请求体 */
export interface CompanyPayload {
  name: string;
  short_name?: string | null;
  code?: string | null;
  company_type?: CompanyType;
  description?: string | null;
  metadata_json?: Record<string, any> | null;
}

/** 公司类型中文标签映射 */
export const COMPANY_TYPE_LABELS: Record<CompanyType, string> = {
  self: "本公司",
  partner: "合作公司",
  competitor: "竞品公司",
  other: "其他",
};

/** 公司类型标签颜色 */
export const COMPANY_TYPE_COLORS: Record<CompanyType, string> = {
  self: "success",
  partner: "primary",
  competitor: "danger",
  other: "info",
};

/** 公司列表 */
export function getCompanies(params?: {
  company_type?: CompanyType;
  keyword?: string;
}) {
  return request.get<Company[]>(`/companies`, { params });
}

/** 精简列表（下拉选择器用） */
export function getCompaniesBrief(params?: { company_type?: CompanyType }) {
  return request.get<CompanyBrief[]>(`/companies/brief`, { params });
}

/** 获取单个公司 */
export function getCompany(id: string) {
  return request.get<Company>(`/companies/${id}`);
}

/** 创建公司 */
export function createCompany(data: CompanyPayload) {
  return request.post<Company>(`/companies`, data);
}

/** 更新公司 */
export function updateCompany(id: string, data: CompanyPayload) {
  return request.put<Company>(`/companies/${id}`, data);
}

/** 删除公司（软删除） */
export function deleteCompany(id: string) {
  return request.delete<void>(`/companies/${id}`);
}
