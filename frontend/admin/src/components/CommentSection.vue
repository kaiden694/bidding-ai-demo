<template>
  <div class="comment-section">
    <div class="section-title">
      <span>协作评论</span>
      <el-tag size="small" round>{{ commentCount }}</el-tag>
    </div>

    <!-- 评论输入框 -->
    <div class="comment-input">
      <el-input
        v-model="newContent"
        type="textarea"
        :rows="3"
        :placeholder="placeholder"
      />
      <div class="input-actions">
        <el-tooltip content="使用 @ 可提及他人，AI 会自动解析关键议题" placement="top">
          <el-button link :icon="InfoFilled">@ 提及提示</el-button>
        </el-tooltip>
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="submitting"
          :disabled="!newContent.trim()"
          @click="onSubmit"
        >发表</el-button>
      </div>
    </div>

    <!-- 评论列表（嵌套展示） -->
    <div v-loading="loading" class="comment-list">
      <div v-for="c in treeComments" :key="c.id" class="comment-node">
        <div class="comment-head">
          <el-avatar :size="28" class="comment-avatar">
            {{ avatarOf(c) }}
          </el-avatar>
          <span class="comment-author">{{ c.author_name || "匿名" }}</span>
          <span class="comment-time">{{ formatTime(c.created_at) }}</span>
          <el-tag v-if="c.analysis" type="success" size="small" effect="plain">
            <el-icon><MagicStick /></el-icon> AI 已分析
          </el-tag>
        </div>
        <div class="comment-body">{{ c.content }}</div>
        <div v-if="c.analysis" class="comment-analysis">
          <span class="analysis-label">AI 分析：</span>
          <span>{{ c.analysis }}</span>
        </div>
        <div class="comment-actions">
          <el-button
            link
            type="primary"
            size="small"
            @click="openReply(c)"
          >回复</el-button>
          <el-button
            v-if="!c.analysis"
            link
            type="primary"
            size="small"
            :loading="analyzingId === c.id"
            @click="onAnalyze(c)"
          >AI 分析</el-button>
          <el-button
            v-if="canDelete(c)"
            link
            type="danger"
            size="small"
            @click="onDelete(c)"
          >删除</el-button>
        </div>

        <!-- 子评论（缩进展示） -->
        <div v-if="c.children?.length" class="reply-list">
          <div v-for="r in c.children" :key="r.id" class="comment-node reply">
            <div class="comment-head">
              <el-avatar :size="24" class="comment-avatar">
                {{ avatarOf(r) }}
              </el-avatar>
              <span class="comment-author">{{ r.author_name || "匿名" }}</span>
              <span class="comment-time">{{ formatTime(r.created_at) }}</span>
            </div>
            <div class="comment-body">{{ r.content }}</div>
            <div class="comment-actions">
              <el-button
                v-if="canDelete(r)"
                link
                type="danger"
                size="small"
                @click="onDelete(r)"
              >删除</el-button>
            </div>
          </div>
        </div>
      </div>
      <el-empty v-if="!loading && commentCount === 0" description="暂无评论" :image-size="60" />
    </div>

    <!-- 回复对话框 -->
    <el-dialog
      v-model="replyDialogVisible"
      title="回复评论"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-width="80px">
        <el-form-item label="原评论">
          <div class="reply-origin">{{ replyTarget?.content }}</div>
        </el-form-item>
        <el-form-item label="回复">
          <el-input v-model="replyContent" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="replyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmitReply">发表回复</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Promotion,
  MagicStick,
  InfoFilled,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import * as commentApi from "@/api/comment";
import type { CommentItem } from "@/types";

const props = defineProps<{
  /** 项目 ID */
  projectId: string;
  /** 实体类型：如 project / bid_draft / todo */
  entityType: string;
  /** 实体 ID */
  entityId: string;
  /** 占位提示 */
  placeholder?: string;
}>();

const auth = useAuthStore();

const loading = ref(false);
const comments = ref<CommentItem[]>([]);
const newContent = ref("");
const submitting = ref(false);
const analyzingId = ref<string | null>(null);

const placeholder = computed(
  () => props.placeholder || "发表评论，使用 @ 可提及他人…",
);

/** 扁平评论总数（父 + 子） */
const commentCount = computed(() => {
  let count = 0;
  comments.value.forEach((c) => {
    count += 1;
    if (c.children) count += c.children.length;
  });
  return count;
});

