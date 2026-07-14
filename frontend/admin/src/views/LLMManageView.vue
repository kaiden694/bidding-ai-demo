<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">AI 服务配置</h2>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="tip-alert"
      title="兼容 OpenAI 接口规范"
      description="所有 LLM / Embedding 服务均通过 OpenAI 兼容协议接入（base_url + api_key + model）。配置保存后即时热加载，无需重启服务。同一时刻仅一个 provider 生效（is_active=true）。"
    />

    <el-tabs v-model="activeTab" class="config-tabs">
      <!-- ============ LLM 配置 ============ -->
      <el-tab-pane label="LLM 对话模型" name="llm">
        <template #label>
          <el-icon class="tab-icon"><ChatDotRound /></el-icon>
          <span>LLM 对话模型</span>
        </template>

        <!-- LLM 运行时状态 -->
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">运行时状态</span>
              <el-button size="small" :icon="RefreshRight" :loading="llmHealthLoading" @click="loadLLMHealth">刷新</el-button>
            </div>
          </template>
          <div v-loading="llmHealthLoading" class="status-grid">
            <div
              v-for="h in llmHealthList"
              :key="h.id || h.name"
              class="status-item"
              :class="{ ok: h.is_healthy && !h.in_circuit_break, warn: h.is_healthy && h.in_circuit_break, fail: !h.is_healthy }"
            >
              <el-icon class="dot">
                <SuccessFilled v-if="h.is_healthy && !h.in_circuit_break" />
                <WarningFilled v-else-if="h.in_circuit_break" />
                <CircleCloseFilled v-else />
              </el-icon>
              <div class="status-info">
                <span class="status-name">{{ h.name || "默认" }}{{ h.is_fallback ? "（降级）" : "" }}</span>
                <span class="status-meta">{{ h.model || "-" }} · 权重 {{ h.weight }}</span>
                <span v-if="h.in_circuit_break" class="status-meta warn-text">熔断中</span>
                <span v-else-if="h.consecutive_failures > 0" class="status-meta warn-text">连续失败 {{ h.consecutive_failures }} 次</span>
              </div>
            </div>
            <el-empty v-if="llmHealthList.length === 0" description="暂无运行数据" :image-size="60" />
          </div>
        </el-card>

        <!-- LLM 提供商列表 -->
        <el-card shadow="never" class="table-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">提供商列表</span>
              <el-button
                v-if="auth.hasPermission('system:config')"
                type="primary"
                size="small"
                :icon="Plus"
                @click="openCreateLLM"
              >新增</el-button>
            </div>
          </template>
          <el-table v-loading="llmLoading" :data="llmProviders" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="model" label="模型" min-width="160" />
            <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip />
            <el-table-column prop="api_key" label="API Key" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text">{{ row.api_key || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column label="权重" width="80" align="center">
              <template #default="{ row }">{{ row.weight }}</template>
            </el-table-column>
            <el-table-column label="健康" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_healthy ? 'success' : 'danger'" size="small">
                  {{ row.is_healthy ? "正常" : "异常" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.is_active"
                  :disabled="!auth.hasPermission('system:config')"
                  @change="(val: boolean) => onToggleLLM(row, val)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Connection"
                  :loading="llmCheckingId === row.id"
                  @click="onLLMHealthCheck(row)"
                >检查</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Edit"
                  @click="openEditLLM(row)"
                >编辑</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="danger" :icon="Delete"
                  @click="onDeleteLLM(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- LLM 用量统计 -->
        <el-card shadow="never" class="usage-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">用量统计</span>
              <div class="usage-controls">
                <span>近</span>
                <el-input-number v-model="llmUsageDays" :min="1" :max="90" size="small" controls-position="right" style="width: 90px" @change="loadLLMUsage" />
                <span>天</span>
              </div>
            </div>
          </template>
          <div v-loading="llmUsageLoading">
            <div class="usage-summary">
              <el-statistic title="总调用次数" :value="llmUsage?.total_calls || 0" />
              <el-statistic title="失败次数" :value="llmUsage?.total_failures || 0" />
              <el-statistic title="输入 Tokens" :value="llmUsage?.total_tokens_in || 0" />
              <el-statistic title="输出 Tokens" :value="llmUsage?.total_tokens_out || 0" />
            </div>
            <el-table :data="llmUsage?.providers || []" border stripe style="margin-top: 12px">
              <el-table-column prop="provider_name" label="提供商" min-width="140" />
              <el-table-column prop="model" label="模型" min-width="140" />
              <el-table-column prop="total_calls" label="调用次数" width="100" />
              <el-table-column prop="success_count" label="成功" width="80" />
              <el-table-column prop="failure_count" label="失败" width="80" />
              <el-table-column prop="tokens_in" label="输入Tokens" width="120" />
              <el-table-column prop="tokens_out" label="输出Tokens" width="120" />
              <el-table-column label="平均延迟" width="100">
                <template #default="{ row }">{{ Math.round(row.avg_latency_ms) }} ms</template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ============ Embedding 配置 ============ -->
      <el-tab-pane label="Embedding 向量模型" name="embedding">
        <template #label>
          <el-icon class="tab-icon"><Histogram /></el-icon>
          <span>Embedding 向量模型</span>
        </template>

        <!-- Embedding 当前生效 provider -->
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">当前生效</span>
              <el-button size="small" :icon="RefreshRight" :loading="embActiveLoading" @click="loadEmbActive">刷新</el-button>
            </div>
          </template>
          <div v-loading="embActiveLoading" class="active-box">
            <template v-if="embActive">
              <div class="active-row">
                <el-icon class="dot" :class="embActive.is_healthy ? 'ok' : 'fail'">
                  <SuccessFilled v-if="embActive.is_healthy" />
                  <CircleCloseFilled v-else />
                </el-icon>
                <span class="active-name">{{ embActive.name || "默认" }}{{ embActive.is_fallback ? "（降级配置）" : "" }}</span>
                <el-tag v-if="embActive.is_active" type="success" size="small">生效中</el-tag>
              </div>
              <div class="active-meta">
                <span>模型：{{ embActive.model || "-" }}</span>
                <span>维度：{{ embActive.dim }}</span>
                <span>Base URL：{{ embActive.base_url || "-" }}</span>
              </div>
            </template>
            <el-empty v-else description="暂无生效 provider" :image-size="60" />
          </div>
        </el-card>

        <!-- Embedding 提供商列表 -->
        <el-card shadow="never" class="table-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">提供商列表</span>
              <el-button
                v-if="auth.hasPermission('system:config')"
                type="primary"
                size="small"
                :icon="Plus"
                @click="openCreateEmb"
              >新增</el-button>
            </div>
          </template>
          <el-table v-loading="embLoading" :data="embProviders" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="model" label="模型" min-width="160" />
            <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip />
            <el-table-column prop="api_key" label="API Key" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text">{{ row.api_key || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="dim" label="维度" width="80" align="center" />
            <el-table-column label="健康" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_healthy ? 'success' : 'danger'" size="small">
                  {{ row.is_healthy ? "正常" : "异常" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.is_active"
                  :disabled="!auth.hasPermission('system:config')"
                  @change="(val: boolean) => onToggleEmb(row, val)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Connection"
                  :loading="embCheckingId === row.id"
                  @click="onEmbHealthCheck(row)"
                >检查</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Edit"
                  @click="openEditEmb(row)"
                >编辑</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="danger" :icon="Delete"
                  @click="onDeleteEmb(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ OCR 配置 ============ -->
      <el-tab-pane label="OCR 识别服务" name="ocr">
        <template #label>
          <el-icon class="tab-icon"><Document /></el-icon>
          <span>OCR 识别服务</span>
        </template>

        <!-- OCR 当前生效 provider -->
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">当前生效</span>
              <el-button size="small" :icon="RefreshRight" :loading="ocrActiveLoading" @click="loadOCRActive">刷新</el-button>
            </div>
          </template>
          <div v-loading="ocrActiveLoading" class="active-box">
            <template v-if="ocrActive && ocrActive.is_active">
              <div class="active-row">
                <el-icon class="dot" :class="ocrActive.is_healthy ? 'ok' : 'fail'">
                  <SuccessFilled v-if="ocrActive.is_healthy" />
                  <CircleCloseFilled v-else />
                </el-icon>
                <span class="active-name">{{ ocrActive.name || "默认" }}</span>
                <el-tag v-if="ocrActive.provider_type" size="small" :type="ocrTypeColors[ocrActive.provider_type] || 'info'">
                  {{ ocrTypeLabels[ocrActive.provider_type] || ocrActive.provider_type }}
                </el-tag>
              </div>
              <div class="active-meta">
                <span>Base URL：{{ ocrActive.base_url || "-" }}</span>
                <span>模型：{{ ocrActive.model || "-" }}</span>
              </div>
            </template>
            <el-empty v-else description="暂无生效 provider" :image-size="60" />
          </div>
        </el-card>

        <!-- OCR 提供商列表 -->
        <el-card shadow="never" class="table-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">提供商列表</span>
              <el-button
                v-if="auth.hasPermission('system:config')"
                type="primary"
                size="small"
                :icon="Plus"
                @click="openCreateOCR"
              >新增</el-button>
            </div>
          </template>
          <el-table v-loading="ocrLoading" :data="ocrProviders" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="类型" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="ocrTypeColors[row.provider_type] || 'info'" size="small">
                  {{ ocrTypeLabels[row.provider_type] || row.provider_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip />
            <el-table-column prop="api_key" label="API Key" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text">{{ row.api_key || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="model" label="模型" width="140">
              <template #default="{ row }">{{ row.model || "-" }}</template>
            </el-table-column>
            <el-table-column label="健康" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_healthy ? 'success' : 'danger'" size="small">
                  {{ row.is_healthy ? "正常" : "异常" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.is_active"
                  :disabled="!auth.hasPermission('system:config')"
                  @change="(val: boolean) => onToggleOCR(row, val)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Connection"
                  :loading="ocrCheckingId === row.id"
                  @click="onOCRHealthCheck(row)"
                >检查</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="primary" :icon="Edit"
                  @click="openEditOCR(row)"
                >编辑</el-button>
                <el-button
                  v-if="auth.hasPermission('system:config')"
                  link type="danger" :icon="Delete"
                  @click="onDeleteOCR(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ LLM 新增/编辑对话框 ============ -->
    <el-dialog
      v-model="llmDialogVisible"
      :title="llmEditing ? '编辑 LLM 提供商' : '新增 LLM 提供商'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form ref="llmFormRef" :model="llmForm" :rules="llmRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="llmForm.name" placeholder="如：默认 OpenAI" />
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="llmForm.base_url" placeholder="如：https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="llmForm.api_key"
            type="password"
            show-password
            :placeholder="llmEditing ? '留空不修改' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型" prop="model">
          <el-input v-model="llmForm.model" placeholder="如：gpt-4o-mini" />
        </el-form-item>
        <el-form-item label="权重">
          <el-input-number v-model="llmForm.weight" :min="1" :max="100" />
          <span class="form-hint">负载均衡权重（多 provider 时按权重轮询）</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="llmForm.is_active" />
          <span class="form-hint">启用后自动停用其他 provider</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="llmDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="llmSubmitting" @click="onSubmitLLM">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ Embedding 新增/编辑对话框 ============ -->
    <el-dialog
      v-model="embDialogVisible"
      :title="embEditing ? '编辑 Embedding 提供商' : '新增 Embedding 提供商'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form ref="embFormRef" :model="embForm" :rules="embRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="embForm.name" placeholder="如：默认 Embedding" />
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="embForm.base_url" placeholder="如：https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="embForm.api_key"
            type="password"
            show-password
            :placeholder="embEditing ? '留空不修改' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型" prop="model">
          <el-input v-model="embForm.model" placeholder="如：text-embedding-3-small" />
        </el-form-item>
        <el-form-item label="维度" prop="dim">
          <el-input-number v-model="embForm.dim" :min="64" :max="8192" :step="128" />
          <span class="form-hint">向量维度（须与模型实际输出一致）</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="embForm.is_active" />
          <span class="form-hint">启用后自动停用其他 provider</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="embDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="embSubmitting" @click="onSubmitEmb">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ OCR 新增/编辑对话框 ============ -->
    <el-dialog
      v-model="ocrDialogVisible"
      :title="ocrEditing ? '编辑 OCR 提供商' : '新增 OCR 提供商'"
      width="580px"
      :close-on-click-modal="false"
    >
      <el-form ref="ocrFormRef" :model="ocrForm" :rules="ocrRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="ocrForm.name" placeholder="如：MinerU 在线服务" />
        </el-form-item>
        <el-form-item label="服务类型" prop="provider_type">
          <el-select v-model="ocrForm.provider_type" style="width: 100%" @change="onOCRTypeChange">
            <el-option
              v-for="(label, key) in ocrTypeLabels"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="ocrForm.base_url" placeholder="如：https://mineru.net" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="ocrForm.api_key"
            type="password"
            show-password
            :placeholder="ocrEditing ? '留空不修改' : 'Bearer Token / API Key'"
          />
        </el-form-item>
        <!-- PaddleOCR 专用：Secret Key -->
        <el-form-item v-if="ocrForm.provider_type === 'paddleocr'" label="Secret Key">
          <el-input
            v-model="ocrForm.secret_key"
            type="password"
            show-password
            placeholder="百度 API 的 Secret Key"
          />
        </el-form-item>
        <!-- MinerU 专用：参数 -->
        <template v-if="ocrForm.provider_type === 'mineru'">
          <el-form-item label="公式识别">
            <el-switch v-model="ocrForm.enable_formula" />
          </el-form-item>
          <el-form-item label="表格识别">
            <el-switch v-model="ocrForm.enable_table" />
          </el-form-item>
          <el-form-item label="识别语言">
            <el-select v-model="ocrForm.language" style="width: 100%">
              <el-option label="中文" value="ch" />
              <el-option label="英文" value="en" />
              <el-option label="自动" value="auto" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item label="模型">
          <el-input v-model="ocrForm.model" placeholder="模型/版本标识（可选）" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="ocrForm.is_active" />
          <span class="form-hint">启用后自动停用其他 provider</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ocrDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ocrSubmitting" @click="onSubmitOCR">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  Plus, Refresh, RefreshRight, Edit, Delete, Connection,
  SuccessFilled, CircleCloseFilled, WarningFilled,
  ChatDotRound, Histogram, Document,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as llmApi from "@/api/llm";
import * as embApi from "@/api/embedding";
import * as ocrApi from "@/api/ocr";
import {
  OCR_PROVIDER_TYPE_LABELS as ocrTypeLabels,
  OCR_PROVIDER_TYPE_COLORS as ocrTypeColors,
} from "@/api/ocr";
import type {
  LLMProvider, LLMProviderStatus, LLMUsageStats,
  EmbeddingProvider, EmbeddingProviderStatus,
  OCRProvider, OCRProviderStatus, OCRProviderType,
} from "@/types";

const auth = useAuthStore();
const activeTab = ref<"llm" | "embedding" | "ocr">("llm");

// ============================================================
// LLM 部分
// ============================================================
const llmLoading = ref(false);
const llmProviders = ref<LLMProvider[]>([]);
const llmHealthList = ref<LLMProviderStatus[]>([]);
const llmHealthLoading = ref(false);
const llmCheckingId = ref<string | null>(null);
const llmUsage = ref<LLMUsageStats | null>(null);
const llmUsageLoading = ref(false);
const llmUsageDays = ref(7);

async function loadLLMProviders() {
  llmLoading.value = true;
  try {
    llmProviders.value = await llmApi.getLLMProviders();
  } finally {
    llmLoading.value = false;
  }
}

async function loadLLMHealth() {
  llmHealthLoading.value = true;
  try {
    llmHealthList.value = await llmApi.getLLMHealth();
  } catch {
    // 拦截器已提示
  } finally {
    llmHealthLoading.value = false;
  }
}

async function loadLLMUsage() {
  llmUsageLoading.value = true;
  try {
    llmUsage.value = await llmApi.getLLMUsageStats({ days: llmUsageDays.value });
  } finally {
    llmUsageLoading.value = false;
  }
}

async function onToggleLLM(row: LLMProvider, val: boolean) {
  try {
    await llmApi.updateLLMProvider(row.id, {
      name: row.name,
      base_url: row.base_url,
      model: row.model,
      weight: row.weight,
      is_active: val,
    });
    row.is_active = val;
    ElMessage.success(val ? "已启用" : "已禁用");
    await Promise.all([loadLLMProviders(), loadLLMHealth()]);
  } catch {
    // 拦截器已提示
  }
}

async function onLLMHealthCheck(row: LLMProvider) {
  llmCheckingId.value = row.id;
  try {
    const res = await llmApi.healthCheckProvider(row.id);
    ElMessage[res.is_healthy ? "success" : "error"](
      `${row.name}：${res.is_healthy ? "正常" : "异常"}${res.error ? `（${res.error}）` : ""}`,
    );
    await Promise.all([loadLLMProviders(), loadLLMHealth()]);
  } finally {
    llmCheckingId.value = null;
  }
}

async function onDeleteLLM(row: LLMProvider) {
  try {
    await ElMessageBox.confirm(`确定删除提供商「${row.name}」吗？`, "提示", { type: "warning" });
    await llmApi.deleteLLMProvider(row.id);
    ElMessage.success("已删除");
    await loadLLMAll();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// LLM 表单
const llmDialogVisible = ref(false);
const llmSubmitting = ref(false);
const llmEditing = ref<LLMProvider | null>(null);
const llmFormRef = ref<FormInstance | null>(null);

const llmForm = reactive({
  name: "",
  base_url: "",
  api_key: "",
  model: "",
  weight: 1,
  is_active: true,
});

const llmRules = computed<FormRules>(() => ({
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  base_url: [{ required: true, message: "请输入 Base URL", trigger: "blur" }],
  api_key: llmEditing.value
    ? [] // 编辑时留空不修改
    : [{ required: true, message: "请输入 API Key", trigger: "blur" }],
  model: [{ required: true, message: "请输入模型名", trigger: "blur" }],
}));

function resetLLMForm() {
  llmForm.name = "";
  llmForm.base_url = "";
  llmForm.api_key = "";
  llmForm.model = "";
  llmForm.weight = 1;
  llmForm.is_active = true;
}

function openCreateLLM() {
  llmEditing.value = null;
  resetLLMForm();
  llmDialogVisible.value = true;
}

function openEditLLM(row: LLMProvider) {
  llmEditing.value = row;
  llmForm.name = row.name;
  llmForm.base_url = row.base_url;
  llmForm.api_key = ""; // 编辑时留空不修改
  llmForm.model = row.model;
  llmForm.weight = row.weight;
  llmForm.is_active = row.is_active;
  llmDialogVisible.value = true;
}

async function onSubmitLLM() {
  if (!llmFormRef.value) return;
  const valid = await llmFormRef.value.validate().catch(() => false);
  if (!valid) return;
  llmSubmitting.value = true;
  try {
    const payload: llmApi.LLMProviderPayload = {
      name: llmForm.name,
      base_url: llmForm.base_url,
      model: llmForm.model,
      weight: llmForm.weight,
      is_active: llmForm.is_active,
    };
    // 新增必填 api_key；编辑时留空不传
    if (llmForm.api_key) payload.api_key = llmForm.api_key;
    else if (!llmEditing.value) payload.api_key = "";

    if (llmEditing.value) {
      await llmApi.updateLLMProvider(llmEditing.value.id, payload);
      ElMessage.success("已更新");
    } else {
      await llmApi.createLLMProvider(payload);
      ElMessage.success("已创建");
    }
    llmDialogVisible.value = false;
    await loadLLMAll();
  } finally {
    llmSubmitting.value = false;
  }
}

// ============================================================
// Embedding 部分
// ============================================================
const embLoading = ref(false);
const embProviders = ref<EmbeddingProvider[]>([]);
const embActive = ref<EmbeddingProviderStatus | null>(null);
const embActiveLoading = ref(false);
const embCheckingId = ref<string | null>(null);

async function loadEmbProviders() {
  embLoading.value = true;
  try {
    embProviders.value = await embApi.getEmbeddingProviders();
  } finally {
    embLoading.value = false;
  }
}

async function loadEmbActive() {
  embActiveLoading.value = true;
  try {
    embActive.value = await embApi.getActiveEmbeddingProvider();
  } catch {
    // 拦截器已提示
  } finally {
    embActiveLoading.value = false;
  }
}

async function onToggleEmb(row: EmbeddingProvider, val: boolean) {
  try {
    await embApi.updateEmbeddingProvider(row.id, {
      name: row.name,
      base_url: row.base_url,
      model: row.model,
      dim: row.dim,
      is_active: val,
    });
    row.is_active = val;
    ElMessage.success(val ? "已启用" : "已禁用");
    await Promise.all([loadEmbProviders(), loadEmbActive()]);
  } catch {
    // 拦截器已提示
  }
}

async function onEmbHealthCheck(row: EmbeddingProvider) {
  embCheckingId.value = row.id;
  try {
    const res = await embApi.healthCheckEmbeddingProvider(row.id);
    ElMessage[res.is_healthy ? "success" : "error"](
      `${row.name}：${res.is_healthy ? "正常" : "异常"}${res.latency_ms != null ? `（${res.latency_ms} ms）` : ""}${res.error ? ` - ${res.error}` : ""}`,
    );
    await Promise.all([loadEmbProviders(), loadEmbActive()]);
  } finally {
    embCheckingId.value = null;
  }
}

async function onDeleteEmb(row: EmbeddingProvider) {
  try {
    await ElMessageBox.confirm(`确定删除提供商「${row.name}」吗？`, "提示", { type: "warning" });
    await embApi.deleteEmbeddingProvider(row.id);
    ElMessage.success("已删除");
    await loadEmbAll();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// Embedding 表单
const embDialogVisible = ref(false);
const embSubmitting = ref(false);
const embEditing = ref<EmbeddingProvider | null>(null);
const embFormRef = ref<FormInstance | null>(null);

const embForm = reactive({
  name: "",
  base_url: "",
  api_key: "",
  model: "",
  dim: 1024,
  is_active: true,
});

const embRules = computed<FormRules>(() => ({
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  base_url: [{ required: true, message: "请输入 Base URL", trigger: "blur" }],
  api_key: embEditing.value
    ? [] // 编辑时留空不修改
    : [{ required: true, message: "请输入 API Key", trigger: "blur" }],
  model: [{ required: true, message: "请输入模型名", trigger: "blur" }],
  dim: [{ required: true, message: "请输入向量维度", trigger: "blur" }],
}));

function resetEmbForm() {
  embForm.name = "";
  embForm.base_url = "";
  embForm.api_key = "";
  embForm.model = "";
  embForm.dim = 1024;
  embForm.is_active = true;
}

function openCreateEmb() {
  embEditing.value = null;
  resetEmbForm();
  embDialogVisible.value = true;
}

function openEditEmb(row: EmbeddingProvider) {
  embEditing.value = row;
  embForm.name = row.name;
  embForm.base_url = row.base_url;
  embForm.api_key = "";
  embForm.model = row.model;
  embForm.dim = row.dim;
  embForm.is_active = row.is_active;
  embDialogVisible.value = true;
}

async function onSubmitEmb() {
  if (!embFormRef.value) return;
  const valid = await embFormRef.value.validate().catch(() => false);
  if (!valid) return;
  embSubmitting.value = true;
  try {
    const payload: embApi.EmbeddingProviderPayload = {
      name: embForm.name,
      base_url: embForm.base_url,
      model: embForm.model,
      dim: embForm.dim,
      is_active: embForm.is_active,
    };
    if (embForm.api_key) payload.api_key = embForm.api_key;
    else if (!embEditing.value) payload.api_key = "";

    if (embEditing.value) {
      await embApi.updateEmbeddingProvider(embEditing.value.id, payload);
      ElMessage.success("已更新");
    } else {
      await embApi.createEmbeddingProvider(payload);
      ElMessage.success("已创建");
    }
    embDialogVisible.value = false;
    await loadEmbAll();
  } finally {
    embSubmitting.value = false;
  }
}

// ============================================================
// 汇总加载
// ============================================================
async function loadLLMAll() {
  await Promise.all([loadLLMProviders(), loadLLMHealth(), loadLLMUsage()]);
}

async function loadEmbAll() {
  await Promise.all([loadEmbProviders(), loadEmbActive()]);
}

// ============================================================
// OCR 部分
// ============================================================
const ocrLoading = ref(false);
const ocrProviders = ref<OCRProvider[]>([]);
const ocrActive = ref<OCRProviderStatus | null>(null);
const ocrActiveLoading = ref(false);
const ocrCheckingId = ref<string | null>(null);

async function loadOCRProviders() {
  ocrLoading.value = true;
  try {
    ocrProviders.value = await ocrApi.getOCRProviders();
  } finally {
    ocrLoading.value = false;
  }
}

async function loadOCRActive() {
  ocrActiveLoading.value = true;
  try {
    ocrActive.value = await ocrApi.getActiveOCRProvider();
  } catch {
    // 拦截器已提示
  } finally {
    ocrActiveLoading.value = false;
  }
}

async function onToggleOCR(row: OCRProvider, val: boolean) {
  try {
    await ocrApi.updateOCRProvider(row.id, {
      name: row.name,
      provider_type: row.provider_type,
      base_url: row.base_url,
      is_active: val,
    });
    row.is_active = val;
    ElMessage.success(val ? "已启用" : "已禁用");
    await Promise.all([loadOCRProviders(), loadOCRActive()]);
  } catch {
    // 拦截器已提示
  }
}

async function onOCRHealthCheck(row: OCRProvider) {
  ocrCheckingId.value = row.id;
  try {
    const res = await ocrApi.healthCheckOCRProvider(row.id);
    ElMessage[res.is_healthy ? "success" : "error"](
      `${row.name}：${res.is_healthy ? "正常" : "异常"}${res.latency_ms != null ? `（${res.latency_ms} ms）` : ""}${res.error ? ` - ${res.error}` : ""}`,
    );
    await Promise.all([loadOCRProviders(), loadOCRActive()]);
  } finally {
    ocrCheckingId.value = null;
  }
}

async function onDeleteOCR(row: OCRProvider) {
  try {
    await ElMessageBox.confirm(`确定删除提供商「${row.name}」吗？`, "提示", { type: "warning" });
    await ocrApi.deleteOCRProvider(row.id);
    ElMessage.success("已删除");
    await loadOCRAll();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// OCR 表单
const ocrDialogVisible = ref(false);
const ocrSubmitting = ref(false);
const ocrEditing = ref<OCRProvider | null>(null);
const ocrFormRef = ref<FormInstance | null>(null);

const ocrForm = reactive({
  name: "",
  provider_type: "mineru" as OCRProviderType,
  base_url: "",
  api_key: "",
  model: "",
  // PaddleOCR 专用
  secret_key: "",
  // MinerU 专用
  enable_formula: true,
  enable_table: true,
  language: "ch",
  is_active: true,
});

const ocrRules = computed<FormRules>(() => ({
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  provider_type: [{ required: true, message: "请选择服务类型", trigger: "change" }],
  base_url: [{ required: true, message: "请输入 Base URL", trigger: "blur" }],
  api_key: ocrEditing.value
    ? [] // 编辑时留空不修改
    : [{ required: true, message: "请输入 API Key", trigger: "blur" }],
}));

function resetOCRForm() {
  ocrForm.name = "";
  ocrForm.provider_type = "mineru";
  ocrForm.base_url = "";
  ocrForm.api_key = "";
  ocrForm.model = "";
  ocrForm.secret_key = "";
  ocrForm.enable_formula = true;
  ocrForm.enable_table = true;
  ocrForm.language = "ch";
  ocrForm.is_active = true;
}

/** 类型切换时自动填充默认 base_url */
function onOCRTypeChange(val: OCRProviderType) {
  if (val === "mineru" && !ocrForm.base_url) {
    ocrForm.base_url = "https://mineru.net";
  } else if (val === "paddleocr" && !ocrForm.base_url) {
    ocrForm.base_url = "https://aip.baidubce.com";
  } else if (val === "local" && !ocrForm.base_url) {
    ocrForm.base_url = "local://rapidocr";
  }
}

function openCreateOCR() {
  ocrEditing.value = null;
  resetOCRForm();
  ocrForm.base_url = "https://mineru.net"; // 默认 MinerU
  ocrDialogVisible.value = true;
}

function openEditOCR(row: OCRProvider) {
  ocrEditing.value = row;
  ocrForm.name = row.name;
  ocrForm.provider_type = row.provider_type;
  ocrForm.base_url = row.base_url;
  ocrForm.api_key = ""; // 编辑时留空不修改
  ocrForm.model = row.model || "";
  // 从 metadata_json 读取扩展参数
  const meta = row.metadata_json || {};
  ocrForm.secret_key = meta.secret_key || "";
  ocrForm.enable_formula = meta.enable_formula !== false;
  ocrForm.enable_table = meta.enable_table !== false;
  ocrForm.language = meta.language || "ch";
  ocrForm.is_active = row.is_active;
  ocrDialogVisible.value = true;
}

async function onSubmitOCR() {
  if (!ocrFormRef.value) return;
  const valid = await ocrFormRef.value.validate().catch(() => false);
  if (!valid) return;
  ocrSubmitting.value = true;
  try {
    // 构建 metadata_json（按 provider_type 存储扩展参数）
    const metadata: Record<string, any> = {};
    if (ocrForm.provider_type === "paddleocr" && ocrForm.secret_key) {
      metadata.secret_key = ocrForm.secret_key;
    } else if (ocrForm.provider_type === "mineru") {
      metadata.enable_formula = ocrForm.enable_formula;
      metadata.enable_table = ocrForm.enable_table;
      metadata.language = ocrForm.language;
    }

    const payload: ocrApi.OCRProviderPayload = {
      name: ocrForm.name,
      provider_type: ocrForm.provider_type,
      base_url: ocrForm.base_url,
      model: ocrForm.model || null,
      is_active: ocrForm.is_active,
      metadata_json: Object.keys(metadata).length > 0 ? metadata : null,
    };
    if (ocrForm.api_key) payload.api_key = ocrForm.api_key;
    else if (!ocrEditing.value) payload.api_key = "";

    if (ocrEditing.value) {
      await ocrApi.updateOCRProvider(ocrEditing.value.id, payload);
      ElMessage.success("已更新");
    } else {
      await ocrApi.createOCRProvider(payload);
      ElMessage.success("已创建");
    }
    ocrDialogVisible.value = false;
    await loadOCRAll();
  } finally {
    ocrSubmitting.value = false;
  }
}

async function loadOCRAll() {
  await Promise.all([loadOCRProviders(), loadOCRActive()]);
}

async function loadAll() {
  await Promise.all([loadLLMAll(), loadEmbAll(), loadOCRAll()]);
}

onMounted(() => {
  loadAll();
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
.config-tabs {
  min-height: 400px;
}
.tab-icon {
  margin-right: 4px;
  vertical-align: middle;
}
.card-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-card {
  margin-bottom: 12px;
}
.status-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.status-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 4px;
  border: 1px solid #ebeef5;
  font-size: 13px;
}
.status-item.ok {
  background: #f0f9eb;
  border-color: #e1f3d8;
  color: #67c23a;
}
.status-item.warn {
  background: #fdf6ec;
  border-color: #faecd8;
  color: #e6a23c;
}
.status-item.fail {
  background: #fef0f0;
  border-color: #fde2e2;
  color: #f56c6c;
}
.status-info {
  display: flex;
  flex-direction: column;
}
.status-name {
  font-weight: 600;
}
.status-meta {
  font-size: 12px;
  color: #909399;
}
.warn-text {
  color: #e6a23c;
}
.dot {
  font-size: 18px;
}
.mono-text {
  font-family: "Courier New", monospace;
  font-size: 12px;
}
.table-card {
  margin-bottom: 12px;
}
.usage-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.usage-summary {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
}
.active-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.active-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.active-name {
  font-size: 15px;
  font-weight: 600;
}
.active-meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: #606266;
  margin-left: 26px;
}
.form-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
