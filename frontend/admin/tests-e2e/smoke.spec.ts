/**
 * 冒烟 E2E 用例（T7.5）
 * 覆盖关键路径：登录 → 布局渲染 → 系统管理页可访问 → 退出登录
 * 依赖：后端运行在 :8000（dev server 已代理 /api）
 */
import { test, expect, type Page } from "@playwright/test";

const ADMIN = {
  username: "admin",
  password: "admin123",
};

async function login(page: Page) {
  await page.goto("/login");
  await page.getByPlaceholder("请输入用户名").fill(ADMIN.username);
  await page.getByPlaceholder("请输入密码").fill(ADMIN.password);
  await page.getByRole("button", { name: "登 录" }).click();
  // 等待跳转到首页
  await expect(page).toHaveURL(/\/dashboard/);
}

test.describe("冒烟流程", () => {
  test("登录页渲染", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText("管理后台登录")).toBeVisible();
    await expect(page.getByPlaceholder("请输入用户名")).toBeVisible();
    await expect(page.getByPlaceholder("请输入密码")).toBeVisible();
    await expect(page.getByRole("button", { name: "登 录" })).toBeVisible();
  });

  test("登录成功跳转工作台", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("未登录访问受保护路由重定向登录", async ({ page }) => {
    // 清除登录态
    await page.context().clearCookies();
    await page.goto("/system/users");
    await expect(page).toHaveURL(/\/login/);
  });

  test("登录后侧边栏菜单可见", async ({ page }) => {
    await login(page);
    // 系统管理菜单（admin 拥有所有权限）
    await expect(page.getByRole("menuitem", { name: "系统管理" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "业务管理" })).toBeVisible();
  });

  test("导航到用户管理页", async ({ page }) => {
    await login(page);
    await page.goto("/system/users");
    await expect(page).toHaveURL(/\/system\/users/);
    // 用户管理页应渲染表格或空状态
    await expect(page.locator("body")).toContainText(/用户|User|暂无/i);
  });

  test("导航到角色管理页", async ({ page }) => {
    await login(page);
    await page.goto("/system/roles");
    await expect(page).toHaveURL(/\/system\/roles/);
  });

  test("导航到审计日志页", async ({ page }) => {
    await login(page);
    await page.goto("/system/audit-logs");
    await expect(page).toHaveURL(/\/system\/audit-logs/);
  });

  test("导航到资质台账页", async ({ page }) => {
    await login(page);
    await page.goto("/qualifications");
    await expect(page).toHaveURL(/\/qualifications/);
  });

  test("面包屑显示当前页面", async ({ page }) => {
    await login(page);
    await page.goto("/system/users");
    // 面包屑含"用户管理"
    await expect(page.locator(".el-breadcrumb")).toContainText("用户管理");
  });

  test("退出登录回到登录页", async ({ page }) => {
    await login(page);
    // 点击用户下拉
    await page.locator(".user-info").click();
    await page.getByRole("menuitem", { name: "退出登录" }).click();
    // 确认对话框
    await page.getByRole("button", { name: "确定" }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("403 页面渲染", async ({ page }) => {
    await page.goto("/403");
    await expect(page.getByText("403 无权限")).toBeVisible();
  });

  test("404 页面渲染", async ({ page }) => {
    await page.goto("/non-existent-page-xyz");
    await expect(page.getByText("404 未找到")).toBeVisible();
  });
});
