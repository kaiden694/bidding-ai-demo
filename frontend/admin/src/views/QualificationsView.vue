<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">资质台账</h2>
      <div class="header-actions">
        <el-button
          v-if="auth.hasPermission('qualification:create') && activeTab === 'all'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >新建资质</el-button>
        <el-button :icon="Refresh" @click="loadCurrent">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="即将过期" name="expiring" />
      <el-tab-pane label="预警记录" name="alerts" />
    </el-tabs>

    <!-- 资质列表（all / expiring） -->
    <template v-if="activeTab !== 'alerts'">
      <el-form :inline="true" class="filter-bar">
        <el-form-item label="类型">
          <el-select
            v-model="filterType"
            placeholder="全部"
            clearable
            style="width: 150px"
            @change="loadList"
          >
            <el-option
              v-for="opt in qualTypeOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="公司">
          <el-select
            v-model="filterCompanyId"
            placeholder="全部公司"
            clearable
            filterable
            style="width: 180px"
            @change="loadList"
          >
            <el-option
              v-for="c in companies"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="供应商">
          <el-input
            v-model="filterSupplier"
            placeholder="供应商名称"
            clearable
            style="width: 180px"
            @change="loadList"
          />
        </el-form-item>
        <el-form-item label="有效性">
          <el-select
            v-model="filterValid"
            placeholder="全部"
            clearable
            style="width: 130px"
            @change="loadList"
          >
            <el-option label="有效" :value="true" />
            <el-option label="无效" :value="false" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="tableData" border stripe>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="公司" min-width="140">
          <template #default="{ row }">
            <span v-if="row.company_name">{{ row.company_name }}</span>
            <el-tag v-else size="small" type="info">未关联</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ qualTypeLabel(row.qual_type) }}</template>
        </el-table-column>
        <el-table-column prop="cert_number" label="证书编号" width="140">
          <template #default="{ row }">{{ row.cert_number || "-" }}</template>
        </el-table-column>
        <el-table-column prop="issuer" label="发证机构" width="140">
          <template #default="{ row }">{{ row.issuer || "-" }}</template>
        </el-table-column>
        <el-table-column prop="supplier_name" label="供应商" width="140">
          <template #default="{ row }">{{ row.supplier_name || "-" }}</template>
        </el-table-column>
        <el-table-column label="有效期" width="120">
          <template #default="{ row }">
            <span :class="expireClass(row.expire_date)">{{ row.expire_date || "-" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_valid ? 'success' : 'danger'">
              {{ row.is_valid ? "有效" : "无效" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('qualification:update')"
              size="small"
              :icon="Edit"
              @click="openEdit(row)"
            >编辑</el-button>
            <el-upload
              v-if="auth.hasPermission('qualification:update')"
              :show-file-list="false"
              :http-request="buildUploadHandler(row)"
              accept=".pdf"
            >
              <el-button size="small" :icon="Upload" :loading="uploadingId === row.id">
                上传证书
              </el-button>
            </el-upload>
            <el-button
              v-if="auth.hasPermission('qualification:extract')"
              size="small"
              type="primary"
              :loading="extractingId === row.id"
              @click="handleExtract(row)"
            >字段提取</el-button>
            <el-button
              v-if="auth.hasPermission('qualification:delete')"
              size="small"
              type="danger"
              :icon="Delete"
              @click="handleDelete(row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 预警记录 -->
    <template v-else>
      <el-form :inline="true" class="filter-bar">
        <el-form-item label="严重程度">
          <el-select
            v-model="alertSeverity"
            placeholder="全部"
            clearable
            style="width: 160px"
            @change="loadAlerts"
          >
            <el-option label="严重" value="critical" />
            <el-option label="已过期" value="expired" />
            <el-option label="预警" value="warning" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-table v-loading="alertsLoading" :data="alerts" border stripe>
        <el-table-column label="资质名称" min-width="180">
          <template #default="{ row }">
            {{ qualNameMap[row.qualification_id] || row.qualification_id }}
          </template>
        </el-table-column>
        <el-table-column label="严重程度" width="110">
          <template #default="{ row }">
            <el-tag :type="alertTagType(row.severity)">{{ alertSeverityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alert_date" label="预警日期" width="120" />
        <el-table-column prop="expire_date" label="到期日期" width="120">
          <template #default="{ row }">{{ row.expire_date || "-" }}</template>
        </el-table-column>
        <el-table-column prop="days_remaining" label="剩余天数" width="110">
          <template #default="{ row }">{{ row.days_remaining }}</template>
        </el-table-column>
        <el-table-column label="已通知" width="90">
          <template #default="{ row }">
            <el-tag :type="row.notified ? 'success' : 'info'" size="small">
              {{ row.notified ? "是" : "否" }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'edit' ? '编辑资质' : '新建资质'"
      width="620px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入资质名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.qual_type" style="width: 100%">
            <el-option
              v-for="opt in qualTypeOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="证书编号">
          <el-input v-model="form.cert_number" />
        </el-form-item>
        <el-form-item label="发证机构">
          <el-input v-model="form.issuer" />
        </el-form-item>
        <el-form-item label="资质范围">
          <el-input v-model="form.scope" type="textarea" :rows="2" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="发证日期">
              <el-date-picker
                v-model="form.issue_date"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="到期日期">
              <el-date-picker
                v-model="form.expire_date"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="所属公司">
              <el-select
                v-model="form.company_id"
                placeholder="选择公司"
                clearable
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="c in companies"
                  :key="c.id"
                  :label="c.name"
                  :value="c.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="持有方">
              <el-input v-model="form.owner" placeholder="（兼容字段，建议选择公司）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="供应商">
          <el-input v-model="form.supplier_name" placeholder="供应商名称（兼容字段）" />
        </el-form-item>
        <el-form-item label="有效">
          <el-switch v-model="form.is_valid" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox, type FormInstance } from "element-plus";
import { Plus, Edit, Delete, Upload, Refresh } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as qualApi from "@/api/qualification";
import * as companyApi from "@/api/company";
import type { Qualification, QualificationAlert, CompanyBrief } from "@/types";

const auth = useAuthStore();

const qualTypeOptions = [
  { label: "企业资质", value: "enterprise" },
  { label: "供应商资质", value: "supplier" },
  { label: "产品认证", value: "product" },
  { label: "人员资质", value: "personnel" },
];

function qualTypeLabel(v: string): string {
  return qualTypeOptions.find((o) => o.value === v)?.label || v || "-";
}

// ---- 标签页 ----
const activeTab = ref<"all" | "expiring" | "alerts">("all");
const loading = ref(false);
const list = ref<Qualification[]>([]);
const expiring = ref<Qualification[]>([]);
const alertsLoading = ref(false);
const alerts = ref<QualificationAlert[]>([]);

const tableData = computed(() =>
  activeTab.value === "expiring" ? expiring.value : list.value,
);

const qualNameMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {};
  list.value.forEach((q) => {
    m[q.id] = q.name;
  });
  return m;
});

// ---- 过滤 ----
const filterType = ref<string | undefined>(undefined);
const filterCompanyId = ref<string>("");
const filterSupplier = ref<string>("");
const filterValid = ref<boolean | undefined>(undefined);
const alertSeverity = ref<string | undefined>(undefined);
const companies = ref<CompanyBrief[]>([]);

async function loadCompanies() {
  try {
    companies.value = await companyApi.getCompaniesBrief();
  } catch {
    // 拦截器已提示
  }
}

async function loadList() {
  loading.value = true;
  try {
    const params: {
      qual_type?: string;
      company_id?: string;
      supplier_name?: string;
      is_valid?: boolean;
    } = {};
    if (filterType.value) params.qual_type = filterType.value;
    if (filterCompanyId.value) params.company_id = filterCompanyId.value;
    if (filterSupplier.value) params.supplier_name = filterSupplier.value;
    if (filterValid.value !== undefined) params.is_valid = filterValid.value;
    list.value = await qualApi.listQualifications(params);
  } finally {
    loading.value = false;
  }
}

async function loadExpiring() {
  loading.value = true;
  try {
    expiring.value = await qualApi.listExpiring(30);
  } finally {
    loading.value = false;
  }
}

async function loadAlerts() {
  alertsLoading.value = true;
  try {
    if (list.value.length === 0) {
      await loadList();
    }
    alerts.value = await qualApi.listAlerts(alertSeverity.value);
  } finally {
    alertsLoading.value = false;
  }
}

function onTabChange(tab: string | number) {
  if (tab === "all") loadList();
  else if (tab === "expiring") loadExpiring();
  else if (tab === "alerts") loadAlerts();
}

function loadCurrent() {
  onTabChange(activeTab.value);
}

// ---- 新建/编辑 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<string | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  qual_type: "enterprise",
  cert_number: "",
  issuer: "",
  scope: "",
  issue_date: "",
  expire_date: "",
  company_id: "" as string,
  owner: "",
  supplier_name: "",
  is_valid: true,
});
const rules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

function resetForm() {
  form.name = "";
  form.qual_type = "enterprise";
  form.cert_number = "";
  form.issuer = "";
  form.scope = "";
  form.issue_date = "";
  form.expire_date = "";
  form.company_id = "";
  form.owner = "";
  form.supplier_name = "";
  form.is_valid = true;
  editingId.value = null;
}

function openCreate() {
  dialogMode.value = "create";
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: Qualification) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  form.name = row.name;
  form.qual_type = row.qual_type || "enterprise";
  form.cert_number = row.cert_number || "";
  form.issuer = row.issuer || "";
  form.scope = row.scope || "";
  form.issue_date = row.issue_date || "";
  form.expire_date = row.expire_date || "";
  form.company_id = row.company_id || "";
  form.owner = row.owner || "";
  form.supplier_name = row.supplier_name || "";
  form.is_valid = row.is_valid;
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    const payload = {
      name: form.name,
      qual_type: form.qual_type,
      cert_number: form.cert_number || undefined,
      issuer: form.issuer || undefined,
      scope: form.scope || undefined,
      issue_date: form.issue_date || undefined,
      expire_date: form.expire_date || undefined,
      company_id: form.company_id || undefined,
      owner: form.owner || undefined,
      supplier_name: form.supplier_name || undefined,
      is_valid: form.is_valid,
    };
    if (dialogMode.value === "create") {
      await qualApi.createQualification(payload);
      ElMessage.success("创建成功");
    } else if (editingId.value) {
      await qualApi.updateQualification(editingId.value, payload);
      ElMessage.success("更新成功");
    }
    dialogVisible.value = false;
    loadCurrent();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: Qualification) {
  await ElMessageBox.confirm(`确定删除资质「${row.name}」吗？`, "提示", {
    type: "warning",
  });
  await qualApi.deleteQualification(row.id);
  ElMessage.success("已删除");
  loadCurrent();
}

// ---- 上传证书 ----
const uploadingId = ref<string | null>(null);

function buildUploadHandler(row: Qualification) {
  return async (options: any) => {
    const file = options.file as File;
    uploadingId.value = row.id;
    try {
      await qualApi.uploadCertificate(row.id, file);
      ElMessage.success("证书已上传");
      loadCurrent();
    } finally {
      uploadingId.value = null;
    }
  };
}

// ---- OCR + LLM 字段提取 ----
const extractingId = ref<string | null>(null);

async function handleExtract(row: Qualification) {
  extractingId.value = row.id;
  try {
    await qualApi.extractFields(row.id);
    ElMessage.success("字段提取完成");
    loadCurrent();
  } finally {
    extractingId.value = null;
  }
}

// ---- 工具 ----
function expireClass(expireDate: string | null): string {
  if (!expireDate) return "";
  const d = new Date(expireDate);
  if (isNaN(d.getTime())) return "";
  const diff = (d.getTime() - Date.now()) / (1000 * 60 * 60 * 24);
  if (diff < 0) return "expire-danger";
  if (diff <= 30) return "expire-warning";
  return "";
}

function alertTagType(severity: string): "danger" | "warning" | "info" {
  if (severity === "critical" || severity === "expired") return "danger";
  if (severity === "warning") return "warning";
  return "info";
}

function alertSeverityLabel(severity: string): string {
  const m: Record<string, string> = {
    critical: "严重",
    expired: "已过期",
    warning: "预警",
  };
  return m[severity] || severity;
}

onMounted(() => {
  loadCompanies();
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
:deep(.el-table .el-button + .el-button) {
  margin-left: 6px;
}
.expire-warning {
  color: #e6a23c;
  font-weight: 600;
}
.expire-danger {
  color: #f56c6c;
  font-weight: 600;
}
</style>
