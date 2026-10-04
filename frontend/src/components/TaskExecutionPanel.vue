<template>
  <section>
    <div class="actions section-gap">
      <el-button v-if="['pending', 'running'].includes(status)" :loading="acting" @click="control('pause')">暂停</el-button>
      <el-button v-if="status === 'paused'" :loading="acting" @click="control('resume')">恢复</el-button>
      <el-button v-if="status === 'failed'" :loading="acting" @click="control('retry')">重试失败目标</el-button>
      <el-button v-if="['pending', 'running', 'paused'].includes(status)" type="danger" plain :loading="acting" @click="control('cancel')">取消任务</el-button>
    </div>
    <h3>执行明细</h3>
    <el-table :data="executions" v-loading="loading" size="small">
      <el-table-column label="目标" min-width="150"><template #default="{ row }">{{ row.target || row.target_id }}</template></el-table-column>
      <el-table-column label="结果" width="100"><template #default="{ row }">{{ executionLabels[row.status] || row.status }}</template></el-table-column>
      <el-table-column label="回执" width="90"><template #default="{ row }">{{ row.read_at ? '已阅读' : row.delivered_at ? '已送达' : row.status === 'succeeded' && kind === 'mass-send' ? '等待回执' : '—' }}</template></el-table-column>
      <el-table-column prop="error" label="失败原因" min-width="180" show-overflow-tooltip />
      <el-table-column v-if="isAdmin" label="核对" width="100"><template #default="{ row }"><el-dropdown v-if="row.status === 'uncertain'" @command="(status: string) => resolve(row, status)"><el-button link type="primary" :disabled="acting">核对结果</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="succeeded">已确认成功</el-dropdown-item><el-dropdown-item command="failed">已确认失败</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
      <el-table-column prop="attempts" label="执行次数" width="85" />
    </el-table>
    <div class="pager"><el-pagination v-model:current-page="executionPage" :page-size="20" :total="executionTotal" layout="total, prev, next" @current-change="load" /></div>
    <h3>日志</h3>
    <el-table :data="logs" size="small">
      <el-table-column label="时间" width="160"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="结果" width="90"><template #default="{ row }">{{ executionLabels[row.result] || TASK_STATUS_LABEL[row.result] || row.result }}</template></el-table-column>
      <el-table-column prop="detail" label="说明" min-width="220" />
    </el-table>
    <div class="pager"><el-pagination v-model:current-page="logPage" :page-size="20" :total="logTotal" layout="total, prev, next" @current-change="load" /></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="section-gap" />
  </section>
</template>
<script setup lang="ts">
import { onMounted, onBeforeUnmount, onDeactivated, onActivated, computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { TaskExecutionRow, TaskLogRow } from '@/types/api'
import { formatDateTime, TASK_STATUS_LABEL } from '@/utils/format'
const props = defineProps<{ kind: 'mass-send' | 'pull-group'; taskId: number; status: string }>()
const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore()
const isAdmin = computed(() => ['super_admin', 'agent_admin'].includes(auth.user?.role || ''))
const executions = ref<TaskExecutionRow[]>([]), logs = ref<TaskLogRow[]>([])
const executionPage = ref(1), logPage = ref(1), executionTotal = ref(0), logTotal = ref(0)
const loading = ref(false), acting = ref(false), error = ref('')
const executionLabels: Record<string, string> = { pending: '等待', executing: '执行中', succeeded: '执行成功', success: '成功', failed: '失败', uncertain: '结果待核对' }
let timer: number | undefined
async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const [e, l] = await Promise.all([taskApi.executions(props.kind, props.taskId, { page: executionPage.value, size: 20 }), taskApi.logs(props.kind, props.taskId, { page: logPage.value, size: 20 })])
    executions.value = e.list; executionTotal.value = e.total; logs.value = l.list; logTotal.value = l.total; error.value = ''
  } catch { error.value = '执行记录加载失败，请刷新重试' } finally { loading.value = false }
}
async function control(action: string) {
  if (action === 'cancel') {
    try { await ElMessageBox.confirm('确认取消任务？已经执行的目标会保留记录。', '取消任务', { type: 'warning' }) } catch { return }
  }
  acting.value = true
  try { await taskApi.control(props.kind, props.taskId, action); emit('changed'); await load(); ElMessage.success('任务状态已更新') } finally { acting.value = false }
}
async function resolve(row: TaskExecutionRow, status: string) {
  let note: string
  try {
    const result = await ElMessageBox.prompt(`请先核对通道记录，确认该目标${status === 'succeeded' ? '已成功执行' : '未执行成功'}，再填写核对依据。`, '人工核对执行结果', { inputValidator: (value: string) => value?.trim().length >= 5 || '请填写至少 5 个字的核对依据', confirmButtonText: '确认核对' })
    note = result.value.trim()
  } catch { return }
  acting.value = true
  try { await taskApi.resolve(props.kind, props.taskId, row.id, { status, note }); emit('changed'); await load(); ElMessage.success('核对结果已保存') } finally { acting.value = false }
}
watch(() => props.taskId, () => { executionPage.value = 1; logPage.value = 1; executions.value = []; logs.value = []; load() })
function start() { if (timer === undefined) { load(); timer = window.setInterval(load, 3000) } }
onMounted(start); onActivated(start)
function stop() { window.clearInterval(timer); timer = undefined }
onBeforeUnmount(stop); onDeactivated(stop)
</script>
