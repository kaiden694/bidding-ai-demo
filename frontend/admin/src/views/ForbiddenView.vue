<template>
  <div class="forbidden">
    <el-result
      icon="warning"
      title="403 无权限"
      sub-title="您没有访问该页面的权限，请联系管理员"
    >
      <template #extra>
        <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
// 403 无权限页
</script>

<style scoped>
.forbidden {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: #f5f7fa;
}
</style>
