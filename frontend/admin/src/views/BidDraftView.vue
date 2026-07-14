<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">标书起草</h2>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左侧：模板与项目 -->
      <el-col :span="8">
        <el-card shadow="never" class="panel">
          <template #header>
            <span class="card-title">模板与项目</span>
          </template>
          <el-form label-width="80px">
            <el-form-item label="项目">
              <el-input
                v-model="projectId"
                placeholder="输入项目 ID"
                clearable
                @change="onProjectChange"
              />
            </el-form-item>
            <el-form-item label="模板">
              <el-select
                v-model="selectedTemplateId"
                placeholder="选择模板"
                filterable
                style="width: 100%"
                @change="onTemplateChange"
              >
                <el-option
                  v-for="t in templates"
                  :key="t.id"
                  :label="t.name"
                  :value="t.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item v-if="selectedTemplate?.variables?.length" label="变量">
              <div class="var-form">
                <div
                  v-for="v in selectedTemplate.variables"
                  :key="v"
                  class="var-row"
                >
                  <span class="var-name">{{ v }}</span>
                  <el-input v-model="variables[v]" placeholder="值" />
                </div>
                <el-button
                  type="primary"
                  size="small"
                  :loading="filling"
                  @click="onFillTemplate"
                >填充模板</el-button>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- 中间：AI 生成章节 -->
      <el-col :span="8">
        <el-card shadow="never" class="panel">
          <template #header>
            <span class="card-title">AI 生成章节</span>
          </template>
          <el-form label-width="80px">
            <el-form-item label="章节标题">
              <el-input v-model="genForm.section_title" placeholder="例如：项目概述" />
            </el-form-item>
            <el-form-item label="类别">
              <el-select v-model="genForm.category" clearable style="width: 100%">
                <el-option label="技术方案" value="technical" />
                <el-option label="商务报价" value="commercial" />
                <el-option label="项目管理" value="management" />
                <el-option label="售后服务" value="service" />
              </el-select>
            </el-form-item>
            <el-form-item label="上下文">
              <el-input
                v-model="genForm.context"
                type="textarea"
                :rows="3"
                placeholder="补充上下文信息（选填）"
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :icon="MagicStick"
                :loading="generating"
                :disabled="!projectId || !genForm.section_title"
                @click="onGenerate"
              >AI 生成</el-button>
            </el-form-item>
          </el-form>

          <div v-if="generatedContent" class="gen-result">
            <div class="result-title">生成结果</div>
            <el-input
              v-model="generatedContent"
              type="textarea"
              :rows="8"
            />
            <el-button
              size="small"
              type="success"
              :icon="Plus"
              @click="appendSection"
            >追加到草稿</el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：草稿 -->
      <el-col :span="8">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">草稿内容</span>
              <div class="header-btns">
                <el-button
                  v-if="auth.hasPermission('bid:edit')"
                  size="small"
                  type="primary"
                  :loading="saving"
                  :disabled="!projectId"
                  @click="onSave"
                >保存</el-button>
              </div>
            </div>
          </template>
          <el-form label-width="80px">
            <el-form-item label="标题">
              <el-input v-model="draft.title" placeholder="草稿标题" />
            </el-form-item>
            <el-form-item label="状态">
              <el-tag size="small">{{ draft.status || "未保存" }}</el-tag>
            </el-form-item>
          </el-form>
          <div class="draft-sections" v-if="draftSections.length">
            <div class="result-title">章节列表</div>
            <el-collapse>
              <el-collapse-item
                v-for="(sec, idx) in draftSections"
                :key="idx"
                :title="sec.title"
                :name="String(idx)"
              >
                <el-input
                  v-model="sec.content"
                  type="textarea"
                  :rows="6"
                />
                <el-button
                  size="small"
                  type="danger"
                  :icon="Delete"
                  @click="removeSection(idx)"
                >删除章节</el-button>
              </el-collapse-item>
            </el-collapse>
          </div>
          <el-empty v-else description="暂无章节，请生成或填充模板" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { Refresh, MagicStick, Plus, Delete } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as bidApi from "@/api/bidDraft";
import type { BidTemplate, BidDraftSection } from "@/types";

const auth = useAuthStore();