/** 一层嵌套：父评论 + 直接子评论 */
const treeComments = computed(() => {
  const parents = comments.value.filter((c) => !c.parent_id);
  const childrenMap = new Map<string, CommentItem[]>();
  comments.value
    .filter((c) => c.parent_id)
    .forEach((c) => {
      const arr = childrenMap.get(c.parent_id!) || [];
      arr.push(c);
      childrenMap.set(c.parent_id!, arr);
    });
  return parents.map((p) => ({ ...p, children: childrenMap.get(p.id) || [] }));
});

async function loadComments() {
  if (!props.projectId) return;
  loading.value = true;
  try {
    comments.value = await commentApi.getComments(props.projectId, {
      entity_type: props.entityType,
      entity_id: props.entityId,
    });
  } finally {
    loading.value = false;
  }
}

async function onSubmit() {
  if (!newContent.value.trim()) return;
  submitting.value = true;
  try {
    await commentApi.createComment(props.projectId, {
      entity_type: props.entityType,
      entity_id: props.entityId,
      content: newContent.value,
    });
    newContent.value = "";
    ElMessage.success("评论已发表");
    await loadComments();
  } finally {
    submitting.value = false;
  }
}

// ---- 回复 ----
const replyDialogVisible = ref(false);
const replyTarget = ref<CommentItem | null>(null);
const replyContent = ref("");

function openReply(c: CommentItem) {
  replyTarget.value = c;
  replyContent.value = "";
  replyDialogVisible.value = true;
}

async function onSubmitReply() {
  if (!replyTarget.value || !replyContent.value.trim()) return;
  submitting.value = true;
  try {
    await commentApi.createComment(props.projectId, {
      entity_type: props.entityType,
      entity_id: props.entityId,
      content: replyContent.value,
      parent_id: replyTarget.value.id,
    });
    ElMessage.success("回复已发表");
    replyDialogVisible.value = false;
    await loadComments();
  } finally {
    submitting.value = false;
  }
}

// ---- AI 分析 ----
async function onAnalyze(c: CommentItem) {
  analyzingId.value = c.id;
  try {
    const res = await commentApi.analyzeComment(c.id);
    c.analysis = res.analysis;
    ElMessage.success("AI 分析完成");
  } finally {
    analyzingId.value = null;
  }
}

// ---- 删除 ----
function canDelete(c: CommentItem): boolean {
  if (!auth.hasPermission("comment:delete")) return false;
  // 作者本人或 admin
  return auth.isAdmin || c.author_id === auth.userId;
}

async function onDelete(c: CommentItem) {
  try {
    await ElMessageBox.confirm("确定删除该评论吗？", "提示", { type: "warning" });
    await commentApi.deleteComment(c.id);
    ElMessage.success("已删除");
    await loadComments();
  } catch (e) {
    if (e !== "cancel") {
      // 其它错误由拦截器提示
    }
  }
}

// ---- 工具 ----
function avatarOf(c: CommentItem): string {
  const name = c.author_name || "?";
  return name.charAt(0).toUpperCase();
}

function formatTime(s: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

onMounted(() => {
  loadComments();
});
</script>

<style scoped>
.comment-section {
  width: 100%;
}
.section-title {
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.comment-input {
  margin-bottom: 12px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}
.comment-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.comment-node {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 12px;
  background: #fff;
}
.comment-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.comment-avatar {
  background: #409eff;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}
.comment-author {
  font-weight: 600;
  font-size: 13px;
}
.comment-time {
  color: #909399;
  font-size: 12px;
}
.comment-body {
  font-size: 14px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}
.comment-analysis {
  margin-top: 6px;
  padding: 6px 8px;
  background: #f0f9eb;
  border-radius: 4px;
  font-size: 12px;
  color: #67c23a;
}
.analysis-label {
  font-weight: 600;
}
.comment-actions {
  margin-top: 4px;
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}
.reply-list {
  margin-top: 8px;
  padding-left: 32px;
  border-left: 2px solid #ebeef5;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.reply {
  background: #fafafa;
  border: none;
  padding: 6px 8px;
}
.reply-origin {
  background: #f5f7fa;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
  white-space: pre-wrap;
}
</style>
