/**
 * Pinia auth store
 * - token 管理（access/refresh，持久化到 localStorage）
 * - 用户信息（user_id / username / full_name / is_admin / permissions）
 * - login / refresh / logout actions
 * - 启动时向 request.ts 注入回调
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import * as authApi from "@/api/auth";
import { setAuthHandlers } from "@/utils/request";
import type { UserInfoResponse } from "@/types";

const STORAGE_KEY = "sbaw-auth";

interface PersistedAuth {
  access_token: string;
  refresh_token: string;
  user_id: string;
  username: string;
  full_name: string | null;
  is_admin: boolean;
  permissions: string[];
}

function loadPersisted(): PersistedAuth | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedAuth;
  } catch {
    return null;
  }
}

function persist(data: PersistedAuth) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function clearPersisted() {
  localStorage.removeItem(STORAGE_KEY);
}

export const useAuthStore = defineStore("auth", () => {
  // ---- state ----
  const persisted = loadPersisted();
  const accessToken = ref<string | null>(persisted?.access_token ?? null);
  const refreshToken = ref<string | null>(persisted?.refresh_token ?? null);
  const userId = ref<string | null>(persisted?.user_id ?? null);
  const username = ref<string | null>(persisted?.username ?? null);
  const fullName = ref<string | null>(persisted?.full_name ?? null);
  const isAdmin = ref<boolean>(persisted?.is_admin ?? false);
  const permissions = ref<string[]>(persisted?.permissions ?? []);

  // ---- getters ----
  const isAuthenticated = computed(() => !!accessToken.value);
  const hasPermission = computed(() => (code: string) =>
    isAdmin.value || permissions.value.includes(code),
  );

  function _save(p: PersistedAuth) {
    accessToken.value = p.access_token;
    refreshToken.value = p.refresh_token;
    userId.value = p.user_id;
    username.value = p.username;
    fullName.value = p.full_name;
    isAdmin.value = p.is_admin;
    permissions.value = p.permissions;
    persist(p);
  }

  // ---- actions ----
  async function login(payload: { username: string; password: string }) {
    const res = await authApi.login(payload);
    _save({
      access_token: res.access_token,
      refresh_token: res.refresh_token,
      user_id: res.user_id,
      username: res.username,
      full_name: res.full_name,
      is_admin: res.is_admin,
      permissions: res.permissions,
    });
    return res;
  }

  /** 用 refresh_token 换新 access_token；失败返回 null */
  async function refresh(): Promise<string | null> {
    if (!refreshToken.value) return null;
    try {
      const res = await authApi.refreshToken(refreshToken.value);
      _save({
        access_token: res.access_token,
        refresh_token: res.refresh_token,
        user_id: res.user_id,
        username: res.username,
        full_name: res.full_name,
        is_admin: res.is_admin,
        permissions: res.permissions,
      });
      return res.access_token;
    } catch {
      clear();
      return null;
    }
  }

  /** 从 /auth/me 拉取最新用户信息 + 权限点 */
  async function fetchMe() {
    if (!accessToken.value) return null;
    const me: UserInfoResponse = await authApi.getMe();
    permissions.value = me.permissions ?? [];
    isAdmin.value = me.is_admin;
    userId.value = me.user_id;
    username.value = me.username;
    fullName.value = me.full_name;
    // 同步到持久化
    if (accessToken.value && refreshToken.value) {
      persist({
        access_token: accessToken.value,
        refresh_token: refreshToken.value,
        user_id: me.user_id,
        username: me.username,
        full_name: me.full_name,
        is_admin: me.is_admin,
        permissions: me.permissions,
      });
    }
    return me;
  }

  async function logout() {
    try {
      await authApi.logout();
    } catch {
      // 忽略登出失败
    }
    clear();
  }

  function clear() {
    accessToken.value = null;
    refreshToken.value = null;
    userId.value = null;
    username.value = null;
    fullName.value = null;
    isAdmin.value = false;
    permissions.value = [];
    clearPersisted();
  }

  // ---- 向 request 注入回调 ----
  setAuthHandlers({
    getAccessToken: () => accessToken.value,
    refresh,
    logout: () => clear(),
  });

  return {
    // state
    accessToken,
    refreshToken,
    userId,
    username,
    fullName,
    isAdmin,
    permissions,
    // getters
    isAuthenticated,
    hasPermission,
    // actions
    login,
    refresh,
    fetchMe,
    logout,
    clear,
  };
});
