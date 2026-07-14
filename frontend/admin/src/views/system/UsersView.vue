<template>
  <div class="users-view">
    <!-- 顶部搜索栏 -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索用户名 / 姓名"
          clearable
          style="width: 260px"
          @keyup.enter="onSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" :icon="Search" @click="onSearch">搜索</el-button>
        <el-button :icon="Refresh" @click="onReset">重置</el-button>
        <div class="filter-actions">
          <el-button
            v-if="auth.hasPermission('user:create')"
            type="primary"
            :icon="Plus"
            @click="openCreateDialog"
          >
            新建用户
          </el-button>
          <el-button
            v-if="auth.hasPermission('user:create')"
            :icon="Upload"
            @click="triggerImport"
          >
            批量导入
          </el-button>
          <input
            ref="importInputRef"
            type="file"
            accept=".csv"
            style="display: none"
            @change="onImportFileChange"
          />
        </div>
      </div>
    </el-card>

    <!-- 用户列表 -->
    <el-card shadow="never" class="table-card">
      <el-table
        v-loading="loading"
        :data="users"
        border
        stripe
        style="width: 100%"
      >
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="full_name" label="姓名" min-width="100">
          <template #default="{ row }">
            {{ row.full_name || "-" }}
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180">
          <template #default="{ row }">{{ row.email || "-" }}</template>
        </el-table-column>
        <el-table-column prop="phone" label="手机" min-width="130">
          <template #default="{ row }">{{ row.phone || "-" }}</template>
        </el-table-column>
        <el-table-column label="启用状态" width="100" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              :disabled="!auth.hasPermission('user:update')"
              @change="(val: boolean) => toggleActive(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="120">
          <template #default="{ row }">
            <el-tag v-if="roleNameOf(row.role_id)" type="info">
              {{ roleNameOf(row.role_id) }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('user:update')"
              link
              type="primary"
              :icon="Edit"
              @click="openEditDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('user:update')"
              link
              type="primary"
              :icon="UserFilled"
              @click="openAssignRoleDialog(row)"
            >
              分配角色
            </el-button>
            <el-button
              v-if="auth.hasPermission('user:reset_password')"
              link
              type="warning"
              :icon="Key"
              @click="openResetPasswordDialog(row)"
            >
              重置密码
            </el-button>
            <el-button
              v-if="auth.hasPermission('user:delete')"
              link
              type="danger"
              :icon="Delete"
              @click="onDisable(row)"
            >
              禁用
            </el-button>
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
          @current-change="loadUsers"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <!-- 新建 / 编辑 对话框 -->
    <el-dialog
      v-model="formDialogVisible"
      :title="editingUser ? '编辑用户' : '新建用户'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="90px"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="formData.username"
            :disabled="!!editingUser"
            placeholder="3-64 个字符"
          />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="密码" prop="password">
          <el-input
            v-model="formData.password"
            type="password"
            show-password
            placeholder="6-128 个字符"
          />
        </el-form-item>
        <el-form-item label="姓名" prop="full_name">
          <el-input v-model="formData.full_name" placeholder="选填" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="formData.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="手机" prop="phone">
          <el-input v-model="formData.phone" placeholder="选填" />
        </el-form-item>
        <el-form-item label="角色" prop="role_id">
          <el-select
            v-model="formData.role_id"
            clearable
            placeholder="选择角色"
            style="width: 100%"
          >
            <el-option
              v-for="r in roles"
              :key="r.id"
              :label="`${r.name} (${r.code})`"
              :value="r.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="组织" prop="organization_id">
          <el-tree-select
            v-model="formData.organization_id"
            :data="orgTreeSelectData"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            clearable
            check-strictly
            placeholder="选择组织"
            style="width: 100%"
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

    <!-- 分配角色对话框 -->
    <el-dialog
      v-model="assignRoleDialogVisible"
      title="分配角色"
      width="420px"
      :close-on-click-modal="false"
    >
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <span>{{ assigningUser?.username }}</span>
        </el-form-item>
        <el-form-item label="角色">
          <el-select
            v-model="assignRoleId"
            clearable
            placeholder="选择角色"
            style="width: 100%"
          >
            <el-option
              v-for="r in roles"
              :key="r.id"
              :label="`${r.name} (${r.code})`"
              :value="r.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="assignRoleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitAssignRole">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 重置密码对话框 -->
    <el-dialog
      v-model="resetPwdDialogVisible"
      title="重置密码"
      width="420px"
      :close-on-click-modal="false"
    >
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <span>{{ resettingUser?.username }}</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="resetPwdValue"
            type="password"
            show-password
            placeholder="6-128 个字符"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetPwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitResetPassword">
          确认重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  Plus, Edit, Delete, Search, Refresh, Upload, Key, UserFilled,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as systemApi from "@/api/system";
import type { UserOut, RoleOut, OrganizationTreeNode } from "@/types";

const auth = useAuthStore();

// ---- 列表数据 ----
const loading = ref(false);
const users = ref<UserOut[]>([]);
const roles = ref<RoleOut[]>([]);
const orgs = ref<OrganizationTreeNode[]>([]);

const keyword = ref("");
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);

