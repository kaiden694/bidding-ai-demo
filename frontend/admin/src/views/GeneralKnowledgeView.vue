<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">通用知识库</h2>
      <div class="header-actions">
        <el-button
          v-if="auth.hasPermission('general_knowledge:create')"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >新建知识库</el-button>
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="分类">
        <el-select
          v-model="filterCategory"
          placeholder="全部"
          clearable
          style="width: 170px"
          @change="loadList"
        >
          <el-option
            v-for="opt in categoryOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="可见范围">
        <el-select
          v-model="filterVisibility"
          placeholder="全部"
          clearable
          style="width: 140px"
          @change="loadList"
        >
          <el-option label="全部" value="all" />
          <el-option label="前台" value="front" />
          <el-option label="后台" value="back" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.description || "-" }}</template>
      </el-table-column>
      <el-table-column label="分类" width="120">
        <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
      </el-table-column>
      <el-table-column label="可见范围" width="100">
        <template #default="{ row }">
          <el-tag :type="visibilityTagType(row.visibility)" size="small">
            {{ visibilityLabel(row.visibility) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="发布状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
            {{ row.is_published ? "已发布" : "未发布" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="340" fixed="right">
        <template #default="{ row }">
          <el-upload
            v-if="auth.hasPermission('general_knowledge:create')"
            :show-file-list="false"
            :http-request="buildImportHandler(row)"
            accept=".zip"
          >
            <el-button size="small" :icon="Upload" :loading="importingId === row.id">
              导入ZIP
            </el-button>
          </el-upload>
          <el-button
            v-if="auth.hasPermission('general_knowledge:create')"
            size="small"
            :icon="RefreshRight"
            :loading="reindexingId === row.id"
            @click="handleReindex(row)"
          >重建索引</el-button>
          <el-button
            v-if="auth.hasPermission('general_knowledge:view')"
            size="small"
            @click="openProgress(row)"
          >查看进度</el-button>
          <el-button
            v-if="auth.hasPermission('general_knowledge:create')"
            size="small"
            type="danger"
            :icon="Delete"
            @click="handleDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建对话框 -->
    <el-dialog v-model="dialogVisible" title="新建通用知识库" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" style="width: 100%">
            <el-option
              v-for="opt in categoryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="可见范围">
          <el-select v-model="form.visibility" style="width: 100%">
            <el-option label="全部" value="all" />
            <el-option label="前台" value="front" />
            <el-option label="后台" value="back" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tagsText" placeholder="多个标签用逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 进度对话框 -->
    <el-dialog
      v-model="progressVisible"
      title="处理进度"
      width="480px"
      :close-on-click-modal="false"
      @close="stopPolling"
    >
      <div v-loading="progressLoading">
        <p>知识库：{{ currentKb?.name || "-" }}</p>
        <p>状态：{{ progress?.status || "-" }}</p>
        <p v-if="progress?.total != null">
          进度：{{ progress.processed ?? 0 }} / {{ progress.total }}
        </p>
        <p v-if="progress?.message">{{ progress.message }}</p>
        <el-progress
          v-if="progress?.total"
          :percentage="Math.round(((progress.processed ?? 0) / progress.total) * 100)"
        />
      </div>
      <template #footer>
        <el-button @click="progressVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount } from "vue";
import { ElMessage, ElMessageBox, type FormInstance } from "element-plus";
import {
  Plus,
  Delete,
  Upload,
  Refresh,
  RefreshRight,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as gkApi from "@/api/generalKnowledge";
import type { GeneralKnowledgeBase, ImportStatus } from "@/types";

const auth = useAuthStore();

const categoryOptions = [
  { label: "企业资料", value: "company" },
  { label: "政策法规", value: "policy" },
  { label: "行业标准", value: "standard" },
  { label: "内部规范", value: "regulation" },
  { label: "常见问题", value: "faq" },
  { label: "其他", value: "other" },
];

function categoryLabel(v: string): string {
  return categoryOptions.find((o) => o.value === v)?.label || v || "-";
}

function visibilityLabel(v: string): string {
  const m: Record<string, string> = { all: "全部", front: "前台", back: "后台" };
  return m[v] || v;
}

function visibilityTagType(v: string): "success" | "warning" | "info" {
  if (v === "all") return "success";
  if (v === "front") return "warning";
  return "info";
}

// ---- 列表 ----
const loading = ref(false);
const list = ref<GeneralKnowledgeBase[]>([]);
const filterCategory = ref<string | undefined>(undefined);
const filterVisibility = ref<string | undefined>(undefined);

async function loadList() {
  loading.value = true;
  try {
    const params: { category?: string; visibility?: string } = {};
    if (filterCategory.value) params.category = filterCategory.value;
    if (filterVisibility.value) params.visibility = filterVisibility.value;
    list.value = await gkApi.listGeneralKnowledge(params);
  } finally {
    loading.value = false;
  }
}

// ---- 新建 ----
const dialogVisible = ref(false);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  description: "",
  category: "other",
  visibility: "all",
  tagsText: "",
});
const rules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

function openCreate() {
  form.name = "";
  form.description = "";
  form.category = "other";
  form.visibility = "all";
  form.tagsText = "";
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    const tags = form.tagsText
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    await gkApi.createGeneralKnowledge({
      name: form.name,
      description: form.description || undefined,
      category: form.category,
      visibility: form.visibility,
      tags: tags.length ? tags : undefined,
    });
    ElMessage.success("创建成功");
    dialogVisible.value = false;
    loadList();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: GeneralKnowledgeBase) {
  await ElMessageBox.confirm(`确定删除知识库「${row.name}」吗？`, "提示", {
    type: "warning",
  });
  await gkApi.deleteGeneralKnowledge(row.id);
  ElMessage.success("已删除");
  loadList();
}

// ---- 批量导入 ----
const importingId = ref<string | null>(null);

function buildImportHandler(row: GeneralKnowledgeBase) {
  return async (options: any) => {
    const file = options.file as File;
    importingId.value = row.id;
    try {
      await gkApi.batchImport(row.id, file);
      ElMessage.success("导入任务已提交");
      loadList();
      openProgress(row);
    } finally {
      importingId.value = null;
    }
  };
}

// ---- 索引重建 + 进度查询 ----
const reindexingId = ref<string | null>(null);
const progressVisible = ref(false);
const progressLoading = ref(false);
const progress = ref<ImportStatus | null>(null);
const currentKb = ref<GeneralKnowledgeBase | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function fetchProgress(kbId: string) {
  progress.value = await gkApi.getImportStatus(kbId);
}

function openProgress(row: GeneralKnowledgeBase) {
  currentKb.value = row;
  progress.value = null;
  progressLoading.value = true;
  progressVisible.value = true;
  fetchProgress(row.id).finally(() => {
    progressLoading.value = false;
  });
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      await fetchProgress(row.id);
      if (
        progress.value &&
        ["completed", "failed", "done", "success"].includes(progress.value.status)
      ) {
        stopPolling();
        loadList();
      }
    } catch {
      stopPolling();
    }
  }, 2000);
}

async function handleReindex(row: GeneralKnowledgeBase) {
  await ElMessageBox.confirm(
    `确定对「${row.name}」重建索引吗？该操作会重新生成所有切块的 Embedding。`,
    "重建索引",
    { type: "warning" },
  );
  reindexingId.value = row.id;
  try {
    await gkApi.reindex(row.id);
    ElMessage.success("重建任务已提交");
    openProgress(row);
  } finally {
    reindexingId.value = null;
  }
}

// ---- 工具 ----
function formatTime(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

onMounted(() => {
  loadList();
});

onBeforeUnmount(() => {
  stopPolling();
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
:deep(.el-table .el-button + .el-button) {
  margin-left: 6px;
}
</style>
