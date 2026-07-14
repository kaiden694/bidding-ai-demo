/**
 * 应用入口
 * - 创建 Vue app
 * - 注册 Pinia / Router / Element Plus 图标
 * - 挂载
 */
import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";

import App from "./App.vue";
import router from "./router";

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { size: "default" });

// 全量注册 Element Plus 图标（按需更省体积，但管理后台优先便利性）
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

app.mount("#app");
