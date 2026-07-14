<template>
  <el-container class="admin-layout">
    <!-- 侧边栏 -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
      <div class="logo">
        <span v-if="!collapsed" class="logo-text">AI 合规工作台</span>
        <span v-else class="logo-icon">AI</span>
      </div>
      <el-scrollbar>
        <el-menu
          :default-active="activeMenu"
          :collapse="collapsed"
          :collapse-transition="false"
          router
          background-color="#001529"
          text-color="#b7c0d1"
          active-text-color="#ffffff"
        >
          <template v-for="item in menus" :key="item.path">
            <el-sub-menu v-if="item.children?.length" :index="item.path">
              <template #title>
                <el-icon v-if="item.icon">
                  <component :is="item.icon" />
                </el-icon>
                <span>{{ item.title }}</span>
              </template>
              <el-menu-item
                v-for="child in item.children"
                :key="child.path"
                :index="child.path"
              >
                <el-icon v-if="child.icon">
                  <component :is="child.icon" />
                </el-icon>
                <template #title>{{ child.title }}</template>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.path">
              <el-icon v-if="item.icon">
                <component :is="item.icon" />
              </el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <!-- 顶栏 -->
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapsed = !collapsed">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
          <!-- 面包屑 -->
          <el-breadcrumb separator="/" class="breadcrumb">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-for="crumb in breadcrumbs" :key="crumb.path">
              {{ crumb.title }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <!-- 通知铃铛 -->
          <el-badge
            :value="unreadCount"
            :hidden="unreadCount === 0"
            :max="99"
            class="notify-badge"
          >
            <el-icon class="notify-icon" @click="goNotifications">
              <Bell />
            </el-icon>
          </el-badge>

          <el-dropdown @command="onCommand">
            <span class="user-info">
              <el-avatar :size="32" class="avatar">
                {{ avatarText }}
              </el-avatar>
              <span class="username">{{ auth.username || "未登录" }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" disabled>
                  <el-icon><User /></el-icon>个人中心
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 主内容区 -->
      <el-main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Fold,
  Expand,
  ArrowDown,
  User,
  SwitchButton,
  Bell,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import { getUnreadCount } from "@/api/notification";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const collapsed = ref(false);

// ---- 通知未读数轮询 ----
const unreadCount = ref(0);
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function loadUnreadCount() {
  try {
    const res = await getUnreadCount();
    unreadCount.value = res.count ?? 0;
  } catch {
    // 拦截器已处理；非关键错误忽略
  }
}

function startPolling() {
  stopPolling();
  // 每 30s 轮询一次未读数
  pollTimer = setInterval(loadUnreadCount, 30 * 1000);
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function goNotifications() {
  router.push("/notifications");
}

interface MenuItem {
  path: string;
  title: string;
  icon?: any;
  permission?: string;
  children?: MenuItem[];
}

/** 菜单配置：与路由定义对应，按权限点过滤
 * 顺序：工作台 → 业务管理 → 系统管理
 */
const allMenus: MenuItem[] = [
  { path: "/dashboard", title: "工作台", icon: "House" },
  {
    path: "/business",
    title: "业务管理",
    icon: "Briefcase",
    children: [
      { path: "/projects", title: "项目管理", icon: "Briefcase", permission: "project:view" },
      { path: "/todos", title: "待办看板", icon: "List", permission: "todo:view" },
      { path: "/bid-drafts", title: "标书起草", icon: "EditPen", permission: "bid:view" },
      { path: "/knowledge/bases", title: "历史知识库", icon: "Files", permission: "knowledge:view" },
      { path: "/qualifications", title: "资质台账", icon: "Medal", permission: "qualification:view" },
      { path: "/products", title: "产品中心", icon: "Box", permission: "product:view" },
      { path: "/general-knowledge", title: "通用知识库", icon: "Reading", permission: "general_knowledge:view" },
    ],
  },
  {
    path: "/system",
    title: "系统管理",
    icon: "Setting",
    children: [
      { path: "/system/users", title: "用户管理", icon: "User", permission: "user:view" },
      { path: "/system/roles", title: "角色管理", icon: "UserFilled", permission: "role:view" },
      { path: "/system/organizations", title: "组织管理", icon: "OfficeBuilding", permission: "organization:view" },
      { path: "/system/audit-logs", title: "审计日志", icon: "Document", permission: "audit_log:view" },
      { path: "/system/companies", title: "公司管理", icon: "Building", permission: "system:config" },
      { path: "/system/llm", title: "AI 服务配置", icon: "Cpu", permission: "system:config" },
    ],
  },
];

/** 按权限过滤后的菜单 */
const menus = computed<MenuItem[]>(() => {
  return allMenus
    .map((m) => {
      if (m.children?.length) {
        const children = m.children.filter(
          (c) => !c.permission || auth.hasPermission(c.permission),
        );
        return children.length ? { ...m, children } : null;
      }
      return !m.permission || auth.hasPermission(m.permission) ? m : null;
    })
    .filter((m): m is MenuItem => !!m);
});

const activeMenu = computed(() => route.path);

const avatarText = computed(() => {
  const name = auth.username || auth.fullName || "?";
  return name.charAt(0).toUpperCase();
});

/** 面包屑：根据当前路由层级生成 */
const breadcrumbs = computed(() => {
  const matched = route.matched.filter((r) => r.meta?.title);
  return matched.map((r) => ({ path: r.path, title: r.meta?.title as string }));
});

async function onCommand(cmd: string) {
  if (cmd === "logout") {
    try {
      await ElMessageBox.confirm("确定要退出登录吗？", "提示", {
        type: "warning",
        confirmButtonText: "确定",
        cancelButtonText: "取消",
      });
      await auth.logout();
      ElMessage.success("已退出登录");
      router.replace("/login");
    } catch {
      // 取消
    }
  }
}

onMounted(() => {
  loadUnreadCount();
  startPolling();
});

onBeforeUnmount(() => {
  stopPolling();
});
</script>

<style scoped>
.admin-layout {
  height: 100vh;
}

.sidebar {
  background-color: #001529;
  transition: width 0.3s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  border-bottom: 1px solid #1d2b3f;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.logo-icon {
  font-size: 18px;
  font-weight: 700;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  padding: 0 16px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  font-size: 20px;
  cursor: pointer;
  color: #5a5e66;
}

.collapse-btn:hover {
  color: #409eff;
}

.breadcrumb {
  font-size: 14px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.notify-badge {
  margin-right: 4px;
}

.notify-icon {
  font-size: 20px;
  cursor: pointer;
  color: #5a5e66;
}

.notify-icon:hover {
  color: #409eff;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 0 8px;
  height: 60px;
  outline: none;
}

.avatar {
  background-color: #409eff;
  color: #fff;
  font-weight: 600;
}

.username {
  font-size: 14px;
  color: #303133;
}

.main {
  background-color: #f0f2f5;
  padding: 16px;
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 覆盖 Element Plus 菜单在暗色背景下的样式 */
.el-menu {
  border-right: none;
}
</style>