// ---- 模板 ----
const templates = ref<BidTemplate[]>([]);
const selectedTemplateId = ref<string | null>(null);
const variables = reactive<Record<string, string>>({});
const filling = ref(false);

const selectedTemplate = computed(() =>
  templates.value.find((t) => t.id === selectedTemplateId.value) || null,
);

async function loadTemplates() {
  templates.value = await bidApi.getBidTemplates();
}

function onTemplateChange() {
  // 清空变量表单
  Object.keys(variables).forEach((k) => delete variables[k]);
  if (selectedTemplate.value?.variables) {
    selectedTemplate.value.variables.forEach((v) => {
      variables[v] = "";
    });
  }
}

async function onFillTemplate() {
  if (!selectedTemplate.value) return;
  filling.value = true;
  try {
    const res = await bidApi.fillTemplate(selectedTemplate.value.id, { ...variables });
    // 把填充结果作为章节追加
    draftSections.value.push({
      title: selectedTemplate.value.name,
      content: res.content,
      category: selectedTemplate.value.category || undefined,
    });
    ElMessage.success("模板已填充并追加到草稿");
  } finally {
    filling.value = false;
  }
}

// ---- 项目 / 草稿 ----
const projectId = ref<string>("");
const draft = reactive({
  id: "" as string,
  title: "" as string,
  content: "" as string,
  status: "" as string,
  template_id: null as string | null,
});
const draftSections = ref<BidDraftSection[]>([]);
const saving = ref(false);

async function onProjectChange() {
  if (!projectId.value) {
    resetDraft();
    return;
  }
  try {
    const d = await bidApi.getBidDraft(projectId.value);
    draft.id = d.id;
    draft.title = d.title || "";
    draft.content = d.content || "";
    draft.status = d.status || "";
    draft.template_id = d.template_id;
    draftSections.value = d.sections || [];
  } catch {
    // 草稿不存在
    resetDraft();
  }
}

function resetDraft() {
  draft.id = "";
  draft.title = "";
  draft.content = "";
  draft.status = "";
  draft.template_id = null;
  draftSections.value = [];
}

// ---- AI 生成 ----
const genForm = reactive({
  section_title: "",
  category: "" as string,
  context: "" as string,
});
const generating = ref(false);
const generatedContent = ref<string>("");

async function onGenerate() {
  if (!projectId.value || !genForm.section_title) return;
  generating.value = true;
  generatedContent.value = "";
  try {
    const res = await bidApi.generateSection(projectId.value, {
      section_title: genForm.section_title,
      category: genForm.category || undefined,
      context: genForm.context || undefined,
    });
    generatedContent.value = res.content;
    ElMessage.success("章节已生成");
  } finally {
    generating.value = false;
  }
}

function appendSection() {
  if (!generatedContent.value) return;
  draftSections.value.push({
    title: genForm.section_title || `章节 ${draftSections.value.length + 1}`,
    content: generatedContent.value,
    category: genForm.category || undefined,
  });
  ElMessage.success("已追加到草稿");
}

function removeSection(idx: number) {
  draftSections.value.splice(idx, 1);
}

async function onSave() {
  if (!projectId.value) return;
  saving.value = true;
  try {
    const payload = {
      title: draft.title || undefined,
      content: draftSections.value.map((s) => s.content).join("\n\n"),
      sections: draftSections.value,
      template_id: draft.template_id || undefined,
      status: draft.status || "draft",
    };
    if (draft.id) {
      await bidApi.updateBidDraft(projectId.value, payload);
      ElMessage.success("草稿已更新");
    } else {
      const res = await bidApi.createBidDraft(projectId.value, payload);
      draft.id = res.id;
      draft.status = res.status || "draft";
      ElMessage.success("草稿已创建");
    }
  } finally {
    saving.value = false;
  }
}

async function loadAll() {
  await loadTemplates();
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
.panel {
  min-height: 60vh;
}
.card-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-btns {
  display: flex;
  gap: 4px;
}
.var-form {
  width: 100%;
}
.var-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.var-name {
  width: 90px;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}
.gen-result {
  margin-top: 12px;
}
.result-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.draft-sections {
  margin-top: 12px;
}
:deep(.el-collapse-item__content) {
  padding-bottom: 8px;
}
:deep(.el-collapse-item__content > .el-button) {
  margin-top: 8px;
}
</style>
