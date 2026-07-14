<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">历史知识库</h2>
      <div class="header-actions">
        <el-button
          v-if="auth.hasPermission('knowledge:create')"
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
          style="width: 160px"
          @change="loadList"
        >
          <el-option label="标书" value="标书" />
          <el-option label="合同" value="合同" />
          <el-option label="经验" value="经验" />
          <el-option label="范本" value="范本" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select
          v-model="filterActive"
          placeholder="全部"
          clearable
          style="width: 140px"
          @change="loadList"
        >
          <el-option label="启用" :value="true" />
          <el-option label="停用" :value="false" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" width="100">
        <template #default="{ row }">
          <span>{{ row.category || "-" }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="160">
        <template #default="{ row }">
          <el-tag
            v-for="(t, i) in row.tags || []"
            :key="i"
            size="small"
            style="margin-right: 4px"
          >{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="400" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.hasPermission('knowledge:create')"
            size="small"
            :icon="Edit"
            @click="openEdit(row)"
          >编辑</el-button>
          <el-upload
            v-if="auth.hasPermission('knowledge:create')"
            :show-file-list="false"
            :http-request="buildImportHandler(row)"
            accept=".zip"
          >
            <el-button
              size="small"
              :icon="Upload"
              :loading="importingId === row.id"
            >导入ZIP</el-button>
          </el-upload>
          <el-button
            v-if="auth.hasPermission('knowledge:create')"
            size="small"
            :icon="RefreshRight"
            :loading="reindexingId === row.id"
            @click="handleReindex(row)"
          >重建索引</el-button>
          <el-button
            v-if="auth.hasPermission('knowledge:view')"
            size="small"
            @click="openChunks(row)"
          >切块</el-button>
          <el-button
            v-if="auth.hasPermission('knowledge:create') && !row.is_active"
            size="small"
            type="warning"
            @click="handleSwitchVersion(row)"
          >设为当前版本</el-button>
          <el-button
            v-if="auth.hasPermission('knowledge:create')"
            size="small"
            type="danger"
            :icon="Delete"
            @click="handleDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'edit' ? '编辑知识库' : '新建知识库'"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" placeholder="请选择" clearable style="width: 100%">
            <el-option label="标书" value="标书" />
            <el-option label="合同" value="合同" />
            <el-option label="经验" value="经验" />
            <el-option label="范本" value="范本" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dialogMode === 'create'" label="版本">
          <el-input v-model="form.version" placeholder="1.0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
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

    <!-- 切块管理抽屉 -->
    <el-drawer
      v-model="chunksDrawer"
      :title="`切块管理 - ${currentKb?.name || ''}`"
      size="60%"
    >
      <div v-loading="chunksLoading">
        <div style="margin-bottom: 12px">
          <el-button size="small" :icon="Refresh" @click="loadChunks">刷新</el-button>
          <span style="margin-left: 8px; color: #909399; font-size: 12px">
            标签以 JSON 对象编辑，保存后写入 metadata_json.tags
          </span>
        </div>
        <el-table :data="chunks" border>
          <el-table-column type="index" width="50" />
          <el-table-column prop="title" label="标题" width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.title || "-" }}</template>
          </el-table-column>
          <el-table-column prop="content" label="内容" min-width="220" show-overflow-tooltip />
          <el-table-column prop="page_number" label="页码" width="70">
            <template #default="{ row }">{{ row.page_number ?? "-" }}</template>
          </el-table-column>
          <el-table-column label="标签(JSON)" min-width="240">
            <template #default="{ row }">
              <el-input
                v-model="row._tagsJson"
                type="textarea"
                :rows="2"
                placeholder='{"key":"value"}'
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                type="primary"
                :loading="row._saving"
                @click="saveChunkTags(row)"
              >保存</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>

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
  Edit,
  Delete,
  Upload,
  Refresh,
  RefreshRight,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as knowledgeApi from "@/api/knowledge";
import type { KnowledgeBase, KnowledgeChunk, ImportStatus } from "@/types";

const auth = useAuthStore();

// ---- 列表 ----
const loading = ref(false);
const list = ref<KnowledgeBase[]>([]);
const filterCategory = ref<string | undefined>(undefined);
const filterActive = ref<boolean | undefined>(undefined);

async function loadList() {
  loading.value = true;
  try {
    const params: { category?: string; is_active?: boolean } = {};
    if (filterCategory.value) params.category = filterCategory.value;
    if (filterActive.value !== undefined) params.is_active = filterActive.value;
    list.value = await knowledgeApi.listKnowledgeBases(params);
  } finally {
    loading.value = false;
  }
}

