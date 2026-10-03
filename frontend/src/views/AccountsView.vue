<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>账号管理</h2>
        <div class="sub">账号列表 · 详情 · 健康度看板</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAccounts">刷新</el-button>
    </div>

    <el-alert
      v-if="apiError"
      type="warning"
      show-icon
      :closable="false"
      title="未能连接 GET /api/v1/accounts，请确认后端已启动。"
    />

    <div class="filter-bar section-gap">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索账号 ID / 号码 ID / IP"
        style="width: 230px"
        :prefix-icon="Search"
        clearable
      />
      <el-select v-model="filters.status" placeholder="账号状态" style="width: 150px" clearable>
        <el-option label="正常" value="normal" />
        <el-option label="观察" value="watch" />
        <el-option label="暂停" value="paused" />
        <el-option label="已封" value="banned" />
      </el-select>
      <el-select v-model="filters.stage" placeholder="养号阶段" style="width: 150px" clearable>
        <el-option
          v-for="(label, key) in NURTURE_STAGE_LABEL"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <el-row :gutter="16" class="section-gap">
      <el-col :xs="24" :md="16">
        <el-card shadow="never">
          <el-table v-loading="loading" :data="pagedAccounts" stripe>
            <el-table-column prop="id" label="账号 ID" width="90" />
            <el-table-column prop="number_id" label="号码 ID" width="90" />
            <el-table-column prop="ip" label="当前 IP" min-width="150" class-name="mono" />
            <el-table-column label="健康分" width="150">
              <template #default="{ row }">
                <el-progress
                  :percentage="row.health_score"
                  :stroke-width="12"
                  :color="healthColor(row.health_score)"
                />
              </template>
            </el-table-column>
            <el-table-column label="养号阶段" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">
                  {{ NURTURE_STAGE_LABEL[row.nurture_stage] || row.nurture_stage }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ ACCOUNT_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row.id)">详情</el-button>
                <el-button
                  link
                  type="warning"
                  :disabled="row.status === 'paused'"
                  @click="pause(row.id)"
                >
                  暂停
                </el-button>
                <el-button
                  link
                  type="success"
                  :disabled="row.status === 'normal'"
                  @click="resume(row.id)"
                >
                  恢复
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无账号数据，请先在「注册管理」中注册号码" />
            </template>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50]"
              :total="filteredAccounts.length"
              layout="total, sizes, prev, pager, next"
              background
            />
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="8">
        <el-card shadow="never">
          <template #header>健康度看板</template>
          <EChart :option="statusChartOption" :height="240" />
        </el-card>
      </el-col>
    </el-row>

    <el-drawer v-model="detailVisible" title="账号详情" size="440px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="current" :column="1" border>
          <el-descriptions-item label="账号 ID">{{ current.id }}</el-descriptions-item>
          <el-descriptions-item label="号码 ID">{{ current.number_id }}</el-descriptions-item>
          <el-descriptions-item label="手机号">{{ current.phone_number || '-' }}</el-descriptions-item>
          <el-descriptions-item label="设备指纹">
            <span class="mono">{{ current.device_fingerprint || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前 IP">
            <span class="mono">{{ current.current_ip || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="健康分">{{ current.health_score }}</el-descriptions-item>
          <el-descriptions-item label="养号阶段">
            {{ NURTURE_STAGE_LABEL[current.nurture_stage] || current.nurture_stage }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(current.status)" size="small">
              {{ ACCOUNT_STATUS_LABEL[current.status] || current.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(current.created_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { accountApi } from '@/api'
import type { AccountDetail, AccountItem } from '@/types/api'
import {
  ACCOUNT_STATUS_LABEL,
  NURTURE_STAGE_LABEL,
  formatDateTime,
  statusTagType,
} from '@/utils/format'
import EChart from '@/components/EChart.vue'

const loading = ref(false)
const apiError = ref(false)
const accounts = ref<AccountItem[]>([])

const filters = reactive({ keyword: '', status: '', stage: '' })
const page = ref(1)
const pageSize = ref(10)

const detailVisible = ref(false)
const detailLoading = ref(false)
const current = ref<AccountDetail | null>(null)

const filteredAccounts = computed(() =>
  accounts.value.filter((a) => {
    if (filters.status && a.status !== filters.status) return false
    if (filters.stage && a.nurture_stage !== filters.stage) return false
    if (filters.keyword) {
      const kw = filters.keyword.toLowerCase()
      if (!`${a.id} ${a.number_id} ${a.ip}`.toLowerCase().includes(kw)) return false
    }
    return true
  }),
)

const pagedAccounts = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredAccounts.value.slice(start, start + pageSize.value)
})

const statusChartOption = computed<EChartsOption>(() => {
  const statuses = ['normal', 'watch', 'paused', 'banned']
  const counts = statuses.map((s) => accounts.value.filter((a) => a.status === s).length)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: statuses.map((s) => ACCOUNT_STATUS_LABEL[s] || s) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        type: 'bar',
        barWidth: '45%',
        data: counts,
        itemStyle: { color: '#409eff', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top' },
      },
    ],
  }
})

watch([() => filters.keyword, () => filters.status, () => filters.stage], () => {
  page.value = 1
})

function healthColor(score: number) {
  if (score >= 90) return '#25d366'
  if (score >= 80) return '#409eff'
  if (score >= 60) return '#e6a23c'
  return '#f56c6c'
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.stage = ''
}

async function openDetail(id: number) {
  detailVisible.value = true
  detailLoading.value = true
  try {
    current.value = await accountApi.detail(id)
  } catch {
    current.value = null
  } finally {
    detailLoading.value = false
  }
}

async function pause(id: number) {
  await accountApi.pause(id)
  ElMessage.success('账号已暂停')
  await loadAccounts()
}

async function resume(id: number) {
  await accountApi.resume(id)
  ElMessage.success('账号已恢复')
  await loadAccounts()
}

async function loadAccounts() {
  loading.value = true
  apiError.value = false
  try {
    accounts.value = await accountApi.list()
  } catch {
    apiError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(loadAccounts)
</script>


