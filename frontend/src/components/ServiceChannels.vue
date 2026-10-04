<template>
  <section v-loading="loading">
    <div class="card-header block-gap"><h3>服务与通道</h3><div class="actions"><el-button :loading="checking" :disabled="!isAdmin" @click="checkHealth">检查服务状态</el-button><el-button @click="load">刷新</el-button></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="block-gap" />
    <el-table :data="providers" class="block-gap">
      <el-table-column label="服务" min-width="120"><template #default="{ row }">{{ PROVIDER_KIND_LABEL[row.kind] || row.kind }}</template></el-table-column>
      <el-table-column prop="name" label="通道" width="120" />
      <el-table-column label="状态" width="110"><template #default="{ row }">{{ healthLabel(row.kind, row.mock) }}</template></el-table-column>
      <el-table-column label="说明" min-width="220"><template #default="{ row }">{{ health?.items.find(item => item.kind === row.kind)?.detail || row.detail || '尚未执行健康检查' }}</template></el-table-column>
    </el-table>
    <p class="muted">{{ health?.checked_at ? `最近检查：${formatDateTime(health.checked_at)}` : '配置完成后可检查服务状态。' }}</p>
    <template v-if="isAdmin">
      <el-alert type="info" :closable="false" title="密钥不会回显。留空且未修改时保留原密钥，主动清空后保存会删除该密钥。" class="block-gap" />
      <el-form label-position="top" class="service-form">
        <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
          <el-select v-if="field.options.length" v-model="form[field.key]" @change="dirty[field.key] = true" style="width: 100%"><el-option v-for="option in field.options" :key="option" :value="option" :label="option" /></el-select>
          <el-input v-else v-model="form[field.key]" :type="field.secret ? 'password' : 'text'" autocomplete="new-password" :placeholder="field.secret && field.configured ? '已设置；输入新值替换' : '未设置'" clearable @input="dirty[field.key] = true" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" :disabled="!Object.keys(dirty).length" @click="save">保存服务配置</el-button>
    </template>
    <p v-else class="muted">服务配置仅管理员可以修改。</p>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { integrationApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { ProviderItem, ServiceConfigField, ServiceHealth } from '@/types/api'
import { PROVIDER_KIND_LABEL, formatDateTime } from '@/utils/format'
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'super_admin')
const providers = ref<ProviderItem[]>([]), fields = ref<ServiceConfigField[]>([]), health = ref<ServiceHealth | null>(null)
const form = reactive<Record<string, string>>({}), dirty = reactive<Record<string, boolean>>({})
const loading = ref(false), checking = ref(false), saving = ref(false), error = ref('')
const healthLabels: Record<string, string> = { healthy: '正常', failed: '故障', mock: '模拟', unconfigured: '未配置', unknown: '无法确认' }
function healthLabel(kind: string, mock: boolean) { const state = health.value?.items.find(item => item.kind === kind)?.state; return state ? healthLabels[state] || state : mock ? '模拟' : '未检查' }
function resetFields(next: ServiceConfigField[]) { fields.value = next; next.forEach(field => { form[field.key] = field.value }); Object.keys(dirty).forEach(key => delete dirty[key]) }
async function load() {
  loading.value = true
  try {
    const [s, h, c] = await Promise.all([integrationApi.status(), integrationApi.health(), isAdmin.value ? integrationApi.config() : Promise.resolve([])])
    providers.value = s.items; health.value = h; resetFields(c); error.value = s.available ? '' : s.error || '服务不可用'
  } catch { error.value = '服务信息加载失败，请重试' } finally { loading.value = false }
}
async function checkHealth() { checking.value = true; try { health.value = await integrationApi.checkHealth() } finally { checking.value = false } }
async function save() {
  saving.value = true
  try { const payload = Object.fromEntries(Object.keys(dirty).map(key => [key, form[key] || ''])); resetFields(await integrationApi.saveConfig(payload)); health.value = null; providers.value = (await integrationApi.status()).items; ElMessage.success('服务配置已保存') } finally { saving.value = false }
}
onMounted(load)
</script>
<style scoped>
.service-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
@media(max-width: 768px) { .service-form { grid-template-columns: minmax(0, 1fr); } }
</style>