/** 后端 list_users 不返回 total，按返回长度估算：
 *  若返回条数等于 pageSize，则假设存在下一页（total +1 以启用“下一页”）；
 *  若不足，则当前为最后一页。 */
function estimateTotal(skip: number, len: number, limit: number) {
  if (len < limit) return skip + len;
  return skip + len + 1;
}

function roleNameOf(roleId: string | null): string | null {
  if (!roleId) return null;
  return roles.value.find((r) => r.id === roleId)?.name ?? null;
}

async function loadUsers() {
  loading.value = true;
  try {
    const skip = (page.value - 1) * pageSize.value;
    const data = await systemApi.listUsers({
      keyword: keyword.value || undefined,
      skip,
      limit: pageSize.value,
    });
    users.value = data;
    total.value = estimateTotal(skip, data.length, pageSize.value);
  } finally {
    loading.value = false;
  }
}

async function loadRoles() {
  roles.value = await systemApi.listRoles();
}

async function loadOrganizations() {
  orgs.value = await systemApi.getOrganizationTree();
}

/** 组织树（用于 el-tree-select） */
const orgTreeSelectData = computed<OrganizationTreeNode[]>(() => orgs.value);

function onSearch() {
  page.value = 1;
  loadUsers();
}

function onReset() {
  keyword.value = "";
  page.value = 1;
  loadUsers();
}

function onSizeChange(size: number) {
  pageSize.value = size;
  page.value = 1;
  loadUsers();
}

// ---- 启用 / 禁用 ----
async function toggleActive(row: UserOut, val: boolean) {
  try {
    await systemApi.updateUser(row.id, { is_active: val });
    row.is_active = val;
    ElMessage.success(val ? "已启用" : "已禁用");
  } catch {
    // 拦截器已提示
  }
}

