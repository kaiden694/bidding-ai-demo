<template>
  <div class="audit-view">
    <!-- 筛选栏 -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input
          v-model="filters.user_id"
          placeholder="用户 ID"
          clearable
          style="width: 200px"
        />
        <el-input
          v-model="filters.action"
          placeholder="操作 action（如 create / update）"
          clearable
          style="width: 220px"
        />
        <el-input
          v-model="filters.resource"
          placeholder="资源类型（如 user / role）"
          clearable
          style="width: 200px"
        />
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          style="width: 380px"
        />
        <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
        <el-button :icon="Refresh" @click="onReset">重置</el-button>
        <el-button
          v-if="auth.hasPermission('audit_log:export')"
          :icon="Download"
          :loading="exporting"
          @click="onExport"
        >
          导出 CSV
        </el-button>
      </div>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table
        v-loading="loading"
        :data="logs"
        border
        stripe
        style="width: 100%"
      >
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="用户" min-width="140">
          <template #default="{ row }">
            <span v-if="row.username">{{ row.username }}</span>
            <span v-else class="muted">{{ row.user_id || "-" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="120">
          <template #default="{ row }">
            <el-tag v-if="row.action" :type="actionTagType(row.action)" size="small">
              {{ row.action }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="资源" min-width="140">
          <template #default="{ row }">{{ row.resource || "-" }}</template>
        </el-table-column>
        <el-table-column label="资源 ID" min-width="180">
          <template #default="{ row }">
            <span v-if="row.resource_id" class="mono">{{ row.resource_id }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="IP" min-width="140">
          <template #default="{ row }">{{ row.ip || "-" }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'success'" type="success" size="small">成功</el-tag>
            <el-tag v-else-if="row.status === 'failed'" type="danger" size="small">失败</el-tag>
            <el-tag v-else-if="row.status" type="warning" size="small">{{ row.status }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.detail || "-" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="loadLogs"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailVisible"
      title="审计日志详情"
      size="540px"
      direction="rtl"
    >
      <div v-if="currentLog" class="detail-body">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">
            {{ formatTime(currentLog.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="用户">
            {{ currentLog.username || currentLog.user_id || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="操作">
            {{ currentLog.action || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="资源">
            {{ currentLog.resource || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="资源 ID">
            {{ currentLog.resource_id || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="IP">
            {{ currentLog.ip || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="User-Agent">
            {{ currentLog.user_agent || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            {{ currentLog.status || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="详情">
            {{ currentLog.detail || "-" }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="json-title">变更前值（before_value）</h4>
        <pre class="json-box">{{ prettyJson(currentLog.before_value) }}</pre>

        <h4 class="json-title">变更后值（after_value）</h4>
        <pre class="json-box">{{ prettyJson(currentLog.after_value) }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Search, Refresh, Download, View } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as systemApi from "@/api/system";
import type { AuditLogItem } from "@/types";

const auth = useAuthStore();

// ---- 筛选 ----
const filters = reactive({
  user_id: "",
  action: "",
  resource: "",
});
const dateRange = ref<[string, string] | null>(null);

// ---- 列表 ----
const loading = ref(false);
const logs = ref<AuditLogItem[]>([]);
const page = ref(1);
const pageSize = ref(50);
const total = ref(0);

/** 后端 list_audit_logs 不返回 total，按返回长度估算 */
function estimateTotal(skip: number, len: number, limit: number) {
  if (len < limit) return skip + len;
  return skip + len + 1;
}

async function loadLogs() {
  loading.value = true;
  try {
    const skip = (page.value - 1) * pageSize.value;
    const params: systemApi.ListAuditLogsParams = {
      skip,
      limit: pageSize.value,
    };
    if (filters.user_id) params.user_id = filters.user_id.trim();
    if (filters.action) params.action = filters.action.trim();
    if (filters.resource) params.resource = filters.resource.trim();
    if (dateRange.value && dateRange.value.length === 2) {
      params.start = dateRange.value[0];
      params.end = dateRange.value[1];
    }
    const data = await systemApi.listAuditLogs(params);
    logs.value = data;
    total.value = estimateTotal(skip, data.length, pageSize.value);
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  page.value = 1;
  loadLogs();
}

function onReset() {
  filters.user_id = "";
  filters.action = "";
  filters.resource = "";
  dateRange.value = null;
  page.value = 1;
  loadLogs();
}

function onSizeChange(size: number) {
  pageSize.value = size;
  page.value = 1;
  loadLogs();
}

// ---- 详情 ----
const detailVisible = ref(false);
const currentLog = ref<AuditLogItem | null>(null);

function openDetail(row: AuditLogItem) {
  currentLog.value = row;
  detailVisible.value = true;
}

// ---- 导出 ----
const exporting = ref(false);

async function onExport() {
  exporting.value = true;
  try {
    const params: {
      user_id?: string;
      action?: string;
      resource?: string;
      start?: string;
      end?: string;
    } = {};
    if (filters.user_id) params.user_id = filters.user_id.trim();
    if (filters.action) params.action = filters.action.trim();
    if (filters.resource) params.resource = filters.resource.trim();
    if (dateRange.value && dateRange.value.length === 2) {
      params.start = dateRange.value[0];
      params.end = dateRange.value[1];
    }
    const blob = await systemApi.exportAuditLogs(params);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const ts = new Date();
    const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}`;
    a.download = `audit_logs_${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    ElMessage.success("导出已开始");
  } finally {
    exporting.value = false;
  }
}

// ---- 工具 ----
function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

function formatTime(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function actionTagType(action: string): "primary" | "success" | "warning" | "danger" {
  const a = action.toLowerCase();
  if (a.includes("create")) return "success";
  if (a.includes("update")) return "primary";
  if (a.includes("delete")) return "danger";
  if (a.includes("login") || a.includes("logout")) return "warning";
  return "primary";
}

function prettyJson(v: any): string {
  if (v === null || v === undefined || v === "") return "-";
  if (typeof v === "string") {
    try {
      return JSON.stringify(JSON.parse(v), null, 2);
    } catch {
      return v;
    }
  }
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

onMounted(() => {
  loadLogs();
});
</script>

<style scoped>
.audit-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.filter-card :deep(.el-card__body),
.table-card :deep(.el-card__body) {
  padding: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pagination-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.mono {
  font-family: "Consolas", "Monaco", monospace;
  font-size: 12px;
}

.detail-body {
  padding: 0 4px;
}

.json-title {
  margin: 16px 0 6px;
  font-size: 13px;
  color: #303133;
}

.json-box {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  font-family: "Consolas", "Monaco", monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 280px;
  overflow: auto;
  margin: 0;
}
</style>
