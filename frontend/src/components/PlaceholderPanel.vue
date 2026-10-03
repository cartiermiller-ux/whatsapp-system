<template>
  <el-card shadow="never" class="placeholder-panel">
    <el-empty :description="description">
      <template #image>
        <el-icon :size="72" color="#a3a3a3"><Tools /></el-icon>
      </template>
      <div class="ph-body">
        <el-tag type="info" effect="plain">待接入后端接口</el-tag>
        <p v-if="api" class="ph-api">
          期望接口：<code class="mono">{{ api }}</code>
        </p>
        <p v-if="tip" class="ph-tip">{{ tip }}</p>
      </div>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  /** 页面/模块标题说明 */
  description: string
  /** 期望对接的后端接口路径 */
  api?: string
  /** 补充提示 */
  tip?: string
}>()
</script>

<style scoped>
.placeholder-panel {
  margin-bottom: 16px;
}
</style>
