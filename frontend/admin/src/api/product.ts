/** 产品中心 API 封装：对应后端 /api/v1/products/*
 *
 * 端点：
 *  分类：
 *   - POST /categories        创建分类（201）
 *   - GET  /categories         分类列表
 *  产品：
 *   - POST /                   创建产品（201）
 *   - GET  /                    产品列表（?category_id=&keyword=）
 *   - GET  /{product_id}       产品详情
 *   - POST /{product_id}/publish 产品上架
 *   - POST /search             产品语义检索（body: { query }）
 *
 * 注：后端暂未提供产品/分类的更新与删除端点，故本封装不含 update/delete。
 */
import { request } from "@/utils/request";
import type {
  ProductCategoryItem,
  ProductItem,
  ProductSpec,
  SearchResultItem,
} from "@/types";

const BASE = "/products";

export interface ProductCategoryCreatePayload {
  name: string;
  code: string;
  parent_id?: string;
  description?: string;
}

export interface ProductCreatePayload {
  name: string;
  code?: string;
  category_id?: string;
  company_id?: string;  // 所属公司（多公司管理）
  model?: string;
  brand?: string;
  manufacturer?: string;
  description?: string;
  specs?: ProductSpec[];
  intro_doc_id?: string;
  qualification_ids?: string[];
  test_report_ids?: string[];
}

/** 产品分类列表 */
export function listCategories() {
  return request.get<ProductCategoryItem[]>(`${BASE}/categories`);
}

/** 创建产品分类 */
export function createCategory(payload: ProductCategoryCreatePayload) {
  return request.post<ProductCategoryItem>(`${BASE}/categories`, payload);
}

/** 产品列表（可按分类/公司/关键字筛选） */
export function listProducts(params?: {
  category_id?: string;
  company_id?: string;
  keyword?: string;
}) {
  return request.get<ProductItem[]>(BASE, { params });
}

/** 产品详情 */
export function getProduct(productId: string) {
  return request.get<ProductItem>(`${BASE}/${productId}`);
}

/** 创建产品 */
export function createProduct(payload: ProductCreatePayload) {
  return request.post<ProductItem>(BASE, payload);
}

/** 产品上架（供比对选型使用） */
export function publishProduct(productId: string) {
  return request.post<ProductItem>(`${BASE}/${productId}/publish`);
}

/** 产品语义检索 */
export function searchProducts(query: string) {
  return request.post<{ results: SearchResultItem[] }>(`${BASE}/search`, {
    query,
  });
}
