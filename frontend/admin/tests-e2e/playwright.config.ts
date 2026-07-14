/**
 * Playwright 配置
 * - 前端 dev server :5173
 * - 后端 API :8000（dev server 已代理 /api → 8000）
 * - 测试用例在 tests-e2e/ 目录
 *
 * 运行：
 *   npx playwright install --with-deps   # 首次安装浏览器
 *   npx playwright test                  # 运行所有 E2E
 *   npx playwright test --headed        # 有头模式
 *   npx playwright test --ui            # 交互式 UI 模式
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests-e2e",
  fullyParallel: false, // 串行：测试间共享登录态
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // 单 worker：避免并发写同一用户
  reporter: [["html", { open: "never" }], ["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // 自动启动前端 dev server
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    cwd: "../",
  },
});
