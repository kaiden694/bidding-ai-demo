<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">待办看板</h2>
      <div class="header-actions">
        <el-button
          v-if="auth.hasPermission('todo:create')"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >新建待办</el-button>
        <el-button :icon="Refresh" @click="loadTodos">刷新</el-button>
      </div>
    </div>

    <div v-loading="loading" class="kanban">
      <div
        v-for="col in columns"
        :key="col.value"
        class="kanban-column"
      >
        <div class="column-header">
          <span class="column-title">{{ col.label }}</span>
          <el-tag size="small" round>{{ columnTodos(col.value).length }}</el-tag>
        </div>
        <div class="column-body">
          <el-empty
            v-if="columnTodos(col.value).length === 0"
            description="暂无待办"
            :image-size="50"
          />
          <el-card
            v-for="todo in columnTodos(col.value)"
            :key="todo.id"
            shadow="hover"
            class="todo-card"
            :class="{ overdue: isOverdue(todo) }"
          >
            <div class="todo-title">{{ todo.title }}</div>
            <div class="todo-desc" v-if="todo.description">{{ todo.description }}</div>
            <div class="todo-meta">
              <el-tag v-if="todo.priority" size="small" :type="priorityTag(todo.priority)">
                {{ priorityLabel(todo.priority) }}
              </el-tag>
              <span class="meta-item">
                <el-icon><Calendar /></el-icon>
                {{ formatDate(todo.due_date) }}
              </span>
              <span v-if="todo.assignee" class="meta-item">
                <el-icon><User /></el-icon>
                {{ todo.assignee }}
              </span>
            </div>
            <div class="todo-actions">
              <el-button
                v-if="auth.hasPermission('todo:update')"
                link
                type="primary"
                size="small"
                @click="openStatusSelect(todo)"
              >切换状态</el-button>
              <el-button
                v-if="auth.hasPermission('todo:update')"
                link
                type="warning"
                size="small"
                @click="openEdit(todo)"
              >编辑</el-button>
            </div>
          </el-card>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="formDialogVisible"
      :title="editing ? '编辑待办' : '新建待办'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="请输入待办标题" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width: 100%">
                <el-option
                  v-for="c in columns"
                  :key="c.value"
                  :label="c.label"
                  :value="c.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-select v-model="form.priority" clearable style="width: 100%">
                <el-option
                  v-for="opt in priorityOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="截止日期">
              <el-date-picker
                v-model="form.due_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-input v-model="form.assignee" placeholder="负责人" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="formDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 切换状态对话框 -->
    <el-dialog
      v-model="statusDialogVisible"
      title="切换状态"
      width="360px"
      :close-on-click-modal="false"
    >
      <el-form label-width="80px">
        <el-form-item label="待办">{{ currentTodo?.title }}</el-form-item>
        <el-form-item label="状态">
          <el-select v-model="targetStatus" style="width: 100%">
            <el-option
              v-for="c in columns"
              :key="c.value"
              :label="c.label"
              :value="c.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="switching" @click="onSwitchStatus">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { Plus, Refresh, Calendar, User } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as todoApi from "@/api/todo";
import type { TodoItem } from "@/types";

const auth = useAuthStore();

// 看板列定义
const columns = [
  { value: "pending", label: "待办" },
  { value: "in_progress", label: "进行中" },
  { value: "done", label: "已完成" },
];

const priorityOptions = [
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
  { value: "urgent", label: "紧急" },
];

function priorityLabel(v: string | null): string {
  if (!v) return "";
  return priorityOptions.find((o) => o.value === v)?.label || v;
}

function priorityTag(v: string): "info" | "warning" | "danger" {
  if (v === "urgent") return "danger";
  if (v === "high") return "danger";
  if (v === "medium") return "warning";
  return "info";
}

// ---- 列表 ----
const loading = ref(false);
const todos = ref<TodoItem[]>([]);

async function loadTodos() {
  loading.value = true;
  try {
    todos.value = await todoApi.getTodos();
  } finally {
    loading.value = false;
  }
}

function columnTodos(status: string): TodoItem[] {
  return todos.value.filter((t) => t.status === status);
}

/** 是否已过期：截止日期早于今天且未完成 */
function isOverdue(todo: TodoItem): boolean {
  if (!todo.due_date || todo.status === "done") return false;
  const due = new Date(todo.due_date);
  if (isNaN(due.getTime())) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return due.getTime() < today.getTime();
}

// ---- 新建 / 编辑 ----
const formDialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<TodoItem | null>(null);
const formRef = ref<FormInstance | null>(null);

const form = reactive({
  title: "",
  description: "",
  status: "pending",
  priority: "medium" as string | null,
  assignee: "",
  due_date: "" as string | null,
});

const rules: FormRules = {
  title: [{ required: true, message: "请输入待办标题", trigger: "blur" }],
};

function resetForm() {
  form.title = "";
  form.description = "";
  form.status = "pending";
  form.priority = "medium";
  form.assignee = "";
  form.due_date = null;
}

function openCreate() {
  editing.value = null;
  resetForm();
  formDialogVisible.value = true;
}

function openEdit(row: TodoItem) {
  editing.value = row;
  form.title = row.title;
  form.description = row.description || "";
  form.status = row.status;
  form.priority = row.priority;
  form.assignee = row.assignee || "";
  form.due_date = row.due_date;
  formDialogVisible.value = true;
}

async function onSubmit() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    const payload: Partial<TodoItem> = {
      title: form.title,
      description: form.description || undefined,
      status: form.status,
      priority: form.priority || undefined,
      assignee: form.assignee || undefined,
      due_date: form.due_date || undefined,
    };
    if (editing.value) {
      await todoApi.updateTodo(editing.value.id, payload);
      ElMessage.success("已更新");
    } else {
      await todoApi.createTodo(payload);
      ElMessage.success("已创建");
    }
    formDialogVisible.value = false;
    loadTodos();
  } finally {
    submitting.value = false;
  }
}

// ---- 切换状态 ----
const statusDialogVisible = ref(false);
const currentTodo = ref<TodoItem | null>(null);
const targetStatus = ref<string>("pending");
const switching = ref(false);

function openStatusSelect(todo: TodoItem) {
  currentTodo.value = todo;
  targetStatus.value = todo.status;
  statusDialogVisible.value = true;
}

async function onSwitchStatus() {
  if (!currentTodo.value) return;
  switching.value = true;
  try {
    await todoApi.updateTodo(currentTodo.value.id, { status: targetStatus.value });
    ElMessage.success("状态已切换");
    statusDialogVisible.value = false;
    loadTodos();
  } finally {
    switching.value = false;
  }
}

// ---- 工具 ----
function formatDate(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

onMounted(() => {
  loadTodos();
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
.kanban {
  display: flex;
  gap: 12px;
  min-height: 60vh;
}
.kanban-column {
  flex: 1;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
}
.column-header {
  padding: 12px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.column-body {
  padding: 8px;
  overflow-y: auto;
  flex: 1;
  max-height: 70vh;
}
.todo-card {
  margin-bottom: 8px;
}
.todo-card.overdue {
  border: 1px solid #f56c6c;
}
.todo-card.overdue :deep(.el-card__body) {
  background: #fef0f0;
}
.todo-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.todo-desc {
  font-size: 12px;
  color: #606266;
  margin-bottom: 6px;
}
.todo-meta {
  font-size: 12px;
  color: #909399;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.todo-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  border-top: 1px dashed #ebeef5;
  padding-top: 6px;
}
</style>
