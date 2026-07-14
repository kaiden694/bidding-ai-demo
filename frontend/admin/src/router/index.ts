/**
 * 路由定义 + 路由守卫
 * - 登录态校验：未登录访问受保护路由 → 重定向 /login
 * - 管理员校验：管理后台路由需 is_admin（或具备任一后台权限点）
 * - 业务页权限点：路由 meta.permission 控制可见性
 *
 * T6.2 将替换 LoginView 与 LayoutView 的占位实现。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "Login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/",
    component: () => import("@/layouts/AdminLayout.vue"),
    redirect: "/dashboard",
    children: [
      {
        path: "dashboard",
        name: "Dashboard",
        component: () => import("@/views/PlaceholderView.vue"),
        meta: { title: "工作台", icon: "House", task: "待实现" },
      },
      // ---- 系统管理 ----
      {
        path: "system/users",
        name: "SystemUsers",
        component: () => import("@/views/system/UsersView.vue"),
        meta: { title: "用户管理", icon: "User", permission: "user:view" },
      },
      {
        path: "system/roles",
        name: "SystemRoles",
        component: () => import("@/views/system/RolesView.vue"),
        meta: { title: "角色管理", icon: "UserFilled", permission: "role:view" },
      },
      {
        path: "system/organizations",
        name: "SystemOrganizations",
        component: () => import("@/views/system/OrganizationsView.vue"),
        meta: { title: "组织管理", icon: "OfficeBuilding", permission: "organization:view" },
      },
      {
        path: "system/audit-logs",
        name: "SystemAuditLogs",
        component: () => import("@/views/system/AuditLogsView.vue"),
        meta: { title: "审计日志", icon: "Document", permission: "audit_log:view" },
      },
      {
        path: "system/companies",
        name: "SystemCompanies",
        component: () => import("@/views/CompanyManageView.vue"),
        meta: { title: "公司管理", icon: "Building", permission: "system:config" },
      },
      // ---- 知识与资质 ----
      {
        path: "knowledge/bases",
        name: "KnowledgeBases",
        component: () => import("@/views/KnowledgeBasesView.vue"),
        meta: { title: "历史知识库", icon: "Files", permission: "knowledge:view" },
      },
      {
        path: "qualifications",
        name: "Qualifications",
        component: () => import("@/views/QualificationsView.vue"),
        meta: { title: "资质台账", icon: "Medal", permission: "qualification:view" },
      },
      {
        path: "products",
        name: "Products",
        component: () => import("@/views/ProductsView.vue"),
        meta: { title: "产品中心", icon: "Box", permission: "product:view" },
      },
      {
        path: "general-knowledge",
        name: "GeneralKnowledge",
        component: () => import("@/views/GeneralKnowledgeView.vue"),
        meta: { title: "通用知识库", icon: "Reading", permission: "general_knowledge:view" },
      },
      // ---- Phase 3 ----
      {
        path: "projects",
        name: "Projects",
        component: () => import("@/views/ProjectsView.vue"),
        meta: { title: "项目管理", icon: "Briefcase", permission: "project:view" },
      },
      {
        path: "todos",
        name: "Todos",
        component: () => import("@/views/TodosView.vue"),
        meta: { title: "待办看板", icon: "List", permission: "todo:view" },
      },
      {
        path: "notifications",
        name: "Notifications",
        component: () => import("@/views/NotificationsView.vue"),
        meta: { title: "通知中心", icon: "Bell", permission: "notification:view" },
      },
      {
        path: "bid-drafts",
        name: "BidDrafts",
        component: () => import("@/views/BidDraftView.vue"),
        meta: { title: "标书起草", icon: "EditPen", permission: "bid:view" },
      },
      {
        path: "system/llm",
        name: "LLMManage",
        component: () => import("@/views/LLMManageView.vue"),
        meta: { title: "AI 服务配置", icon: "Cpu", permission: "system:config" },
      },
    ],
  },
  {
    path: "/403",
    name: "Forbidden",
    component: () => import("@/views/ForbiddenView.vue"),
    meta: { public: true, title: "无权限" },
  },
  {
    path: "/:pathMatch(.*)*",
    name: "NotFound",
    component: () => import("@/views/NotFoundView.vue"),
    meta: { public: true, title: "未找到" },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// ---- 路由守卫 ----
router.beforeEach((to, _from, next) => {
  const auth = useAuthStore();

  // 公开路由直接放行
  if (to.meta.public) {
    next();
    return;
  }

  // 未登录 → 跳登录
  if (!auth.isAuthenticated) {
    next({ name: "Login", query: { redirect: to.fullPath } });
    return;
  }

  // 权限点校验
  const requiredPerm = to.meta?.permission as string | undefined;
  if (requiredPerm && !auth.hasPermission(requiredPerm)) {
    next({ name: "Forbidden" });
    return;
  }

  next();
});

// ---- 标题同步 ----
router.afterEach((to) => {
  const title = (to.meta?.title as string) ?? "";
  document.title = title
    ? `${title} - 智能招投标与合同合规 AI 工作台`
    : "智能招投标与合同合规 AI 工作台";
});

export default router;
