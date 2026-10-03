<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>群发任务</h2>
        <div class="sub">创建任务 · 实时进度 · 效果统计</div>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="createVisible = true">新建群发任务</el-button>
      </div>
    </div>

        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>群发任务列表</span>
              <el-select
                v-model="statusFilter"
                size="small"
                placeholder="全部状态"
                clearable
                style="width: 130px"
                @change="reload"
              >
                <el-option label="排队中" value="pending" />
                <el-option label="进行中" value="running" />
                <el-option label="已完成" value="done" />
              </el-select>
            </div>
          </template>

          <el-table v-loading="loading" :data="tasks" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="task_name" label="任务名称" min-width="140" show-overflow-tooltip />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ TASK_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="140">
              <template #default="{ row }">
                <el-progress
                  :percentage="progressOf(row)"
                  :stroke-width="12"
                  :status="row.status === 'done' ? 'success' : undefined"
                />
              </template>
            </el-table-column>
            <el-table-column label="已发送" width="80">
              <template #default="{ row }">{{ row.sent }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row.id)">详情</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无任务，点击页面右上角「新建群发任务」" />
            </template>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="size"
              :page-sizes="[10, 20, 50]"
              :total="total"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadTasks"
              @size-change="onSizeChange"
            />
          </div>
        </el-card>

    <el-drawer v-model="createVisible" title="创建群发任务" size="560px">
          <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
            <el-form-item label="任务名称" prop="task_name">
              <el-input v-model="form.task_name" placeholder="如 10月促销第一波" />
            </el-form-item>

            <el-form-item label="目标选择">
              <el-radio-group v-model="form.target_type">
                <el-radio-button value="group">资源群</el-radio-button>
                <el-radio-button value="contact">联系人</el-radio-button>
              </el-radio-group>
              <el-input
                v-model="form.target_text"
                type="textarea"
                :rows="3"
                class="section-gap"
                placeholder="目标 ID 列表，逗号或换行分隔"
              />
              <span class="muted">已解析 {{ targetIds.length }} 个目标</span>
            </el-form-item>

            <el-form-item label="发送账号">
              <el-select
                v-model="form.account_ids"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                placeholder="从账号池选择执行账号"
                style="width: 100%"
              >
                <el-option
                  v-for="a in accounts"
                  :key="a.id"
                  :label="`账号 #${a.id}（号码 ${a.number_id}）`"
                  :value="a.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="消息内容" prop="message_content">
              <el-input
                v-model="form.message_content"
                type="textarea"
                :rows="4"
                placeholder="支持变量，例如：Hi {name}，查看 {link}"
              />
              <div class="var-row">
                <el-button size="small" @click="insertVar('{name}')">插入 {name}</el-button>
                <el-button size="small" @click="insertVar('{link}')">插入 {link}</el-button>
              </div>
            </el-form-item>

            <el-form-item label="超链接">
              <el-input v-model="form.link_url" placeholder="https://example.com/xxx" />
            </el-form-item>

            <el-collapse class="section-gap block-gap">
              <el-collapse-item title="高级选项（暂未开放）" name="advanced">
            <el-form-item label="发送策略">
              <el-radio-group v-model="form.strategy" disabled>
                <el-radio-button value="ai">AI 自动</el-radio-button>
                <el-radio-button value="manual">手动</el-radio-button>
              </el-radio-group>
              <el-tag type="info" size="small" effect="plain" class="inline-tag">待接入</el-tag>
            </el-form-item>

            <el-form-item label="定时发送">
              <el-date-picker
                v-model="form.scheduled_at"
                type="datetime"
                placeholder="立即发送"
                style="width: 100%"
                disabled
              />
              <el-tag type="info" size="small" effect="plain" class="inline-tag">待接入</el-tag>
            </el-form-item>

              </el-collapse-item>
            </el-collapse>
            <el-button
              type="primary"
              :loading="submitting"
              :disabled="targetIds.length === 0 || form.account_ids.length === 0"
              @click="submit"
            >
              提交群发任务
            </el-button>
          </el-form>
    </el-drawer>

    <el-drawer v-model="detailVisible" title="任务详情" size="460px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detailRow" :column="1" border>
          <el-descriptions-item label="任务 ID">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="任务名称">{{ detailRow.task_name }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(currentStatus)" size="small">
              {{ TASK_STATUS_LABEL[currentStatus] || currentStatus }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDateTime(detailRow.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-gap">
          <div class="metric">
            <span>已发送</span>
            <el-progress
              :percentage="currentSent ? 100 : 0"
              :show-text="false"
              :stroke-width="14"
            />
            <b>{{ currentSent }}</b>
          </div>
          <div class="metric">
            <span>已送达</span>
            <el-progress
              :percentage="pct(currentDelivered, currentSent)"
              :show-text="false"
              :stroke-width="14"
              color="#303030"
            />
            <b>{{ currentDelivered }}</b>
          </div>
          <div class="metric">
            <span>已阅读</span>
            <el-progress
              :percentage="pct(currentRead, currentSent)"
              :show-text="false"
              :stroke-width="14"
              color="#a16207"
            />
            <b>{{ currentRead }}</b>
          </div>
        </div>

        <el-alert
          class="section-gap"
          :closable="false"
          show-icon
          title="详情打开时每 3 秒更新一次任务进度。"
        />
        <el-alert
          class="section-gap"
          type="info"
          :closable="false"
          show-icon
          title="「已点击」指标需后端补充点击追踪字段后展示。"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { accountApi, massSendApi } from '@/api'
import type { AccountItem, MassSendProgress, MassSendTaskRow } from '@/types/api'
import { TASK_STATUS_LABEL, formatDateTime, parseIdList, statusTagType } from '@/utils/format'

const formRef = ref<FormInstance>()
const submitting = ref(false)
const route = useRoute()
const router = useRouter()
const createVisible = ref(false)
watch(() => route.query.create, (value) => {
  if (value === '1' && route.path === '/mass-send') {
    createVisible.value = true
    const { create, ...query } = route.query
    router.replace({ path: route.path, query })
  }
}, { immediate: true })
const loading = ref(false)
const accounts = ref<AccountItem[]>([])

const tasks = ref<MassSendTaskRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const statusFilter = ref('')

const form = reactive({
  task_name: '',
  target_type: 'group',
  target_text: '',
  account_ids: [] as number[],
  message_content: '',
  link_url: '',
  strategy: 'ai',
  scheduled_at: null as string | null,
})

const rules: FormRules = {
  task_name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  message_content: [{ required: true, message: '请输入消息内容', trigger: 'blur' }],
}

const targetIds = computed(() => parseIdList(form.target_text))

// ---------- 详情抽屉（实时拉取） ----------
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailRow = ref<MassSendTaskRow | null>(null)
const detailProgress = ref<MassSendProgress | null>(null)
let detailTimer: number | null = null
let timer: number | null = null

const currentStatus = computed(() => detailProgress.value?.status || detailRow.value?.status || '')
const currentSent = computed(() => detailProgress.value?.sent ?? detailRow.value?.sent ?? 0)
const currentDelivered = computed(
  () => detailProgress.value?.delivered ?? detailRow.value?.delivered ?? 0,
)
const currentRead = computed(() => detailProgress.value?.read ?? detailRow.value?.read ?? 0)

async function loadDetail() {
  if (!detailVisible.value || !detailRow.value) return
  detailLoading.value = true
  try {
    detailProgress.value = await massSendApi.detail(detailRow.value.id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    detailLoading.value = false
  }
}

function openDetail(id: number) {
  detailRow.value = tasks.value.find((t) => t.id === id) || null
  detailProgress.value = null
  detailVisible.value = true
  loadDetail()
  if (!detailTimer) detailTimer = window.setInterval(loadDetail, 3000)
}

function stopDetailTimer() {
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }
}

watch(detailVisible, (v) => {
  if (!v) stopDetailTimer()
})

function insertVar(v: string) {
  form.message_content = `${form.message_content}${form.message_content ? ' ' : ''}${v}`
}

function progressOf(row: MassSendTaskRow) {
  if (row.status === 'done') return 100
  if (!row.sent) return 0
  return Math.min(100, Math.round((row.delivered / Math.max(row.sent, 1)) * 100))
}

function pct(part: number, total: number) {
  if (!total) return 0
  return Math.min(100, Math.round((part / total) * 100))
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const res = await massSendApi.create({
      task_name: form.task_name,
      target_type: form.target_type,
      target_ids: targetIds.value,
      account_ids: form.account_ids,
      message_content: form.message_content,
      link_url: form.link_url,
    })
    createVisible.value = false
    ElMessage.success(`任务已创建，ID: ${res.task_id}`)
    form.task_name = ''
    form.target_text = ''
    form.message_content = ''
    form.link_url = ''
    page.value = 1
    await loadTasks()
    startPolling()
  } finally {
    submitting.value = false
  }
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await massSendApi.list({
      page: page.value,
      size: size.value,
      status: statusFilter.value || undefined,
    })
    tasks.value = res.list
    total.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadTasks()
}

function onSizeChange() {
  page.value = 1
  loadTasks()
}

function startPolling() {
  if (timer) return
  timer = window.setInterval(() => {
    const active = tasks.value.some((t) => t.status === 'pending' || t.status === 'running')
    if (active) loadTasks()
  }, 2000)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(async () => {
  accounts.value = await accountApi.list().catch(() => [])
  await loadTasks()
  startPolling()
})

onActivated(startPolling)
onDeactivated(() => {
  stopPolling()
  stopDetailTimer()
})
onBeforeUnmount(() => {
  stopPolling()
  stopDetailTimer()
})
</script>

<style scoped>
.var-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.inline-tag {
  margin-left: 10px;
}

.metric {
  display: grid;
  grid-template-columns: 60px 1fr 48px;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 13px;
}
</style>
