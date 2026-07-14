/** 历史知识库 API 封装：对应后端 /api/v1/knowledge/*
 *
 * 端点（历史知识库，is_general=False）：
 *  - POST   /bases                      创建知识库
 *  - GET    /bases                       知识库列表（?category=&is_active=）
 *  - GET    /bases/{kb_id}               知识库详情
 *  - PATCH  /bases/{kb_id}               更新知识库
 *  - DELETE /bases/{kb_id}               软删除（204）
 *  - POST   /bases/{kb_id}/import        ZIP 批量导入（multipart: file + is_general）
 *  - POST   /bases/{kb_id}/reindex       重建 Embedding（?is_general=）
 *  - GET    /bases/{kb_id}/import-status  导入/重建进度（?is_general=）
 *  - POST   /bases/{kb_id}/switch-version 版本切换（body: { is_general })
 *  - GET    /bases/{kb_id}/chunks        切块列表（?is_general=&limit=&offset=）
 *  - POST   /bases/{kb_id}/chunks/filter 按标签筛选切块（body: FilterChunksRequest）
 *  - PATCH  /chunks/{chunk_id}/tags      更新切块标签（body: { tags }）
 *  - POST   /search                      语义检索（body: { query, category, top_k }）
 */
import { request } from "@/utils/request";
import type {
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeChunkBrief,
  ImportStatus,
  SearchResultItem,
} from "@/types";

const BASE = "/knowledge";

export interface KnowledgeBaseCreatePayload {
  name: string;
  description?: string;
  category?: string;
  version?: string;
  is_active?: boolean;
  tags?: any[];
}

export interface KnowledgeBaseUpdatePayload {
  name?: string;
  description?: string;
  category?: string;
  is_active?: boolean;
  tags?: any[];
}

export interface FilterChunksPayload {
  tag_key: string;
  tag_value: string;
  limit?: number;
}

export interface SearchKnowledgePayload {
  query: string;
  category?: string;
  top_k?: number;
}

/** 历史知识库列表 */
export function listKnowledgeBases(params?: {
  category?: string;
  is_active?: boolean;
}) {
  return request.get<KnowledgeBase[]>(`${BASE}/bases`, { params });
}

/** 知识库详情 */
export function getKnowledgeBase(kbId: string) {
  return request.get<KnowledgeBase>(`${BASE}/bases/${kbId}`);
}

/** 创建知识库 */
export function createKnowledgeBase(payload: KnowledgeBaseCreatePayload) {
  return request.post<KnowledgeBase>(`${BASE}/bases`, payload);
}

/** 更新知识库 */
export function updateKnowledgeBase(
  kbId: string,
  payload: KnowledgeBaseUpdatePayload,
) {
  return request.patch<KnowledgeBase>(`${BASE}/bases/${kbId}`, payload);
}

/** 软删除知识库 */
export function deleteKnowledgeBase(kbId: string) {
  return request.delete<void>(`${BASE}/bases/${kbId}`);
}

/** ZIP 批量导入文档（解析 → 切块 → 向量化） */
export function batchImport(kbId: string, file: File, isGeneral = false) {
  const form = new FormData();
  form.append("file", file);
  form.append("is_general", String(isGeneral));
  return request.upload<any>(`${BASE}/bases/${kbId}/import`, form);
}

/** 重建知识库所有切块的 Embedding */
export function reindex(kbId: string, isGeneral = false) {
  return request.post<any>(`${BASE}/bases/${kbId}/reindex`, undefined, {
    params: { is_general: isGeneral },
  });
}

/** 查询导入/重建进度 */
export function getImportStatus(kbId: string, isGeneral = false) {
  return request.get<ImportStatus>(`${BASE}/bases/${kbId}/import-status`, {
    params: { is_general: isGeneral },
  });
}

/** 版本切换：将目标知识库设为 active，同 name 的其他版本置为 inactive */
export function switchVersion(kbId: string, isGeneral = false) {
  return request.post<any>(`${BASE}/bases/${kbId}/switch-version`, {
    is_general: isGeneral,
  });
}

/** 切块列表 */
export function listChunks(
  kbId: string,
  params?: { is_general?: boolean; limit?: number; offset?: number },
) {
  return request.get<KnowledgeChunk[]>(`${BASE}/bases/${kbId}/chunks`, {
    params,
  });
}

/** 按标签筛选切块（tag_key + tag_value 精确匹配） */
export function filterChunks(
  kbId: string,
  payload: FilterChunksPayload,
  isGeneral = false,
) {
  return request.post<{ items: KnowledgeChunkBrief[] }>(
    `${BASE}/bases/${kbId}/chunks/filter`,
    payload,
    { params: { is_general: isGeneral } },
  );
}

/** 更新切块标签（标签存入 metadata_json.tags） */
export function updateChunkTags(
  chunkId: string,
  tags: Record<string, any>,
  isGeneral = false,
) {
  return request.patch<KnowledgeChunk>(
    `${BASE}/chunks/${chunkId}/tags`,
    { tags },
    { params: { is_general: isGeneral } },
  );
}

/** 语义检索知识库 */
export function searchKnowledge(payload: SearchKnowledgePayload) {
  return request.post<{ results: SearchResultItem[] }>(
    `${BASE}/search`,
    payload,
  );
}
