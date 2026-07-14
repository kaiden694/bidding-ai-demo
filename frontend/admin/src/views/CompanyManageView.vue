<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">公司管理</h2>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadCompanies">刷新</el-button>
        <el-button
          v-if="auth.hasPermission('system:config')"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >新增公司</el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="tip-alert"
      title="公司主数据管理"
      description="统一管理本公司、合作公司、竞品公司。产品和资质通过公司关联实现分类管理。"
    />

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-select
        v-model="filterType"
        placeholder="全部类型"
        clearable
        style="width: 160px"
        @change="loadCompanies"
      >
        <el-option
          v-for="(label, key) in typeLabels"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-input
        v-model="filterKeyword"
        placeholder="搜索公司名称/编码"
        clearable
        style="width: 240px"
        @keyup.enter="loadCompanies"
        @clear="loadCompanies"
      />
      <el-button :icon="Search" @click="loadCompanies">查询</el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="loading" :data="companies" border stripe>
      <el-table-column prop="name" label="公司名称" min-width="200" />
      <el-table-column prop="short_name" label="简称" width="120" />
      <el-table-column prop="code" label="编码" width="120" />
      <el-table-column label="类型" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="typeColor[row.company_type] || 'info'" size="small">
            {{ row.company_type_label || typeLabels[row.company_type] || row.company_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.hasPermission('system:config')"
            link type="primary" :icon="Edit"
            @click="openEdit(row)"
          >编辑</el-button>
          <el-button
            v-if="auth.hasPermission('system:config')"
            link type="danger" :icon="Delete"
            @click="onDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑公司' : '新增公司'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="公司名称" prop="name">
          <el-input v-model="form.name" placeholder="如：华为技术有限公司" />
        </el-form-item>
        <el-form-item label="简称">
          <el-input v-model="form.short_name" placeholder="如：华为" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="form.code" placeholder="如：HUAWEI（唯一）" />
        </el-form-item>
        <el-form-item label="公司类型" prop="company_type">
          <el-select v-model="form.company_type" style="width: 100%">
            <el-option
              v-for="(label, key) in typeLabels"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="公司简介、主营业务等"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import { Plus, Refresh, Edit, Delete, Search } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as companyApi from "@/api/company";
import {
  COMPANY_TYPE_LABELS,
  COMPANY_TYPE_COLORS,
} from "@/api/company";
import type { Company, CompanyType } from "@/types";

const auth = useAuthStore();

const loading = ref(false);
const companies = ref<Company[]>([]);
const filterType = ref<CompanyType | "">("");
const filterKeyword = ref("");

const typeLabels = COMPANY_TYPE_LABELS;
const typeColor = COMPANY_TYPE_COLORS;

async function loadCompanies() {
  loading.value = true;
  try {
    const params: Record<string, any> = {};
    if (filterType.value) params.company_type = filterType.value;
    if (filterKeyword.value) params.keyword = filterKeyword.value;
    companies.value = await companyApi.getCompanies(params);
  } finally {
    loading.value = false;
  }
}

function formatTime(t: string): string {
  if (!t) return "-";
  const d = new Date(t);
  return d.toLocaleString("zh-CN", { hour12: false });
}

// 新增/编辑
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Company | null>(null);
const formRef = ref<FormInstance | null>(null);

const form = reactive({
  name: "",
  short_name: "",
  code: "",
  company_type: "other" as CompanyType,
  description: "",
});

const rules: FormRules = {
  name: [{ required: true, message: "请输入公司名称", trigger: "blur" }],
  company_type: [{ required: true, message: "请选择公司类型", trigger: "change" }],
};

function resetForm() {
  form.name = "";
  form.short_name = "";
  form.code = "";
  form.company_type = "other";
  form.description = "";
}

function openCreate() {
  editing.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: Company) {
  editing.value = row;
  form.name = row.name;
  form.short_name = row.short_name || "";
  form.code = row.code || "";
  form.company_type = row.company_type;
  form.description = row.description || "";
  dialogVisible.value = true;
}

async function onSubmit() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    const payload: companyApi.CompanyPayload = {
      name: form.name,
      short_name: form.short_name || null,
      code: form.code || null,
      company_type: form.company_type,
      description: form.description || null,
    };
    if (editing.value) {
      await companyApi.updateCompany(editing.value.id, payload);
      ElMessage.success("已更新");
    } else {
      await companyApi.createCompany(payload);
      ElMessage.success("已创建");
    }
    dialogVisible.value = false;
    await loadCompanies();
  } finally {
    submitting.value = false;
  }
}

async function onDelete(row: Company) {
  try {
    await ElMessageBox.confirm(`确定删除公司「${row.name}」吗？`, "提示", { type: "warning" });
    await companyApi.deleteCompany(row.id);
    ElMessage.success("已删除");
    await loadCompanies();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

onMounted(() => {
  loadCompanies();
});
</script>

<style scoped>
.page-container {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.page-title {
  margin: 0;
  font-size: 18px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.tip-alert {
  margin-bottom: 4px;
}
.filter-bar {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
