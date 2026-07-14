/** 资质台账 API 封装：对应后端 /api/v1/qualifications/*
 *
 * 端点：
 *  - POST   /                          创建资质（201）
 *  - GET    /                           资质列表（?qual_type=&supplier_name=&is_valid=）
 *  - GET    /expiring                  即将过期列表（?days=30）
 *  - GET    /alerts                     预警记录（?severity=）
 *  - GET    /{qual_id}                  资质详情
 *  - PATCH  /{qual_id}                  更新资质
 *  - DELETE /{qual_id}                  软删除（204）
 *  - POST   /{qual_id}/upload-certificate 上传证书 PDF（multipart: file）
 *  - POST   /{qual_id}/extract          OCR+LLM 字段提取
 */
import { request } from "@/utils/request";
import type { Qualification, QualificationAlert } from "@/types";

const BASE = "/qualifications";

export interface QualificationCreatePayload {
  name: string;
  qual_type?: string;
  cert_number?: string;
  issuer?: string;
  scope?: string;
  issue_date?: string;
  expire_date?: string;
  company_id?: string;  // 所属公司（多公司管理）
  owner?: string;
  supplier_name?: string;
  document_id?: string;
  is_valid?: boolean;
}

export type QualificationUpdatePayload = Partial<QualificationCreatePayload>;

export interface QualificationListParams {
  qual_type?: string;
  company_id?: string;  // 按公司筛选
  supplier_name?: string;
  is_valid?: boolean;
}

/** 资质列表（支持按类型/供应商/有效性过滤） */
export function listQualifications(params?: QualificationListParams) {
  return request.get<Qualification[]>(BASE, { params });
}

/** 即将过期的资质列表（默认 ≤30 天，含已过期） */
export function listExpiring(days = 30) {
  return request.get<Qualification[]>(`${BASE}/expiring`, { params: { days } });
}

/** 资质预警记录（由 Celery 定时任务写入） */
export function listAlerts(severity?: string) {
  return request.get<QualificationAlert[]>(`${BASE}/alerts`, {
    params: { severity },
  });
}

/** 资质详情 */
export function getQualification(qualId: string) {
  return request.get<Qualification>(`${BASE}/${qualId}`);
}

/** 创建资质 */
export function createQualification(payload: QualificationCreatePayload) {
  return request.post<Qualification>(BASE, payload);
}

/** 更新资质 */
export function updateQualification(
  qualId: string,
  payload: QualificationUpdatePayload,
) {
  return request.patch<Qualification>(`${BASE}/${qualId}`, payload);
}

/** 软删除资质 */
export function deleteQualification(qualId: string) {
  return request.delete<void>(`${BASE}/${qualId}`);
}

/** 上传资质证书 PDF（自动创建 Document + 关联资质） */
export function uploadCertificate(qualId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request.upload<Qualification>(`${BASE}/${qualId}/upload-certificate`, form);
}

/** OCR + LLM 提取资质证书字段（需先上传证书） */
export function extractFields(qualId: string) {
  return request.post<any>(`${BASE}/${qualId}/extract`);
}
