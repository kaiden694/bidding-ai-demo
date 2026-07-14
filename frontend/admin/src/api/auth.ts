/** 认证 API 封装：对应后端 /api/v1/auth/* */
import { request } from "@/utils/request";
import type {
  LoginRequest,
  TokenResponse,
  RefreshRequest,
  UserInfoResponse,
} from "@/types";

export function login(payload: LoginRequest) {
  return request.post<TokenResponse>("/auth/login", payload);
}

export function refreshToken(refresh_token: string) {
  return request.post<TokenResponse>("/auth/refresh", {
    refresh_token,
  } as RefreshRequest);
}

export function logout() {
  return request.post<{ message: string }>("/auth/logout");
}

export function getMe() {
  return request.get<UserInfoResponse>("/auth/me");
}
