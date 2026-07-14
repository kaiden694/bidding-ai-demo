/** 通用知识库 API 封装：对应后端 /api/v1/general-knowledge/*
 *
 * 端点：
 *  - POST   /                  创建通用知识库（201）
 *  - GET    /                   列表（?category=&visibility=，按用户身份过滤）
 *  - GET    /{kb_id}            详情
 *  - DELETE /{kb_id}            软删除（204）
 *  - POST   /search             语义检索（body: GeneralSearchRequest）
 *  - POST   /{kb_id}/import     ZIP 批量导入（multipart: file）
 *  - POST   /{kb_id}/reindex    重建 Embedding
 *  - GET    /{kb_id}/import-status 导入/重建进度
 *
 * 注：后端暂未提供通用知识库的更新端点，故本封装不含 update。
 */
import { request } from "@/utils/request";
import type {
  GeneralKnowledgeBase,
  ImportStatus,
  SearchResultItem,
} from "@/types";

const BASE = "/general-knowledge";

export interface GeneralKnowledgeCreatePayload {
  name: string;
  description?: string;
  category?: string;
  source_doc_id?: string;
  visibility?: string; // all / front / back
  tags?: string[];
}

export interface GeneralSearchPayload {
  query: string;
  category?: string;
  visibility?: string;
  top_k?: number;
}

/** 通用知识库列表 */
export function listGeneralKnowledge(params?: {
  category?: string;
  visibility?: string;
}) {
  return request.get<GeneralKnowledgeBase[]>(BASE, { params });
}

/** 通用知识库详情 */
export function getGeneralKnowledge(kbId: string) {
  return request.get<GeneralKnowledgeBase>(`${BASE}/${kbId}`);
}

/** 创建通用知识库 */
export function createGeneralKnowledge(payload: GeneralKnowledgeCreatePayload) {
  return request.post<GeneralKnowledgeBase>(BASE, payload);
}

/** 软删除通用知识库 */
export function deleteGeneralKnowledge(kbId: string) {
  return request.delete<void>(`${BASE}/${kbId}`);
}

/** ZIP 批量导入通用知识库文档 */
export function batchImport(kbId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request.upload<any>(`${BASE}/${kbId}/import`, form);
}

/** 重建通用知识库所有切块的 Embedding */
export function reindex(kbId: string) {
  return request.post<any>(`${BASE}/${kbId}/reindex`);
}

/** 查询通用知识库导入/重建进度 */
export function getImportStatus(kbId: string) {
  return request.get<ImportStatus>(`${BASE}/${kbId}/import-status`);
}

/** 通用知识库语义检索 */
export function searchGeneralKnowledge(payload: GeneralSearchPayload) {
  return request.post<{ results: SearchResultItem[] }>(
    `${BASE}/search`,
    payload,
  );
}
