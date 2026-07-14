<template>
  <div class="roles-view">
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索角色 code / 名称"
          clearable
          style="width: 260px"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button
          v-if="auth.hasPermission('role:create')"
          type="primary"
          :icon="Plus"
          @click="openCreateDialog"
        >
          新建角色
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="filteredRoles" border stripe style="width: 100%">
        <el-table-column prop="code" label="角色 Code" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || "-" }}</template>
        </el-table-column>
        <el-table-column label="类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_system" type="warning">系统内置</el-tag>
            <el-tag v-else type="success">自定义</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('role:update')"
              link
              type="primary"
              :icon="Edit"
              @click="openEditDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('role:assign_permissions')"
              link
              type="primary"
              :icon="Setting"
              @click="openPermDialog(row)"
            >
              分配权限
            </el-button>
            <el-button
              v-if="auth.hasPermission('role:update') && !row.is_system"
              link
              type="danger"
              :icon="Delete"
              @click="onDelete(row)"
            >
              删除
            </el-button>
            <el-tooltip
              v-else-if="row.is_system"
              content="系统内置角色不可删除"
              placement="top"
            >
              <el-button link type="info" :icon="Delete" disabled>删除</el-button>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑 对话框 -->
    <el-dialog
      v-model="formDialogVisible"
      :title="editingRole ? '编辑角色' : '新建角色'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="80px"
      >
        <el-form-item label="Code" prop="code">
          <el-input
            v-model="formData.code"
            :disabled="!!editingRole"
            placeholder="如 admin / auditor"
          />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="formData.name" placeholder="角色显示名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="选填"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitForm">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 权限分配对话框 -->
    <el-dialog
      v-model="permDialogVisible"
      title="分配权限"
      width="560px"
      :close-on-click-modal="false"
      @open="onPermDialogOpen"
    >
      <div v-loading="permLoading">
        <p class="perm-tip">
          当前角色：<b>{{ permRole?.name }}</b>
          <span class="muted">（按模块分组，勾选父节点会自动勾选/取消其子节点）</span>
        </p>
        <el-tree
          ref="permTreeRef"
          :data="permTreeData"
          :props="permTreeProps"
          node-key="id"
          show-checkbox
          default-expand-all
          :check-strictly="false"
          style="max-height: 420px; overflow: auto"
        />
      </div>
      <template #footer>
        <el-button @click="permDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitPerms">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import { Plus, Edit, Delete, Search, Setting } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as systemApi from "@/api/system";
import type { RoleOut, PermissionGroup, Permission } from "@/types";

const auth = useAuthStore();

// ---- 列表 ----
const loading = ref(false);
const roles = ref<RoleOut[]>([]);
const keyword = ref("");

const filteredRoles = computed<RoleOut[]>(() => {
  const kw = keyword.value.trim().toLowerCase();
  if (!kw) return roles.value;
  return roles.value.filter(
    (r) =>
      r.code.toLowerCase().includes(kw) || r.name.toLowerCase().includes(kw),
  );
});

async function loadRoles() {
  loading.value = true;
  try {
    roles.value = await systemApi.listRoles();
  } finally {
    loading.value = false;
  }
}

// ---- 新建 / 编辑 ----
const formDialogVisible = ref(false);
const editingRole = ref<RoleOut | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance | null>(null);

const formData = reactive({
  code: "",
  name: "",
  description: "",
});

const formRules: FormRules = {
  code: [
    { required: true, message: "请输入角色 Code", trigger: "blur" },
    { min: 2, max: 64, message: "长度 2-64 个字符", trigger: "blur" },
  ],
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

function openCreateDialog() {
  editingRole.value = null;
  formData.code = "";
  formData.name = "";
  formData.description = "";
  formDialogVisible.value = true;
}

function openEditDialog(row: RoleOut) {
  editingRole.value = row;
  formData.code = row.code;
  formData.name = row.name;
  formData.description = row.description ?? "";
  formDialogVisible.value = true;
}

async function onSubmitForm() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid) => {
    if (!valid) return;
    submitting.value = true;
    try {
      if (editingRole.value) {
        await systemApi.updateRole(editingRole.value.id, {
          name: formData.name,
          description: formData.description || null,
        });
        ElMessage.success("已更新");
      } else {
        await systemApi.createRole({
          code: formData.code,
          name: formData.name,
          description: formData.description || null,
        });
        ElMessage.success("已创建");
      }
      formDialogVisible.value = false;
      loadRoles();
    } finally {
      submitting.value = false;
    }
  });
}

async function onDelete(row: RoleOut) {
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${row.name}」吗？该操作不可恢复。`,
      "删除确认",
      { type: "warning" },
    );
    await systemApi.deleteRole(row.id);
    ElMessage.success("角色已删除");
    loadRoles();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// ---- 权限分配 ----
const permDialogVisible = ref(false);
const permRole = ref<RoleOut | null>(null);
const permLoading = ref(false);
const permTreeRef = ref<any>(null);
const permGroups = ref<PermissionGroup[]>([]);

/** 权限树数据：根节点为模块分组（id 用 group: 前缀避免与权限 id 冲突），叶子为权限点 */
const permTreeData = computed(() => {
  return permGroups.value.map((g) => ({
    id: `group:${g.module}`,
    label: g.module,
    children: (g.permissions ?? []).map((p: Permission) => ({
      id: p.id,
      label: `${p.name} (${p.code})`,
    })),
  }));
});

const permTreeProps = { label: "label", children: "children" };

async function openPermDialog(row: RoleOut) {
  permRole.value = row;
  permDialogVisible.value = true;
}

/** 对话框 open 后加载分组与当前角色已分配权限 */
async function onPermDialogOpen() {
  if (!permRole.value) return;
  permLoading.value = true;
  try {
    if (permGroups.value.length === 0) {
      permGroups.value = await systemApi.listPermissionsGrouped();
    }
    const current = await systemApi.getRolePermissions(permRole.value.id);
    const checkedIds = current.map((p) => p.id);
    // 等待树渲染
    await Promise.resolve();
    permTreeRef.value?.setCheckedKeys(checkedIds);
  } finally {
    permLoading.value = false;
  }
}

async function onSubmitPerms() {
  if (!permRole.value || !permTreeRef.value) return;
  // 仅取叶子节点（权限点）id，排除模块分组节点
  const checkedNodes: { id: string }[] = permTreeRef.value.getCheckedNodes(true, false);
  const permIds = checkedNodes.map((n: { id: string }) => n.id);
  submitting.value = true;
  try {
    await systemApi.assignRolePermissions(permRole.value.id, permIds);
    ElMessage.success(`已为角色分配 ${permIds.length} 个权限`);
    permDialogVisible.value = false;
  } finally {
    submitting.value = false;
  }
}

// ---- 工具 ----
function formatTime(s: string): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

onMounted(() => {
  loadRoles();
});
</script>

<style scoped>
.roles-view {
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

.perm-tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: #606266;
}

.muted {
  color: #909399;
  font-size: 12px;
}
</style>