// ---- 新建/编辑 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<string | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  description: "",
  category: "" as string,
  version: "1.0",
  is_active: true,
  tagsText: "",
});
const rules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

function resetForm() {
  form.name = "";
  form.description = "";
  form.category = "";
  form.version = "1.0";
  form.is_active = true;
  form.tagsText = "";
  editingId.value = null;
}

function openCreate() {
  dialogMode.value = "create";
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: KnowledgeBase) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  form.name = row.name;
  form.description = row.description || "";
  form.category = row.category || "";
  form.version = row.version;
  form.is_active = row.is_active;
  form.tagsText = (row.tags || []).join(",");
  dialogVisible.value = true;
}

function parseTags(text: string): any[] {
  return text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

async function handleSubmit() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    if (dialogMode.value === "create") {
      await knowledgeApi.createKnowledgeBase({
        name: form.name,
        description: form.description || undefined,
        category: form.category || undefined,
        version: form.version || "1.0",
        is_active: form.is_active,
        tags: parseTags(form.tagsText),
      });
      ElMessage.success("创建成功");
    } else if (editingId.value) {
      await knowledgeApi.updateKnowledgeBase(editingId.value, {
        name: form.name,
        description: form.description || undefined,
        category: form.category || undefined,
        is_active: form.is_active,
        tags: parseTags(form.tagsText),
      });
      ElMessage.success("更新成功");
    }
    dialogVisible.value = false;
    loadList();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: KnowledgeBase) {
  await ElMessageBox.confirm(`确定删除知识库「${row.name}」吗？`, "提示", {
    type: "warning",
  });
  await knowledgeApi.deleteKnowledgeBase(row.id);
  ElMessage.success("已删除");
  loadList();
}

// ---- 批量导入 ----
const importingId = ref<string | null>(null);

function buildImportHandler(row: KnowledgeBase) {
  return async (options: any) => {
    const file = options.file as File;
    importingId.value = row.id;
    try {
      await knowledgeApi.batchImport(row.id, file, false);
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
const currentKb = ref<KnowledgeBase | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function fetchProgress(kbId: string) {
  progress.value = await knowledgeApi.getImportStatus(kbId, false);
}

function openProgress(row: KnowledgeBase) {
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

async function handleReindex(row: KnowledgeBase) {
  await ElMessageBox.confirm(
    `确定对「${row.name}」重建索引吗？该操作会重新生成所有切块的 Embedding。`,
    "重建索引",
    { type: "warning" },
  );
  reindexingId.value = row.id;
  try {
    await knowledgeApi.reindex(row.id, false);
    ElMessage.success("重建任务已提交");
    openProgress(row);
  } finally {
    reindexingId.value = null;
  }
}

async function handleSwitchVersion(row: KnowledgeBase) {
  await knowledgeApi.switchVersion(row.id, false);
  ElMessage.success("已切换为当前版本");
  loadList();
}

// ---- 切块标签管理 ----
interface ChunkRow extends KnowledgeChunk {
  _tagsJson: string;
  _saving: boolean;
}

const chunksDrawer = ref(false);
const chunksLoading = ref(false);
const chunks = ref<ChunkRow[]>([]);

async function openChunks(row: KnowledgeBase) {
  currentKb.value = row;
  chunksDrawer.value = true;
  await loadChunks();
}

async function loadChunks() {
  if (!currentKb.value) return;
  chunksLoading.value = true;
  try {
    const data = await knowledgeApi.listChunks(currentKb.value.id, {
      is_general: false,
      limit: 200,
      offset: 0,
    });
    chunks.value = data.map((c) => {
      const tagsObj = (c.metadata_json?.tags as Record<string, any>) || c.tags || {};
      return {
        ...c,
        _tagsJson: JSON.stringify(tagsObj, null, 2),
        _saving: false,
      };
    });
  } finally {
    chunksLoading.value = false;
  }
}

async function saveChunkTags(row: ChunkRow) {
  let parsed: Record<string, any>;
  try {
    parsed = row._tagsJson.trim() ? JSON.parse(row._tagsJson) : {};
  } catch {
    ElMessage.error("标签 JSON 格式错误");
    return;
  }
  row._saving = true;
  try {
    await knowledgeApi.updateChunkTags(row.id, parsed, false);
    ElMessage.success("标签已更新");
  } finally {
    row._saving = false;
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
