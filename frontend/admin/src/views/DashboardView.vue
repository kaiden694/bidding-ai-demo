<template>
  <div class="dashboard">
    <!-- 欢迎区 -->
    <el-card shadow="never" class="welcome-card">
      <div class="welcome-row">
        <div>
          <h2 class="welcome-title">{{ greeting }}，{{ auth.username || "用户" }}</h2>
          <p class="welcome-sub">{{ todayStr }} · 智能招投标与合同合规 AI 工作台</p>
        </div>
        <div class="welcome-actions">
          <el-button type="primary" :icon="Plus" @click="go('/projects')">新建项目</el-button>
          <el-button :icon="Upload" @click="go('/knowledge/bases')">上传文档</el-button>
        </div>
      </div>
    </el-card>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <el-card
        v-for="card in statCards"
        :key="card.key"
        shadow="hover"
        class="stat-card"
        @click="go(card.path)"
      >
        <div class="stat-row">
          <div class="stat-icon" :class="card.color">
            <el-icon :size="24"><component :is="card.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ card.value === null ? "…" : card.value }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <div class="content-grid">
      <!-- 左侧：业务快览 -->
      <div class="content-col">
        <!-- 即将过期资质 -->
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">
                <el-icon><Medal /></el-icon> 即将过期资质
              </span>
              <el-button link type="primary" @click="go('/qualifications')">全部 →</el-button>
            </div>
          </template>
          <div v-loading="expiringLoading">
            <el-table :data="expiringList" size="small" :max-height="280" :show-overflow-tooltip="true">
              <el-table-column prop="name" label="名称" min-width="160" />
              <el-table-column label="公司" width="120">
                <template #default="{ row }">
                  <span>{{ row.company_name || row.supplier_name || "-" }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="expire_date" label="到期日" width="120">
                <template #default="{ row }">
                  <span :class="expireClass(row.expire_date)">{{ row.expire_date || "-" }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="expireTagType(row.expire_date)">
                    {{ expireLabel(row.expire_date) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!expiringLoading && expiringList.length === 0" description="暂无即将过期资质" :image-size="60" />
          </div>
        </el-card>

        <!-- 快捷入口 -->
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">
                <el-icon><Menu /></el-icon> 业务快捷入口
              </span>
            </div>
          </template>
          <div class="quick-grid">
            <div
              v-for="q in quickEntries"
              :key="q.path"
              class="quick-item"
              @click="go(q.path)"
            >
              <el-icon :size="28" :color="q.color"><component :is="q.icon" /></el-icon>
              <span class="quick-label">{{ q.label }}</span>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 右侧：系统状态 -->
      <div class="content-col">
        <!-- AI 服务状态 -->
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">
                <el-icon><Cpu /></el-icon> AI 服务状态
              </span>
              <el-button link type="primary" @click="go('/system/llm')">配置 →</el-button>
            </div>
          </template>
          <div v-loading="aiLoading" class="ai-status-list">
            <div v-for="s in aiStatus" :key="s.key" class="ai-status-item">
              <el-icon :size="18" :color="s.ok ? '#67c23a' : '#f56c6c'">
                <SuccessFilled v-if="s.ok" />
                <CircleCloseFilled v-else />
              </el-icon>
              <span class="ai-name">{{ s.label }}</span>
              <span class="ai-meta">{{ s.detail || (s.ok ? "正常" : "未配置") }}</span>
            </div>
          </div>
        </el-card>

        <!-- 待办和通知 -->
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">
                <el-icon><Bell /></el-icon> 待办与通知
              </span>
              <el-button link type="primary" @click="go('/todos')">全部 →</el-button>
            </div>
          </template>
          <div class="todo-mini-grid">
            <div class="todo-mini" @click="go('/todos')">
              <div class="todo-mini-num">{{ todoCount }}</div>
              <div class="todo-mini-label">待办事项</div>
            </div>
            <div class="todo-mini" @click="go('/notifications')">
              <div class="todo-mini-num">{{ unreadCount }}</div>
              <div class="todo-mini-label">未读通知</div>
            </div>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Plus, Upload, Medal, Menu, Cpu, Bell,
  Briefcase, Files, Box, Reading, EditPen, List,
  SuccessFilled, CircleCloseFilled,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import { listExpiring, listQualifications } from "@/api/qualification";
import { listProducts } from "@/api/product";
import { listKnowledgeBases } from "@/api/knowledge";
import { getLLMHealth } from "@/api/llm";
import { getActiveEmbeddingProvider } from "@/api/embedding";
import { getActiveOCRProvider } from "@/api/ocr";
import { getUnreadCount } from "@/api/notification";
import { getTodos } from "@/api/todo";

const router = useRouter();
const auth = useAuthStore();

function go(path: string) {
  router.push(path);
}

// ---- 问候语 ----
const now = ref(new Date());
const greeting = computed(() => {
  const h = now.value.getHours();
  if (h < 6) return "凌晨好";
  if (h < 12) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});
const todayStr = computed(() => {
  const d = now.value;
  const week = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 · 星期${week}`;
});

// ---- 统计卡片 ----
const projectCount = ref<number | null>(null);
const productCount = ref<number | null>(null);
const qualCount = ref<number | null>(null);
const kbCount = ref<number | null>(null);

const statCards = computed(() => [
  { key: "project", label: "项目数", icon: Briefcase, color: "blue", value: projectCount.value, path: "/projects" },
  { key: "product", label: "产品数", icon: Box, color: "green", value: productCount.value, path: "/products" },
  { key: "qual", label: "资质数", icon: Medal, color: "orange", value: qualCount.value, path: "/qualifications" },
  { key: "kb", label: "知识库", icon: Files, color: "purple", value: kbCount.value, path: "/knowledge/bases" },
]);

// ---- 即将过期资质 ----
const expiringLoading = ref(false);
const expiringList = ref<any[]>([]);

function expireClass(date?: string | null) {
  if (!date) return "";
  const days = daysUntil(date);
  if (days < 0) return "expire-red";
  if (days <= 7) return "expire-red";
  if (days <= 30) return "expire-orange";
  return "";
}

function expireTagType(date?: string | null) {
  const days = daysUntil(date);
  if (days < 0) return "danger" as const;
  if (days <= 7) return "danger" as const;
  if (days <= 30) return "warning" as const;
  return "success" as const;
}

function expireLabel(date?: string | null) {
  const days = daysUntil(date);
  if (days < 0) return "已过期";
  if (days <= 7) return "紧急";
  if (days <= 30) return "预警";
  return "正常";
}

function daysUntil(date: string): number {
  const t = new Date(date).getTime();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((t - today.getTime()) / (24 * 3600 * 1000));
}

// ---- AI 服务状态 ----
const aiLoading = ref(false);
const aiStatus = ref<{ key: string; label: string; ok: boolean; detail?: string }[]>([]);

// ---- 待办/通知 ----
const todoCount = ref(0);
const unreadCount = ref(0);

// ---- 快捷入口 ----
const quickEntries = [
  { path: "/projects", label: "项目管理", icon: Briefcase, color: "#409eff" },
  { path: "/bid-drafts", label: "标书起草", icon: EditPen, color: "#67c23a" },
  { path: "/knowledge/bases", label: "历史知识库", icon: Files, color: "#9c27b0" },
  { path: "/products", label: "产品中心", icon: Box, color: "#ff9800" },
  { path: "/qualifications", label: "资质台账", icon: Medal, color: "#e91e63" },
  { path: "/general-knowledge", label: "通用知识库", icon: Reading, color: "#00bcd4" },
  { path: "/todos", label: "待办看板", icon: List, color: "#3f51b5" },
];

// ---- 数据加载 ----
async function loadStats() {
  // 项目数（后端没有 list 端点暴露在 frontend api，用 0 占位避免阻塞）
  // 暂不调用项目列表接口
  projectCount.value = 0;

  // 产品数
  try {
    const products = await listProducts();
    productCount.value = Array.isArray(products) ? products.length : 0;
  } catch { productCount.value = 0; }

  // 资质数
  try {
    const quals = await listQualifications();
    qualCount.value = Array.isArray(quals) ? quals.length : 0;
  } catch { qualCount.value = 0; }

  // 知识库数
  try {
    const kbs = await listKnowledgeBases();
    kbCount.value = Array.isArray(kbs) ? kbs.length : 0;
  } catch { kbCount.value = 0; }
}

async function loadExpiring() {
  expiringLoading.value = true;
  try {
    const list = await listExpiring(30);
    expiringList.value = (Array.isArray(list) ? list : []).slice(0, 6);
  } catch {
    expiringList.value = [];
  } finally {
    expiringLoading.value = false;
  }
}

async function loadAIStatus() {
  aiLoading.value = true;
  const results: typeof aiStatus.value = [
    { key: "llm", label: "LLM 对话", ok: false },
    { key: "emb", label: "Embedding 向量", ok: false },
    { key: "ocr", label: "OCR 识别", ok: false },
  ];

  // LLM 健康
  try {
    const lh = await getLLMHealth();
    const anyHealthy = Array.isArray(lh) && lh.some((h: any) => h.is_healthy);
    results[0].ok = anyHealthy;
    results[0].detail = anyHealthy ? `${lh.length} 个 provider` : "无健康 provider";
  } catch {
    results[0].detail = "查询失败";
  }

  // Embedding
  try {
    const eb = await getActiveEmbeddingProvider();
    results[1].ok = !!eb?.is_active;
    results[1].detail = eb?.model || (eb?.is_active ? "已启用" : "未启用");
  } catch {
    results[1].detail = "查询失败";
  }

  // OCR
  try {
    const oc = await getActiveOCRProvider();
    results[2].ok = !!oc?.is_active;
    results[2].detail = oc?.name || (oc?.is_active ? "已启用" : "未启用");
  } catch {
    results[2].detail = "查询失败";
  }

  aiStatus.value = results;
  aiLoading.value = false;
}

async function loadTodoNotify() {
  try { unreadCount.value = (await getUnreadCount()).count ?? 0; } catch { /* ignore */ }
  // 待办接口
  try {
    const todos = await getTodos({ status: "pending" });
    todoCount.value = Array.isArray(todos) ? todos.length : 0;
  } catch { /* ignore */ }
}

onMounted(() => {
  loadStats();
  loadExpiring();
  loadAIStatus();
  loadTodoNotify();
});
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 欢迎卡片 */
.welcome-card {
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff 0%, #6366f1 100%);
  color: #fff;
  border: none;
}

.welcome-card :deep(.el-card__body) {
  padding: 20px 24px;
}

.welcome-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.welcome-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: #fff;
}

.welcome-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}

.welcome-actions :deep(.el-button--primary) {
  background-color: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.4);
}

.welcome-actions :deep(.el-button:not(.el-button--primary)) {
  color: #fff;
  background-color: transparent;
  border-color: rgba(255, 255, 255, 0.5);
}

.welcome-actions :deep(.el-button:not(.el-button--primary):hover) {
  background-color: rgba(255, 255, 255, 0.15);
}

/* 统计卡片网格 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  cursor: pointer;
  border-radius: 8px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
}

.stat-card :deep(.el-card__body) {
  padding: 16px 20px;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-icon.blue { background: linear-gradient(135deg, #409eff, #6366f1); }
.stat-icon.green { background: linear-gradient(135deg, #67c23a, #95d475); }
.stat-icon.orange { background: linear-gradient(135deg, #e6a23c, #f0c78a); }
.stat-icon.purple { background: linear-gradient(135deg, #9c27b0, #c084fc); }

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 2px;
}

/* 内容区域 */
.content-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}

.content-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.content-card {
  border-radius: 8px;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}

/* 过期颜色 */
.expire-red { color: #f56c6c; font-weight: 600; }
.expire-orange { color: #e6a23c; }

/* 快捷入口 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 6px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.quick-item:hover {
  background: #f5f7fa;
}

.quick-label {
  font-size: 13px;
  color: #606266;
}

/* AI 状态列表 */
.ai-status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ai-status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.ai-name {
  font-weight: 600;
  color: #303133;
  min-width: 110px;
}

.ai-meta {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
}

/* 待办通知 mini */
.todo-mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.todo-mini {
  background: linear-gradient(135deg, #f5f7fa, #ecf5ff);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s;
}

.todo-mini:hover {
  transform: translateY(-2px);
}

.todo-mini-num {
  font-size: 28px;
  font-weight: 700;
  color: #409eff;
  line-height: 1;
}

.todo-mini-label {
  font-size: 13px;
  color: #606266;
  margin-top: 6px;
}

@media (max-width: 1200px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .content-grid { grid-template-columns: 1fr; }
  .quick-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 768px) {
  .stat-grid { grid-template-columns: 1fr; }
  .quick-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
