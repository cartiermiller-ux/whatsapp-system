<template>
  <section v-loading="loading">
    <div class="filter-bar">
      <el-input v-model="name" placeholder="租户名称" maxlength="64" style="width: 240px" @keyup.enter="create" />
      <el-button type="primary" :disabled="!name.trim()" @click="create">新建租户</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="rows">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="租户" min-width="160" />
      <el-table-column prop="users" label="用户数" width="100" />
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column label="创建时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link :disabled="row.name === auth.tenant" @click="toggle(row)">{{ row.status === 'active' ? '停用' : '启用' }}</el-button></template></el-table-column>
    </el-table>
  </section>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
const auth = useAuthStore()
const name = ref(''), loading = ref(false)
const rows = ref<Awaited<ReturnType<typeof adminApi.tenants>>>([])
async function load() {
  loading.value = true
  try { rows.value = await adminApi.tenants() } finally { loading.value = false }
}
async function create() {
  if (!name.value.trim() || loading.value) return
  loading.value = true
  try { await adminApi.createTenant(name.value.trim()); name.value = ''; ElMessage.success('租户已创建') }
  catch { return } finally { loading.value = false }
  await load()
}
async function toggle(row: typeof rows.value[number]) {
  const status = row.status === 'active' ? 'disabled' : 'active'
  try { await ElMessageBox.confirm(status === 'disabled' ? `停用「${row.name}」后，其用户将退出登录，任务停止继续执行。` : `启用「${row.name}」？`, '租户状态') } catch { return }
  await adminApi.updateTenant(row.id, status)
  await load()
}
onMounted(load)
</script>
