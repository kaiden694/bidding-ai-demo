<template>
  <div class="placeholder">
    <el-result icon="info" title="待实现" :sub-title="`路由：${path}`">
      <template #extra>
        <el-tag type="info">{{ taskTag }}</el-tag>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from "vue-router";
import { computed } from "vue";

const route = useRoute();
const path = computed(() => route.path);
const taskTag = computed(() => (route.meta?.task as string) ?? "T6.x");
</script>

<style scoped>
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>
