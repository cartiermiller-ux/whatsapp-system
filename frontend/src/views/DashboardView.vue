<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>数据看板</h2>
        <div class="sub">今日消息概览 · 账号健康度 · 余额</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <el-alert
      v-if="apiError"
      type="warning"
      show-icon
      :closable="false"
      title="未能连接后端接口，请确认 FastAPI 已在 127.0.0.1:8000 启动。"
      description="看板数据来自 GET /api/v1/dashboard/today 与 GET /api/v1/accounts。"
    />

    <div class="filter-bar section-gap">
      <el-select v-model="filters.country" placeholder="国家 / 区号" style="width: 180px" clearable>
        <el-option label="中国 +86" value="CN" />
        <el-option label="美国 +1" value="US" />
        <el-option label="印度 +91" value="IN" />
        <el-option label="印尼 +62" value="ID" />
      </el-select>
      <el-date-picker
        v-model="filters.range"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
      />
      <el-tag type="info" effect="plain">筛选参数后端暂未支持，接入后生效</el-tag>
    </div>

    <!-- 今日消息看板 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">今日已发送</div>
        <div class="value" style="color: #409eff">{{ today.sent }}</div>
        <div class="hint">GET /api/v1/dashboard/today</div>
      </div>
      <div class="stat-card">
        <div class="label">今日已送达</div>
        <div class="value" style="color: #25d366">{{ today.delivered }}</div>
        <div class="hint">送达率 {{ percent(today.delivered, today.sent) }}</div>
      </div>
      <div class="stat-card">
        <div class="label">今日已阅读</div>
        <div class="value" style="color: #e6a23c">{{ today.read }}</div>
        <div class="hint">阅读率 {{ percent(today.read, today.sent) }}</div>
      </div>
      <div class="stat-card">
        <div class="label">账号总数</div>
        <div class="value">{{ accounts.length }}</div>
        <div class="hint">GET /api/v1/accounts</div>
      </div>
    </div>

    <!-- 账号健康度概览 -->
    <div class="section-gap">
      <h3 class="block-title">账号健康度概览</h3>
      <div class="stat-grid">
        <div class="stat-card">
          <div class="label">正常</div>
          <div class="value" style="color:#25d366">{{ healthCount('normal') }}</div>
        </div>
        <div class="stat-card">
          <div class="label">观察</div>
          <div class="value" style="color:#e6a23c">{{ healthCount('watch') }}</div>
        </div>
        <div class="stat-card">
          <div class="label">暂停</div>
          <div class="value" style="color:#909399">{{ healthCount('paused') }}</div>
        </div>
        <div class="stat-card">
          <div class="label">已封</div>
          <div class="value" style="color:#f56c6c">{{ healthCount('banned') }}</div>
        </div>
      </div>
    </div>

    <el-row :gutter="16" class="section-gap">
      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <template #header>账号健康分分布（真实数据）</template>
          <EChart :option="healthChartOption" :height="280" />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="10">
        <el-card shadow="never">
          <template #header>余额概览</template>
          <div class="balance-value">
            {{ balance.balance }}
            <span class="balance-unit">{{ balance.currency }}</span>
          </div>
          <div class="hint muted">GET /api/v1/balance</div>
          <el-button class="section-gap" size="small" @click="goBilling">
            查看充值 / 消费流水
          </el-button>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { dashboardApi, accountApi, billingApi } from '@/api'
import type { AccountItem, BalanceInfo, DashboardToday } from '@/types/api'
import { percent } from '@/utils/format'
import EChart from '@/components/EChart.vue'

const router = useRouter()
const loading = ref(false)
const apiError = ref(false)
const today = ref<DashboardToday>({ sent: 0, delivered: 0, read: 0 })
const accounts = ref<AccountItem[]>([])
const balance = ref<BalanceInfo>({
  balance: 0,
  currency: 'USDT',
  total_recharge: 0,
  total_consume: 0,
  pending_orders: 0,
  updated_at: null,
})

const filters = reactive<{ country: string; range: [string, string] | null }>({
  country: '',
  range: null,
})

function healthCount(status: string) {
  return accounts.value.filter((a) => a.status === status).length
}

const healthChartOption = computed<EChartsOption>(() => {
  const buckets = { '优 (≥90)': 0, '良 (80-89)': 0, '一般 (60-79)': 0, '差 (<60)': 0 }
  for (const a of accounts.value) {
    if (a.health_score >= 90) buckets['优 (≥90)'] += 1
    else if (a.health_score >= 80) buckets['良 (80-89)'] += 1
    else if (a.health_score >= 60) buckets['一般 (60-79)'] += 1
    else buckets['差 (<60)'] += 1
  }
  const entries = Object.entries(buckets)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: entries.map((e) => e[0]) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        type: 'bar',
        barWidth: '45%',
        data: entries.map((e) => e[1]),
        itemStyle: { color: '#25d366', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top' },
      },
    ],
  }
})

async function loadAll() {
  loading.value = true
  apiError.value = false
  try {
    const [t, a, b] = await Promise.all([
      dashboardApi.today(),
      accountApi.list(),
      billingApi.balance(),
    ])
    today.value = t
    accounts.value = a
    balance.value = b
  } catch {
    apiError.value = true
  } finally {
    loading.value = false
  }
}

function goBilling() {
  router.push('/billing')
}

onMounted(loadAll)
</script>

<style scoped>
.block-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 12px;
}

.balance-value {
  font-size: 30px;
  font-weight: 700;
  color: #25d366;
  line-height: 1.2;
}

.balance-unit {
  font-size: 14px;
  font-weight: 400;
  color: #909399;
  margin-left: 6px;
}
</style>
