<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">产品中心</h2>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="product-layout">
      <!-- 左侧：分类树 -->
      <div class="category-panel">
        <div class="panel-header">
          <span class="panel-title">产品分类</span>
          <el-button
            v-if="auth.hasPermission('product:create')"
            size="small"
            :icon="Plus"
            @click="openCategoryDialog"
          >新增</el-button>
        </div>
        <el-button
          class="all-btn"
          :type="selectedCategoryId === null ? 'primary' : ''"
          size="small"
          @click="selectAllProducts"
        >全部产品</el-button>
        <el-tree
          :data="treeData"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          highlight-current
          :expand-on-click-node="false"
          @node-click="onCategoryClick"
        />
        <el-empty v-if="treeData.length === 0" description="暂无分类" :image-size="60" />
      </div>

      <!-- 右侧：产品列表 -->
      <div class="product-panel">
        <div class="panel-header">
          <span class="panel-title">
            产品列表{{ selectedCategory ? ` - ${selectedCategory.name}` : "" }}
          </span>
          <el-button
            v-if="auth.hasPermission('product:create')"
            type="primary"
            :icon="Plus"
            @click="openProductDialog"
          >新建产品</el-button>
        </div>

        <el-form :inline="true" class="filter-bar">
          <el-form-item label="关键字">
            <el-input
              v-model="keyword"
              placeholder="产品名称"
              clearable
              style="width: 200px"
              @change="loadProducts"
            />
          </el-form-item>
          <el-form-item label="公司">
            <el-select
              v-model="selectedCompanyId"
              placeholder="全部公司"
              clearable
              filterable
              style="width: 200px"
              @change="loadProducts"
            >
              <el-option
                v-for="c in companies"
                :key="c.id"
                :label="c.name"
                :value="c.id"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <el-table v-loading="loading" :data="products" border stripe>
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column label="公司" min-width="140">
            <template #default="{ row }">
              <span v-if="row.company_name">{{ row.company_name }}</span>
              <el-tag v-else size="small" type="info">未关联</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="编码" width="120">
            <template #default="{ row }">{{ row.code || "-" }}</template>
          </el-table-column>
          <el-table-column prop="model" label="型号" width="120">
            <template #default="{ row }">{{ row.model || "-" }}</template>
          </el-table-column>
          <el-table-column prop="brand" label="品牌" width="120">
            <template #default="{ row }">{{ row.brand || "-" }}</template>
          </el-table-column>
          <el-table-column prop="manufacturer" label="厂商" width="140">
            <template #default="{ row }">{{ row.manufacturer || "-" }}</template>
          </el-table-column>
          <el-table-column label="参数项" width="90">
            <template #default="{ row }">{{ (row.specs || []).length }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_published ? 'success' : 'info'">
                {{ row.is_published ? "已上架" : "未上架" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="auth.hasPermission('product:publish') && !row.is_published"
                size="small"
                type="success"
                @click="handlePublish(row)"
              >上架</el-button>
              <el-tag v-else-if="row.is_published" type="success" size="small">已上架</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 分类新建对话框 -->
    <el-dialog v-model="categoryDialog" title="新建分类" width="480px">
      <el-form ref="categoryFormRef" :model="categoryForm" :rules="categoryRules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="categoryForm.name" />
        </el-form-item>
        <el-form-item label="编码" prop="code">
          <el-input v-model="categoryForm.code" />
        </el-form-item>
        <el-form-item label="父分类">
          <el-tree-select
            v-model="categoryForm.parent_id"
            :data="treeData"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            clearable
            placeholder="无（顶级分类）"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="categoryForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryDialog = false">取消</el-button>
        <el-button type="primary" :loading="categorySubmitting" @click="handleCategorySubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 产品新建对话框 -->
    <el-dialog v-model="productDialog" title="新建产品" width="760px">
      <el-form ref="productFormRef" :model="productForm" :rules="productRules" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="名称" prop="name">
              <el-input v-model="productForm.name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="编码">
              <el-input v-model="productForm.code" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="分类">
              <el-tree-select
                v-model="productForm.category_id"
                :data="treeData"
                :props="{ label: 'name', children: 'children' }"
                node-key="id"
                check-strictly
                clearable
                placeholder="请选择分类"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属公司">
              <el-select
                v-model="productForm.company_id"
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
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="型号">
              <el-input v-model="productForm.model" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="品牌">
              <el-input v-model="productForm.brand" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="厂商">
          <el-input v-model="productForm.manufacturer" placeholder="生产厂家（建议优先选择所属公司）" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="productForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="技术参数">
          <div class="specs-wrap">
            <div
              v-for="(spec, idx) in productForm.specs"
              :key="idx"
              class="spec-row"
            >
              <el-input
                v-model="spec.name"
                placeholder="参数名"
                style="width: 120px"
              />
              <el-input
                v-model="spec.value"
                placeholder="数值"
                style="width: 120px"
              />
              <el-input
                v-model="spec.unit"
                placeholder="单位"
                style="width: 80px"
              />
              <el-input
                v-model="spec.tolerance"
                placeholder="公差"
                style="width: 100px"
              />
              <el-input
                v-model="spec.remarks"
                placeholder="备注"
                style="width: 120px"
              />
              <el-button
                :icon="Delete"
                circle
                size="small"
                @click="removeSpec(idx)"
              />
            </div>
            <el-button size="small" :icon="Plus" @click="addSpec">添加参数</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="productDialog = false">取消</el-button>
        <el-button type="primary" :loading="productSubmitting" @click="handleProductSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox, type FormInstance } from "element-plus";
import { Plus, Delete, Refresh } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as productApi from "@/api/product";
import * as companyApi from "@/api/company";
import type {
  ProductCategoryItem,
  ProductItem,
  ProductSpec,
  CompanyBrief,
} from "@/types";

const auth = useAuthStore();

// ---- 分类 ----
const categories = ref<ProductCategoryItem[]>([]);
const selectedCategoryId = ref<string | null>(null);

const treeData = computed<ProductCategoryItem[]>(() => buildTree(categories.value));

function buildTree(items: ProductCategoryItem[]): ProductCategoryItem[] {
  const map = new Map<string, ProductCategoryItem>();
  items.forEach((i) => map.set(i.id, { ...i, children: [] }));
  const roots: ProductCategoryItem[] = [];
  items.forEach((i) => {
    const node = map.get(i.id)!;
    if (i.parent_id && map.has(i.parent_id)) {
      map.get(i.parent_id)!.children!.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

const selectedCategory = computed<ProductCategoryItem | null>(() =>
  selectedCategoryId.value
    ? categories.value.find((c) => c.id === selectedCategoryId.value) || null
    : null,
);

async function loadCategories() {
  categories.value = await productApi.listCategories();
}

function onCategoryClick(node: ProductCategoryItem) {
  selectedCategoryId.value = node.id;
  loadProducts();
}

function selectAllProducts() {
  selectedCategoryId.value = null;
  loadProducts();
}

// ---- 产品列表 ----
const loading = ref(false);
const products = ref<ProductItem[]>([]);
const keyword = ref("");
const selectedCompanyId = ref<string>("");
const companies = ref<CompanyBrief[]>([]);

async function loadCompanies() {
  try {
    companies.value = await companyApi.getCompaniesBrief();
  } catch {
    // 拦截器已提示
  }
}

async function loadProducts() {
  loading.value = true;
  try {
    const params: { category_id?: string; company_id?: string; keyword?: string } = {};
    if (selectedCategoryId.value) params.category_id = selectedCategoryId.value;
    if (selectedCompanyId.value) params.company_id = selectedCompanyId.value;
    if (keyword.value) params.keyword = keyword.value;
    products.value = await productApi.listProducts(params);
  } finally {
    loading.value = false;
  }
}

async function loadAll() {
  await Promise.all([loadCategories(), loadCompanies(), loadProducts()]);
}

async function handlePublish(row: ProductItem) {
  await ElMessageBox.confirm(`确定上架产品「${row.name}」吗？`, "上架", {
    type: "warning",
  });
  await productApi.publishProduct(row.id);
  ElMessage.success("已上架");
  loadProducts();
}

// ---- 分类新建 ----
const categoryDialog = ref(false);
const categorySubmitting = ref(false);
const categoryFormRef = ref<FormInstance>();
const categoryForm = reactive({
  name: "",
  code: "",
  parent_id: "" as string,
  description: "",
});
const categoryRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  code: [{ required: true, message: "请输入编码", trigger: "blur" }],
};

function openCategoryDialog() {
  categoryForm.name = "";
  categoryForm.code = "";
  categoryForm.parent_id = "";
  categoryForm.description = "";
  categoryDialog.value = true;
}

async function handleCategorySubmit() {
  if (!categoryFormRef.value) return;
  const valid = await categoryFormRef.value.validate().catch(() => false);
  if (!valid) return;
  categorySubmitting.value = true;
  try {
    await productApi.createCategory({
      name: categoryForm.name,
      code: categoryForm.code,
      parent_id: categoryForm.parent_id || undefined,
      description: categoryForm.description || undefined,
    });
    ElMessage.success("分类已创建");
    categoryDialog.value = false;
    loadCategories();
  } finally {
    categorySubmitting.value = false;
  }
}

// ---- 产品新建 ----
const productDialog = ref(false);
const productSubmitting = ref(false);
const productFormRef = ref<FormInstance>();
const productForm = reactive({
  name: "",
  code: "",
  category_id: "" as string,
  company_id: "" as string,
  model: "",
  brand: "",
  manufacturer: "",
  description: "",
  specs: [] as ProductSpec[],
});
const productRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

function openProductDialog() {
  productForm.name = "";
  productForm.code = "";
  productForm.category_id = selectedCategoryId.value || "";
  productForm.company_id = "";
  productForm.model = "";
  productForm.brand = "";
  productForm.manufacturer = "";
  productForm.description = "";
  productForm.specs = [];
  productDialog.value = true;
}

function addSpec() {
  productForm.specs.push({
    name: "",
    value: "",
    unit: "",
    tolerance: "",
    remarks: "",
  });
}

function removeSpec(idx: number) {
  productForm.specs.splice(idx, 1);
}

async function handleProductSubmit() {
  if (!productFormRef.value) return;
  const valid = await productFormRef.value.validate().catch(() => false);
  if (!valid) return;
  productSubmitting.value = true;
  try {
    await productApi.createProduct({
      name: productForm.name,
      code: productForm.code || undefined,
      category_id: productForm.category_id || undefined,
      company_id: productForm.company_id || undefined,
      model: productForm.model || undefined,
      brand: productForm.brand || undefined,
      manufacturer: productForm.manufacturer || undefined,
      description: productForm.description || undefined,
      specs: productForm.specs.filter((s) => s.name),
    });
    ElMessage.success("产品已创建");
    productDialog.value = false;
    loadProducts();
  } finally {
    productSubmitting.value = false;
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
  loadAll();
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
.product-layout {
  display: flex;
  gap: 12px;
}
.category-panel {
  width: 260px;
  flex-shrink: 0;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px;
  background: #fff;
}
.product-panel {
  flex: 1;
  min-width: 0;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.panel-title {
  font-weight: 600;
}
.all-btn {
  width: 100%;
  margin-bottom: 8px;
}
.filter-bar {
  margin-bottom: 12px;
}
.specs-wrap {
  width: 100%;
}
.spec-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
</style>
