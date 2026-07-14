/**
 * axios 实例 + 拦截器
 * - 请求拦截：注入 JWT Authorization 头
 * - 响应拦截：401 触发 token 刷新（含并发去重）；403 提示无权限
 *
 * 为避免与 auth store 循环依赖，刷新/登出回调通过 setAuthHandlers 注入。
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { ElMessage, ElMessageBox } from "element-plus";

/** 后端统一错误响应：{ detail: string } */
export interface ApiError {
  detail: string;
}

/** 由 auth store 注入的回调 */
interface AuthHandlers {
  /** 获取当前 access_token */
  getAccessToken: () => string | null;
  /** 用 refresh_token 换新 access_token；返回新 token 或 null */
  refresh: () => Promise<string | null>;
  /** 清空登录态并跳转登录页 */
  logout: () => void;
}

let handlers: AuthHandlers | null = null;

export function setAuthHandlers(h: AuthHandlers) {
  handlers = h;
}

const service: AxiosInstance = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

// ---- 请求拦截：注入 JWT ----
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    if (handlers) {
      const token = handlers.getAccessToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    return config;
  },
  (err) => Promise.reject(err),
);

// ---- 并发刷新去重 ----
let refreshPromise: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  if (!handlers) return null;
  if (refreshPromise) return refreshPromise;
  refreshPromise = handlers.refresh().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

// ---- 响应拦截：错误处理 ----
service.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  async (error) => {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail || error?.message || "请求失败";

    if (status === 401) {
      // 尝试刷新
      const newToken = await doRefresh();
      if (newToken && error.config) {
        // 重放原请求
        error.config.headers.Authorization = `Bearer ${newToken}`;
        return service.request(error.config);
      }
      // 刷新失败：登出
      handlers?.logout();
      ElMessage.error("登录已过期，请重新登录");
      return Promise.reject(error);
    }

    if (status === 403) {
      ElMessage.warning("无权限执行该操作");
      return Promise.reject(error);
    }

    ElMessage.error(detail);
    return Promise.reject(error);
  },
);

/** 便捷方法 */
export const request = {
  get: <T = any>(url: string, config?: AxiosRequestConfig) =>
    service.get<T, T>(url, config),
  post: <T = any>(url: string, data?: any, config?: AxiosRequestConfig) =>
    service.post<T, T>(url, data, config),
  put: <T = any>(url: string, data?: any, config?: AxiosRequestConfig) =>
    service.put<T, T>(url, data, config),
  patch: <T = any>(url: string, data?: any, config?: AxiosRequestConfig) =>
    service.patch<T, T>(url, data, config),
  delete: <T = any>(url: string, config?: AxiosRequestConfig) =>
    service.delete<T, T>(url, config),
  /** 上传（保持原生 axios 以便监听进度） */
  upload: <T = any>(url: string, formData: FormData, config?: AxiosRequestConfig) =>
    service.post<T, T>(url, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      ...config,
    }),
};

export default service;