async function onDisable(row: UserOut) {
  try {
    await ElMessageBox.confirm(
      `确定要禁用用户「${row.username}」吗？该操作为软删除。`,
      "禁用确认",
      { type: "warning" },
    );
    await systemApi.disableUser(row.id);
    ElMessage.success("用户已禁用");
    loadUsers();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// ---- 新建 / 编辑 ----
const formDialogVisible = ref(false);
const editingUser = ref<UserOut | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance | null>(null);

const formData = reactive<{
  username: string;
  password: string;
  full_name: string;
  email: string;
  phone: string;
  role_id: string | null;
  organization_id: string | null;
}>({
  username: "",
  password: "",
  full_name: "",
  email: "",
  phone: "",
  role_id: null,
  organization_id: null,
});

const formRules: FormRules = {
  username: [
    { required: true, message: "请输入用户名", trigger: "blur" },
    { min: 3, max: 64, message: "长度 3-64 个字符", trigger: "blur" },
  ],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    { min: 6, max: 128, message: "长度 6-128 个字符", trigger: "blur" },
  ],
  email: [{ type: "email", message: "邮箱格式不正确", trigger: "blur" }],
};

function resetForm() {
  formData.username = "";
  formData.password = "";
  formData.full_name = "";
  formData.email = "";
  formData.phone = "";
  formData.role_id = null;
  formData.organization_id = null;
}

function openCreateDialog() {
  editingUser.value = null;
  resetForm();
  formDialogVisible.value = true;
}

function openEditDialog(row: UserOut) {
  editingUser.value = row;
  formData.username = row.username;
  formData.password = "";
  formData.full_name = row.full_name ?? "";
  formData.email = row.email ?? "";
  formData.phone = row.phone ?? "";
  formData.role_id = row.role_id;
  formData.organization_id = row.organization_id;
  formDialogVisible.value = true;
}

async function onSubmitForm() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid) => {
    if (!valid) return;
    submitting.value = true;
    try {
      if (editingUser.value) {
        await systemApi.updateUser(editingUser.value.id, {
          email: formData.email || null,
          phone: formData.phone || null,
          full_name: formData.full_name || null,
          role_id: formData.role_id,
          organization_id: formData.organization_id,
        });
        ElMessage.success("已更新");
      } else {
        await systemApi.createUser({
          username: formData.username,
          password: formData.password,
          email: formData.email || null,
          phone: formData.phone || null,
          full_name: formData.full_name || null,
          role_id: formData.role_id,
          organization_id: formData.organization_id,
        });
        ElMessage.success("已创建");
      }
      formDialogVisible.value = false;
      loadUsers();
    } finally {
      submitting.value = false;
    }
  });
}

// ---- 分配角色 ----
const assignRoleDialogVisible = ref(false);
const assigningUser = ref<UserOut | null>(null);
const assignRoleId = ref<string | null>(null);

function openAssignRoleDialog(row: UserOut) {
  assigningUser.value = row;
  assignRoleId.value = row.role_id;
  assignRoleDialogVisible.value = true;
}

async function onSubmitAssignRole() {
  if (!assigningUser.value) return;
  submitting.value = true;
  try {
    await systemApi.updateUser(assigningUser.value.id, {
      role_id: assignRoleId.value,
    });
    ElMessage.success("角色已分配");
    assignRoleDialogVisible.value = false;
    loadUsers();
  } finally {
    submitting.value = false;
  }
}

// ---- 重置密码 ----
const resetPwdDialogVisible = ref(false);
const resettingUser = ref<UserOut | null>(null);
const resetPwdValue = ref("");

function openResetPasswordDialog(row: UserOut) {
  resettingUser.value = row;
  resetPwdValue.value = "";
  resetPwdDialogVisible.value = true;
}

async function onSubmitResetPassword() {
  if (!resettingUser.value) return;
  if (!resetPwdValue.value || resetPwdValue.value.length < 6) {
    ElMessage.warning("密码至少 6 个字符");
    return;
  }
  submitting.value = true;
  try {
    await systemApi.resetPassword(resettingUser.value.id, resetPwdValue.value);
    ElMessage.success("密码已重置");
    resetPwdDialogVisible.value = false;
  } finally {
    submitting.value = false;
  }
}

// ---- 批量导入 ----
const importInputRef = ref<HTMLInputElement | null>(null);

function triggerImport() {
  importInputRef.value?.click();
}

async function onImportFileChange(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  if (!file.name.endsWith(".csv")) {
    ElMessage.error("仅支持 CSV 文件");
    target.value = "";
    return;
  }
  const fd = new FormData();
  fd.append("file", file);
  try {
    loading.value = true;
    const res = await systemApi.batchImportUsers(fd);
    const failedCount = res.failed.length;
    ElMessage.success(`导入完成：成功 ${res.success} 条${failedCount ? `，失败 ${failedCount} 条` : ""}`);
    if (failedCount) {
      const detail = res.failed.map((f) => `${f.username}: ${f.reason}`).join("\n");
      ElMessageBox.alert(detail, "失败明细", { type: "warning" });
    }
    loadUsers();
  } finally {
    loading.value = false;
    target.value = "";
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

onMounted(async () => {
  await Promise.all([loadRoles(), loadOrganizations()]);
  await loadUsers();
});
</script>

<style scoped>
.users-view {
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

.filter-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.pagination-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
