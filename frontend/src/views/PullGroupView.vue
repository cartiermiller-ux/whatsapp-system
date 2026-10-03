<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>拉群任务</h2>
        <div class="sub">拉人来源 · 执行账号 · 任务列表</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
    </div>

    <el-row :gutter="16" class="card-row">
      <el-col :xs="24" :md="10">
        <el-card shadow="never">
          <template #header>创建拉群任务</template>
          <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
            <el-form-item label="任务名称" prop="task_name">
              <el-input v-model="form.task_name" placeholder="如 10月拉群第一批" />
            </el-form-item>
            <el-form-item label="目标群" prop="target_group_id">
              <el-select
                v-model="form.target_group_id"
                filterable
                placeholder="选择目标资源群"
                style="width: 100%"
              >
                <el-option
                  v-for="g in groups"
                  :key="g.id"
                  :label="`#${g.id} ${g.group_name}`"
                  :value="g.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="拉人来源">
              <el-radio-group v-model="form.source_type">
                <el-radio-button value="number_pool">号码池</el-radio-button>
                <el-radio-button value="contact">联系人</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="来源 ID 列表">
              <el-input
                v-model="form.source_text"
                type="textarea"
                :rows="3"
                placeholder="拉人来源的 ID，逗号或换行分隔"
              />
              <span class="muted">已解析 {{ sourceIds.length }} 个</span>
            </el-form-item>
            <el-form-item label="执行账号">
              <el-select
                v-model="form.account_ids"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                placeholder="从账号池选择"
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
            <el-form-item label="计费国家">
              <el-input v-model="form.billing_country" placeholder="如 CN / US（可选）" />
            </el-form-item>
            <el-button
              type="primary"
              :loading="submitting"
              :disabled="!form.task_name || !form.target_group_id"
              @click="submit"
            >
              提交拉群任务
            </el-button>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>任务列表（GET /api/v1/invite/tasks）</span>
              <span class="muted">{{ total }} 条</span>
            </div>
          </template>
          <el-table v-loading="loading" :data="tasks" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="task_name" label="任务名称" min-width="150" show-overflow-tooltip />
            <el-table-column prop="target_group_id" label="目标群 ID" width="110" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ TASK_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无拉群任务，点上方「创建拉群任务」发起" />
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
      </el-col>
    </el-row>

    <el-drawer v-model="detailVisible" title="拉群任务详情" size="420px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item label="任务 ID">{{ detail.task_id }}</el-descriptions-item>
          <el-descriptions-item label="任务名称">{{ detail.task_name }}</el-descriptions-item>
          <el-descriptions-item label="目标群 ID">{{ detail.target_group_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detail.status)" size="small">
              {{ TASK_STATUS_LABEL[detail.status] || detail.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDateTime(detail.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-alert
          class="section-gap"
          type="info"
          :closable="false"
          show-icon
          title="进度、成功拉入人数、失败原因需后端补充字段。当前对接 GET /api/v1/invite/tasks/{id}，抽屉打开时每 3 秒刷新。"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { accountApi, groupApi, inviteApi } from '@/api'
import type { AccountItem, GroupRow, InviteTaskDetail, InviteTaskRow } from '@/types/api'
import { TASK_STATUS_LABEL, formatDateTime, parseIdList, statusTagType } from '@/utils/format'

const formRef = ref<FormInstance>()
const submitting = ref(false)
const loading = ref(false)

const groups = ref<GroupRow[]>([])
const accounts = ref<AccountItem[]>([])
const tasks = ref<InviteTaskRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

// ---------- 详情抽屉（实时拉取） ----------
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<InviteTaskDetail | null>(null)
let detailTimer: number | null = null

async function loadDetail() {
  if (!detailVisible.value || !detail.value) return
  detailLoading.value = true
  try {
    detail.value = await inviteApi.detail(detail.value.task_id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    detailLoading.value = false
  }
}

function openDetail(row: InviteTaskRow) {
  detail.value = {
    task_id: row.id,
    task_name: row.task_name,
    target_group_id: row.target_group_id,
    status: row.status,
    created_at: row.created_at,
  }
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

onDeactivated(stopDetailTimer)
onBeforeUnmount(stopDetailTimer)

const form = reactive({
  task_name: '',
  target_group_id: undefined as number | undefined,
  source_type: 'number_pool',
  source_text: '',
  account_ids: [] as number[],
  billing_country: '',
})

const rules: FormRules = {
  task_name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  target_group_id: [{ required: true, message: '请选择目标群', trigger: 'change' }],
}

const sourceIds = computed(() => parseIdList(form.source_text))

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid || form.target_group_id === undefined) return

  submitting.value = true
  try {
    const res = await inviteApi.create({
      task_name: form.task_name,
      target_group_id: form.target_group_id,
      source_type: form.source_type,
      source_ids: sourceIds.value,
      account_ids: form.account_ids,
      billing_country: form.billing_country,
    })
    ElMessage.success(`拉群任务已创建，ID: ${res.task_id}`)
    form.task_name = ''
    form.source_text = ''
    loadTasks()
  } finally {
    submitting.value = false
  }
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await inviteApi.list({ page: page.value, size: size.value })
    tasks.value = res.list
    total.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function onSizeChange() {
  page.value = 1
  loadTasks()
}

onMounted(async () => {
  const [g, a] = await Promise.all([
    groupApi.list({ page: 1, size: 100 }).catch(() => ({ list: [] as GroupRow[] })),
    accountApi.list().catch(() => [] as AccountItem[]),
  ])
  groups.value = g.list
  accounts.value = a
  loadTasks()
})
</script>


