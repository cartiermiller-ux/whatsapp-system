<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>注册管理</h2>
        <div class="sub">批量注册 · 实时进度 · 成功率统计</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadStatus">刷新状态</el-button>
    </div>

    <el-row :gutter="16">
      <!-- 批量注册 -->
      <el-col :xs="24" :md="9">
        <el-card shadow="never">
          <template #header>批量注册</template>
          <el-form label-position="top">
            <el-form-item label="号码 ID 列表">
              <el-input
                v-model="registerText"
                type="textarea"
                :rows="5"
                placeholder="输入号码池中的号码 ID，逗号或换行分隔，例如：1,2,3"
              />
            </el-form-item>
            <el-form-item>
              <el-button size="small" @click="pickPending">选择全部待注册号码</el-button>
              <span class="muted"> 已选 {{ registerIds.length }} 个</span>
            </el-form-item>
            <el-button
              type="primary"
              :loading="submitting"
              :disabled="registerIds.length === 0"
              @click="submitRegister"
            >
              提交注册任务
            </el-button>
          </el-form>
          <el-alert
            class="section-gap"
            type="info"
            :closable="false"
            show-icon
            title="对接 POST /api/v1/register/batch，后端为后台异步任务（模拟约 2 秒/个）。"
          />
        </el-card>
      </el-col>

      <!-- 注册状态 -->
      <el-col :xs="24" :md="15">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>注册状态（GET /api/v1/register/status）</span>
              <div class="auto-refresh">
                <span class="muted">实时刷新</span>
                <el-switch v-model="autoRefresh" @change="onAutoRefreshChange" />
              </div>
            </div>
          </template>

          <div class="stat-grid">
            <div class="stat-card">
              <div class="label">总数</div>
              <div class="value">{{ status.total }}</div>
            </div>
            <div class="stat-card">
              <div class="label">注册成功</div>
              <div class="value" style="color:#25d366">{{ status.success }}</div>
            </div>
            <div class="stat-card">
              <div class="label">注册失败</div>
              <div class="value" style="color:#f56c6c">{{ status.failed }}</div>
            </div>
            <div class="stat-card">
              <div class="label">待注册</div>
              <div class="value" style="color:#e6a23c">{{ status.pending }}</div>
            </div>
          </div>

          <div class="rate section-gap">
            <span>注册成功率</span>
            <el-progress
              :percentage="successRate"
              :stroke-width="14"
              :color="successRate >= 70 ? '#25d366' : '#e6a23c'"
              style="flex: 1"
            />
            <b>{{ successRate }}%</b>
          </div>

          <el-table :data="status.details" size="small" max-height="320" class="section-gap">
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="phone" label="号码" min-width="140" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ NUMBER_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="section-gap">
      <template #header>
        <div class="card-header">
          <span>失败归因（GET /api/v1/register/analysis）</span>
          <span class="muted">共 {{ analysis.total }} 个失败号码</span>
        </div>
      </template>
      <el-table :data="analysis.details" size="small" max-height="320">
        <el-table-column prop="id" label="号码 ID" width="90" />
        <el-table-column prop="phone" label="号码" min-width="150" />
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            {{ NUMBER_SOURCE_LABEL[row.source_type] || row.source_type }}
          </template>
        </el-table-column>
        <el-table-column prop="source_channel" label="来源渠道" min-width="120" />
        <template #empty>
          <el-empty description="暂无注册失败号码" />
        </template>
      </el-table>
      <el-alert
        class="section-gap"
        type="info"
        :closable="false"
        show-icon
        title="后端目前只返回失败号码清单，尚未返回具体失败原因（number / environment / sms）。"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { registerApi } from '@/api'
import type { RegisterAnalysis, RegisterStatusResult } from '@/types/api'
import {
  NUMBER_SOURCE_LABEL,
  NUMBER_STATUS_LABEL,
  parseIdList,
  statusTagType,
} from '@/utils/format'

const loading = ref(false)
const submitting = ref(false)
const autoRefresh = ref(false)
const registerText = ref('')
let timer: number | null = null

const status = ref<RegisterStatusResult>({
  total: 0,
  success: 0,
  failed: 0,
  pending: 0,
  details: [],
})

const analysis = ref<RegisterAnalysis>({ total: 0, details: [] })

const registerIds = computed(() => parseIdList(registerText.value))
const successRate = computed(() => {
  const done = status.value.success + status.value.failed
  if (!done) return 0
  return Math.round((status.value.success / done) * 100)
})

function pickPending() {
  const pendingIds = status.value.details.filter((d) => d.status === 'pending').map((d) => d.id)
  if (!pendingIds.length) {
    ElMessage.info('没有待注册的号码')
    return
  }
  registerText.value = pendingIds.join(',')
}

async function loadStatus() {
  loading.value = true
  try {
    const [s, a] = await Promise.all([registerApi.status(), registerApi.analysis()])
    status.value = s
    analysis.value = a
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  submitting.value = true
  try {
    const res = await registerApi.batch(registerIds.value)
    ElMessage.success(res.message || `已提交 ${res.count} 个注册任务`)
    registerText.value = ''
    // 稍等后刷新，让「注册中」状态可见
    setTimeout(loadStatus, 500)
  } finally {
    submitting.value = false
  }
}

function onAutoRefreshChange(val: boolean) {
  if (val) {
    timer = window.setInterval(loadStatus, 2000)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

// keep-alive 场景下，离开页面暂停轮询，回来时若仍开启则恢复
onActivated(() => {
  loadStatus()
  if (autoRefresh.value && !timer) {
    timer = window.setInterval(loadStatus, 2000)
  }
})

onDeactivated(stopTimer)

onMounted(loadStatus)

onBeforeUnmount(stopTimer)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.auto-refresh {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.rate {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
