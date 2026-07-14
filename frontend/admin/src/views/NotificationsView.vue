<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">通知中心</h2>
      <div class="header-actions">
        <el-button
          v-if="unreadCount > 0"
          type="primary"
          :icon="Check"
          :loading="markingAll"
          @click="onMarkAllRead"
        >全部标记已读</el-button>
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="状态">
        <el-radio-group v-model="filter" @change="onFilterChange">
          <el-radio-button label="all">全部</el-radio-button>
          <el-radio-button label="unread">未读</el-radio-button>
          <el-radio-button label="read">已读</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item>
        <span class="unread-tip" v-if="unreadCount > 0">
          有 <strong>{{ unreadCount }}</strong> 条未读通知
        </span>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="notifications" border stripe>
      <el-table-column label="标题" min-width="180">
        <template #default="{ row }">
          <div class="noti-title" :class="{ unread: !row.is_read }">
            <el-badge v-if="!row.is_read" is-dot class="dot-badge">
              <span>{{ row.title }}</span>
            </el-badge>
            <span v-else>{{ row.title }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">{{ row.content || "-" }}</template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small">{{ typeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_read" type="info" size="small">已读</el-tag>
          <el-tag v-else type="danger" size="small">未读</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="!row.is_read"
            link
            type="primary"
            @click="onMarkRead(row)"
          >标记已读</el-button>
          <el-button
            v-if="row.entity_type && row.entity_id"
            link
            type="primary"
            @click="goEntity(row)"
          >查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadList"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Check, Refresh } from "@element-plus/icons-vue";
import * as notifApi from "@/api/notification";
import type { NotificationItem } from "@/types";

const router = useRouter();

// ---- 列表 ----
const loading = ref(false);
const notifications = ref<NotificationItem[]>([]);
const filter = ref<"all" | "unread" | "read">("all");
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);

const unreadCount = ref(0);
const markingAll = ref(false);

function estimateTotal(skip: number, len: number, limit: number) {
  if (len < limit) return skip + len;
  return skip + len + 1;
}

async function loadList() {
  loading.value = true;
  try {
    const skip = (page.value - 1) * pageSize.value;
    const params: notifApi.ListNotificationsParams = {
      limit: pageSize.value,
      offset: skip,
    };
    if (filter.value === "unread") params.is_read = false;
    if (filter.value === "read") params.is_read = true;
    const data = await notifApi.getNotifications(params);
    notifications.value = data;
    total.value = estimateTotal(skip, data.length, pageSize.value);
    await loadUnreadCount();
  } finally {
    loading.value = false;
  }
}

async function loadUnreadCount() {
  try {
    const res = await notifApi.getUnreadCount();
    unreadCount.value = res.count ?? 0;
  } catch {
    // 忽略
  }
}

function onFilterChange() {
  page.value = 1;
  loadList();
}

function onSizeChange(size: number) {
  pageSize.value = size;
  page.value = 1;
  loadList();
}

async function onMarkRead(row: NotificationItem) {
  await notifApi.markRead(row.id);
  row.is_read = true;
  unreadCount.value = Math.max(0, unreadCount.value - 1);
  ElMessage.success("已标记已读");
}

async function onMarkAllRead() {
  markingAll.value = true;
  try {
    await notifApi.markAllRead();
    ElMessage.success("全部已标记已读");
    await loadList();
  } finally {
    markingAll.value = false;
  }
}

/** 点击通知跳转相关实体 */
function goEntity(row: NotificationItem) {
  if (!row.entity_type || !row.entity_id) return;
  // 根据实体类型路由到对应详情页
  const map: Record<string, string> = {
    project: "/projects",
    todo: "/todos",
    bid_draft: "/bid-drafts",
  };
  const target = map[row.entity_type];
  if (target) {
    router.push(target);
  } else {
    ElMessage.info(`实体类型：${row.entity_type}（${row.entity_id}）`);
  }
}

// ---- 工具 ----
function typeLabel(t: string): string {
  const m: Record<string, string> = {
    info: "信息",
    warning: "警告",
    error: "错误",
    success: "成功",
    todo: "待办",
    project: "项目",
    bid: "标书",
    contract: "合同",
  };
  return m[t] || t || "-";
}

function formatTime(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
.unread-tip {
  color: #e6a23c;
  font-size: 13px;
}
.noti-title.unread {
  font-weight: 600;
}
.dot-badge {
  vertical-align: baseline;
}
.pagination-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
