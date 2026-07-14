<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">项目管理</h2>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="关键字">
        <el-input
          v-model="keyword"
          placeholder="项目名称 / 编码"
          clearable
          style="width: 220px"
          @keyup.enter="onSearch"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-select
          v-model="filterStatus"
          placeholder="全部状态"
          clearable
          style="width: 160px"
          @change="onSearch"
        >
          <el-option
            v-for="s in PROJECT_STATUSES"
            :key="s"
            :label="PROJECT_STATUS_LABELS[s]"
            :value="s"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="Search" @click="onSearch">搜索</el-button>
        <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="projects" border stripe>
      <el-table-column prop="name" label="项目名称" min-width="180" />
      <el-table-column prop="code" label="项目编码" width="140">
        <template #default="{ row }">{{ row.code || "-" }}</template>
      </el-table-column>
      <el-table-column label="当前状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="client_name" label="甲方" min-width="140">
        <template #default="{ row }">{{ row.client_name || "-" }}</template>
      </el-table-column>
      <el-table-column prop="owner" label="负责人" width="100">
        <template #default="{ row }">{{ row.owner || "-" }}</template>
      </el-table-column>
      <el-table-column label="截止日期" width="120">
        <template #default="{ row }">{{ formatDate(row.deadline) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看状态机</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 项目详情 / 状态机侧滑 -->
    <el-drawer
      v-model="detailVisible"
      :title="current?.name ? `状态机 - ${current.name}` : '项目状态机'"
      direction="rtl"
      size="640px"
      :close-on-click-modal="false"
      @close="onDetailClose"
    >
      <div v-loading="detailLoading" v-if="current">
        <!-- 基本信息 -->
        <el-descriptions :column="1" border size="small" class="info-block">
          <el-descriptions-item label="项目编码">{{ current.code || "-" }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">
            <el-tag :type="statusTagType(current.status)" size="small">
              {{ statusLabel(current.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="甲方">{{ current.client_name || "-" }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ current.owner || "-" }}</el-descriptions-item>
          <el-descriptions-item label="截止日期">{{ formatDate(current.deadline) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 状态机流程图 -->
        <div class="section-title">状态机流程</div>
        <el-steps
          :active="currentStatusIndex"
          finish-status="success"
          align-center
          class="status-flow"
        >
          <el-step
            v-for="(s, idx) in PROJECT_STATUSES"
            :key="s"
            :title="PROJECT_STATUS_LABELS[s]"
            :status="stepStatus(s, idx)"
          />
        </el-steps>

        <!-- AI 推荐下一状态 -->
        <div class="section-title">
          <span>AI 推荐下一状态</span>
          <el-button
            link
            type="primary"
            :icon="MagicStick"
            :loading="recommending"
            @click="loadRecommend"
          >重新推荐</el-button>
        </div>
        <el-alert
          v-if="recommend"
          :title="`推荐：${statusLabel(recommend.recommended_status)}`"
          :description="recommend.reason || ''"
          type="success"
          :closable="false"
          show-icon
        />
        <el-empty v-else description="点击「重新推荐」获取 AI 建议" :image-size="40" />

        <!-- 流转按钮 -->
        <div class="section-title">可流转状态</div>
        <div v-loading="nextLoading" class="actions-row">
          <el-button
            v-if="nextStatuses.length === 0"
            disabled
          >无可流转状态</el-button>
          <el-button
            v-for="s in nextStatuses"
            :key="s"
            type="primary"
            plain
            @click="openTransition(s)"
          >
            流转至「{{ statusLabel(s) }}」
          </el-button>
        </div>

        <!-- 流转历史时间线 -->
        <div class="section-title">流转历史</div>
        <el-timeline v-loading="historyLoading">
          <el-timeline-item
            v-for="t in transitions"
            :key="t.id"
            :timestamp="formatTime(t.created_at)"
            placement="top"
          >
            <div class="history-item">
              <span class="history-status">
                <el-tag type="info" size="small">{{ statusLabel(t.from_status) }}</el-tag>
                <el-icon class="arrow"><ArrowRight /></el-icon>
                <el-tag :type="statusTagType(t.to_status)" size="small">
                  {{ statusLabel(t.to_status) }}
                </el-tag>
              </span>
              <div class="history-meta">
                <span>操作人：{{ t.operator_name || "-" }}</span>
                <span v-if="t.reason">原因：{{ t.reason }}</span>
              </div>
            </div>
          </el-timeline-item>
          <el-timeline-item v-if="transitions.length === 0" timestamp="-">
            <span style="color: #909399">暂无流转记录</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>

    <!-- 流转对话框 -->
    <el-dialog
      v-model="transitionDialogVisible"
      title="项目状态流转"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-width="100px">
        <el-form-item label="当前状态">
          <el-tag :type="statusTagType(current?.status || '')" size="small">
            {{ statusLabel(current?.status || "") }}
          </el-tag>
        </el-form-item>
        <el-form-item label="目标状态">
          <el-tag :type="statusTagType(transitionTarget)" size="small">
            {{ statusLabel(transitionTarget) }}
          </el-tag>
        </el-form-item>
        <el-form-item label="流转原因">
          <el-input
            v-model="transitionReason"
            type="textarea"
            :rows="3"
            placeholder="请输入流转原因（选填）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="transitionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="transitioning" @click="onSubmitTransition">
          确认流转
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import {
  Refresh,
  RefreshLeft,
  Search,
  ArrowRight,
  MagicStick,
} from "@element-plus/icons-vue";
import * as projectApi from "@/api/project";
import {
  PROJECT_STATUSES,
  PROJECT_STATUS_LABELS,
  PROJECT_STATUS_TAG_TYPES,
  type ProjectItem,
  type ProjectTransition,
} from "@/types";

// ---- 列表 ----
const loading = ref(false);
const projects = ref<ProjectItem[]>([]);
const keyword = ref("");
const filterStatus = ref<string | undefined>(undefined);

async function loadList() {
  loading.value = true;
  try {
    const params: projectApi.ListProjectsParams = {};
    if (keyword.value) params.keyword = keyword.value;
    if (filterStatus.value) params.status = filterStatus.value;
    projects.value = await projectApi.listProjects(params);
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  loadList();
}

function onReset() {
  keyword.value = "";
  filterStatus.value = undefined;
  loadList();
}

// ---- 状态机详情 ----
const detailVisible = ref(false);
const detailLoading = ref(false);
const current = ref<ProjectItem | null>(null);
const transitions = ref<ProjectTransition[]>([]);
const historyLoading = ref(false);
const nextStatuses = ref<string[]>([]);
const nextLoading = ref(false);
const recommend = ref<{ recommended_status: string; reason?: string } | null>(null);
const recommending = ref(false);

const currentStatusIndex = computed(() => {
  if (!current.value) return 0;
  return PROJECT_STATUSES.indexOf(current.value.status as any);
});

function statusLabel(s: string | null): string {
  if (!s) return "-";
  return PROJECT_STATUS_LABELS[s] || s;
}

function statusTagType(s: string) {
  return PROJECT_STATUS_TAG_TYPES[s] || "info";
}

/** el-step 状态：当前状态高亮为 process */
function stepStatus(s: string, _idx: number): "wait" | "process" | "success" | "error" | "finish" {
  if (!current.value) return "wait";
  if (s === current.value.status) return "process";
  const currentIdx = PROJECT_STATUSES.indexOf(current.value.status as any);
  const thisIdx = PROJECT_STATUSES.indexOf(s as any);
  if (currentIdx >= 0 && thisIdx >= 0 && thisIdx < currentIdx) return "success";
  return "wait";
}

async function openDetail(row: ProjectItem) {
  current.value = row;
  detailVisible.value = true;
  detailLoading.value = true;
  transitions.value = [];
  nextStatuses.value = [];
  recommend.value = null;
  try {
    await Promise.all([
      loadTransitions(row.id),
      loadNextStatuses(row.id),
      loadRecommend(row.id),
    ]);
  } finally {
    detailLoading.value = false;
  }
}

async function loadTransitions(id: string) {
  historyLoading.value = true;
  try {
    transitions.value = await projectApi.getProjectTransitions(id);
  } finally {
    historyLoading.value = false;
  }
}

async function loadNextStatuses(id: string) {
  nextLoading.value = true;
  try {
    nextStatuses.value = await projectApi.getProjectNextStatuses(id);
  } finally {
    nextLoading.value = false;
  }
}

async function loadRecommend(id?: string) {
  const pid = id || current.value?.id;
  if (!pid) return;
  recommending.value = true;
  try {
    recommend.value = await projectApi.recommendNextStatus(pid);
  } finally {
    recommending.value = false;
  }
}

function onDetailClose() {
  current.value = null;
  transitions.value = [];
  nextStatuses.value = [];
  recommend.value = null;
}

// ---- 流转对话框 ----
const transitionDialogVisible = ref(false);
const transitionTarget = ref<string>("");
const transitionReason = ref<string>("");
const transitioning = ref(false);

function openTransition(target: string) {
  transitionTarget.value = target;
  transitionReason.value = "";
  transitionDialogVisible.value = true;
}

async function onSubmitTransition() {
  if (!current.value) return;
  transitioning.value = true;
  try {
    await projectApi.transitionProject(current.value.id, {
      to_status: transitionTarget.value,
      reason: transitionReason.value || undefined,
    });
    ElMessage.success(`已流转至「${statusLabel(transitionTarget.value)}」`);
    transitionDialogVisible.value = false;
    // 刷新详情
    current.value = { ...current.value, status: transitionTarget.value };
    await Promise.all([
      loadTransitions(current.value.id),
      loadNextStatuses(current.value.id),
      loadRecommend(current.value.id),
    ]);
    // 同时刷新列表
    loadList();
  } finally {
    transitioning.value = false;
  }
}

// ---- 工具 ----
function formatTime(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDate(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

onMounted(() => {
  loadList();
});
</script>

<style scoped>
.page-container {
  padding: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.page-title {
  margin: 0;
  font-size: 18px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.filter-bar {
  margin-bottom: 12px;
}
.info-block {
  margin-bottom: 16px;
}
.section-title {
  font-weight: 600;
  margin: 16px 0 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-flow {
  padding: 12px 0;
  flex-wrap: wrap;
}
.actions-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.history-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.history-status {
  display: flex;
  align-items: center;
  gap: 6px;
}
.arrow {
  color: #909399;
}
.history-meta {
  font-size: 12px;
  color: #909399;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
:deep(.el-steps) {
  flex-wrap: wrap;
}
:deep(.el-step__main) {
  white-space: normal;
}
</style>
