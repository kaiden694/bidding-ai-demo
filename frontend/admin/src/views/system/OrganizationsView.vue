<template>
  <div class="orgs-view">
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input
          v-model="filterText"
          placeholder="过滤组织名称"
          clearable
          style="width: 240px"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button
          v-if="auth.hasPermission('organization:create')"
          type="primary"
          :icon="Plus"
          @click="openCreateRootDialog"
        >
          新建根组织
        </el-button>
        <span v-if="auth.hasPermission('organization:update')" class="drag-tip">
          <el-icon><InfoFilled /></el-icon>
          支持拖拽节点调整层级
        </span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-tree
        ref="treeRef"
        v-loading="loading"
        :data="orgTree"
        :props="treeProps"
        node-key="id"
        :filter-node-method="filterNode"
        :draggable="auth.hasPermission('organization:update')"
        :expand-on-click-node="false"
        default-expand-all
        @node-drop="onNodeDrop"
      >
        <template #default="{ node, data }">
          <div class="org-node">
            <span class="org-label">
              <el-icon class="org-icon"><OfficeBuilding /></el-icon>
              {{ data.name }}
              <el-tag size="small" type="info" class="code-tag">{{ data.code }}</el-tag>
            </span>
            <span class="org-actions" @click.stop>
              <el-button
                v-if="auth.hasPermission('organization:create')"
                link
                type="primary"
                :icon="Plus"
                @click="openCreateChildDialog(data)"
              >
                新增子组织
              </el-button>
              <el-button
                v-if="auth.hasPermission('organization:update')"
                link
                type="primary"
                :icon="Edit"
                @click="openEditDialog(data)"
              >
                编辑
              </el-button>
              <el-button
                v-if="auth.hasPermission('organization:delete')"
                link
                type="danger"
                :icon="Delete"
                @click="onDelete(node, data)"
              >
                删除
              </el-button>
            </span>
          </div>
        </template>
      </el-tree>

      <el-empty v-if="!loading && orgTree.length === 0" description="暂无组织数据" />
    </el-card>

    <!-- 新建 / 编辑 对话框 -->
    <el-dialog
      v-model="formDialogVisible"
      :title="dialogTitle"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="90px"
      >
        <el-form-item v-if="formDataParentId" label="父组织">
          <span>{{ parentName }}</span>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="formData.name" placeholder="组织显示名称" />
        </el-form-item>
        <el-form-item label="Code" prop="code">
          <el-input
            v-model="formData.code"
            :disabled="!!editingOrg"
            placeholder="组织编码（唯一）"
          />
        </el-form-item>
        <el-form-item label="排序" prop="sort_order">
          <el-input-number v-model="formData.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitForm">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  Plus, Edit, Delete, Search, InfoFilled, OfficeBuilding,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as systemApi from "@/api/system";
import type { OrganizationOut, OrganizationTreeNode } from "@/types";

const auth = useAuthStore();

// ---- 树数据 ----
const loading = ref(false);
const orgTree = ref<OrganizationTreeNode[]>([]);
const treeRef = ref<any>(null);

const treeProps = { label: "name", children: "children" };

async function loadTree() {
  loading.value = true;
  try {
    orgTree.value = await systemApi.getOrganizationTree();
  } finally {
    loading.value = false;
  }
}

// ---- 过滤 ----
const filterText = ref("");
watch(filterText, (val) => {
  treeRef.value?.filter(val);
});

function filterNode(value: string, data: OrganizationOut) {
  if (!value) return true;
  return data.name.toLowerCase().includes(value.toLowerCase());
}

// ---- 拖拽移动节点 ----
async function onNodeDrop(
  draggingNode: { data: OrganizationOut },
  dropNode: { data: OrganizationOut },
  dropType: "before" | "after" | "inner",
) {
  const draggingId = draggingNode.data.id;
  if (!draggingId) return;
  let newParentId: string | null;
  if (dropType === "inner") {
    newParentId = dropNode.data.id;
  } else {
    // before/after：与 dropNode 同级，父节点 = dropNode 的父
    newParentId = dropNode.data.parent_id ?? null;
  }
  try {
    await systemApi.updateOrganization(draggingId, { parent_id: newParentId });
    ElMessage.success("已移动组织节点");
    await loadTree();
  } catch {
    // 后端会校验环路等；失败时重新加载以还原
    await loadTree();
  }
}

// ---- 新建 / 编辑 ----
const formDialogVisible = ref(false);
const editingOrg = ref<OrganizationOut | null>(null);
const formDataParentId = ref<string | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance | null>(null);

const formData = reactive({
  name: "",
  code: "",
  sort_order: 0,
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  code: [{ required: true, message: "请输入 Code", trigger: "blur" }],
};

const dialogTitle = computed(() => (editingOrg.value ? "编辑组织" : "新建组织"));

/** 通过遍历树查找节点名称（用于显示父组织名）*/
function findNodeName(tree: OrganizationTreeNode[], id: string | null): string {
  if (!id) return "";
  for (const n of tree) {
    if (n.id === id) return n.name;
    if (n.children?.length) {
      const r = findNodeName(n.children, id);
      if (r) return r;
    }
  }
  return "";
}

const parentName = computed(() => findNodeName(orgTree.value, formDataParentId.value));

function openCreateRootDialog() {
  editingOrg.value = null;
  formDataParentId.value = null;
  formData.name = "";
  formData.code = "";
  formData.sort_order = 0;
  formDialogVisible.value = true;
}

function openCreateChildDialog(parent: OrganizationOut) {
  editingOrg.value = null;
  formDataParentId.value = parent.id;
  formData.name = "";
  formData.code = "";
  formData.sort_order = 0;
  formDialogVisible.value = true;
}

function openEditDialog(node: OrganizationOut) {
  editingOrg.value = node;
  formDataParentId.value = node.parent_id;
  formData.name = node.name;
  formData.code = node.code;
  formData.sort_order = node.sort_order;
  formDialogVisible.value = true;
}

async function onSubmitForm() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid) => {
    if (!valid) return;
    submitting.value = true;
    try {
      if (editingOrg.value) {
        await systemApi.updateOrganization(editingOrg.value.id, {
          name: formData.name,
          parent_id: formDataParentId.value,
          sort_order: formData.sort_order,
        });
        ElMessage.success("已更新");
      } else {
        await systemApi.createOrganization({
          name: formData.name,
          code: formData.code,
          parent_id: formDataParentId.value,
          sort_order: formData.sort_order,
        });
        ElMessage.success("已创建");
      }
      formDialogVisible.value = false;
      await loadTree();
    } finally {
      submitting.value = false;
    }
  });
}

async function onDelete(
  node: { data: OrganizationOut },
  data: OrganizationOut,
) {
  // node.children 长度判断（el-tree NodeData）
  const childCount = (node as any).childNodes?.length ?? 0;
  if (childCount > 0) {
    ElMessage.warning("请先删除子组织");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确定删除组织「${data.name}」吗？该操作为软删除。`,
      "删除确认",
      { type: "warning" },
    );
    await systemApi.deleteOrganization(data.id);
    ElMessage.success("组织已删除");
    await loadTree();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

onMounted(() => {
  loadTree();
});
</script>

<style scoped>
.orgs-view {
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

.drag-tip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}

.org-node {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 8px;
}

.org-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.org-icon {
  color: #409eff;
}

.code-tag {
  margin-left: 4px;
}

.org-actions {
  display: none;
}

:deep(.el-tree-node__content):hover .org-actions {
  display: inline-flex;
}
</style>
