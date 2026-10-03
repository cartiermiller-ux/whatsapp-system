<template>
  <div class="page dashboard-page">
    <div class="page-header">
      <div>
        <h2>数据看板</h2>
        <div class="sub">WhatsApp 群发运营 · 今日概览 · 快捷操作 · 通道状态 · 任务进度</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 错误态：给出原因和重试入口，而不是一片空白 -->
    <el-alert
      v-if="loadError"
      class="section-gap"
      type="error"
      show-icon
      :closable="false"
      title="看板数据加载失败"
      :description="loadError"
    >
      <template #default>
        <div class="error-body">
          <span>{{ loadError }}</span>
          <el-button size="small" type="primary" @click="load">重试</el-button>
        </div>
      </template>
    </el-alert>

    <div class="dashboard-grid">
    <!-- ① 今日概览（核心 KPI，一级信息） -->
    <el-card shadow="never" class="overview-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>今日概览</span>
          <span class="muted">更新于 {{ updatedAt }}</span>
        </div>
      </template>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">今日发送</div>
          <div class="kpi-value">{{ today.sent }}</div>
          <div v-if="sendTrend" class="kpi-trend" :class="sendTrend.tone">{{ sendTrend.text }}</div>
          <div class="kpi-hint">{{ today.tasks }} 个任务</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">成功率</div>
          <div class="kpi-value" :class="successTone">{{ today.success_rate }}%</div>
          <div v-if="rateTrend" class="kpi-trend" :class="rateTrend.tone">{{ rateTrend.text }}</div>
          <div class="kpi-hint">送达 {{ today.delivered }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">失败数</div>
          <div class="kpi-value" :class="today.failed > 0 ? 'tone-danger' : ''">
            {{ today.failed }}
          </div>
          <div class="kpi-hint">{{ today.failed > 0 ? '需要关注' : '暂无失败' }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">账户余额</div>
          <div class="kpi-value" :class="balanceTone">{{ balance.balance }}</div>
          <div class="kpi-hint">
            {{ balance.currency }}
            <template v-if="balance.pending_orders"> · {{ balance.pending_orders }} 笔待支付</template>
          </div>
        </div>
      </div>
      <div class="kpi-foot muted">
        累计发送 {{ total.sent }} 条 · 送达率 {{ total.success_rate }}% · 阅读率 {{ total.read_rate }}%
      </div>
    </el-card>

    <!-- ② 快捷操作（主 CTA 固定在第二位，颜色唯一） -->
    <el-card shadow="never" class="quick-card">
      <template #header>快捷操作</template>
      <div class="quick-actions">
        <el-button type="primary" :icon="Promotion" @click="go('/mass-send')">新建群发</el-button>
        <el-button :icon="Upload" @click="go('/numbers')">导入号码</el-button>
        <el-button :icon="Document" @click="go('/ads')">广告文案</el-button>
        <el-button :icon="Wallet" @click="go('/billing')">余额充值</el-button>
      </div>
    </el-card>

    <!-- ③ 通道状态 -->
    <el-card shadow="never" class="channels-card">
      <template #header>
        <div class="card-header">
          <span>通道状态</span>
          <el-button link type="primary" @click="go('/integrations')">配置</el-button>
        </div>
      </template>
      <div class="channel-grid">
        <div v-for="item in providers" :key="item.kind" class="channel">
          <span class="dot" :class="item.configured ? 'dot-ok' : 'dot-warn'"></span>
          <div class="channel-copy">
            <span class="channel-name">{{ PROVIDER_KIND_LABEL[item.kind] || item.kind }}</span>
            <span class="channel-meta muted">{{ item.mock ? '模拟' : item.name }}</span>
          </div>
        </div>
        <div v-if="!providers.length" class="channel muted">未获取到通道状态</div>
      </div>
    </el-card>

    <!-- ④ 任务列表 -->
    <el-card shadow="never" class="tasks-card">
      <template #header>
        <div class="card-header">
          <span>{{ activeTasks.length ? '进行中任务' : '最近任务' }}</span>
          <el-button link type="primary" @click="go('/mass-send')">全部任务</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="taskRows" stripe>
        <el-table-column prop="task_name" label="任务" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ TASK_STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="Math.min(100, Math.round(row.progress))"
                :stroke-width="6"
                :show-text="false"
                :status="row.status === 'failed' ? 'exception' : undefined"
              />
              <span class="muted">{{ row.sent }}/{{ row.targets }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="delivered" label="送达" width="80" />
        <el-table-column label="失败" width="80">
          <template #default="{ row }">
            <span :class="row.failed > 0 ? 'tone-danger' : 'muted'">{{ row.failed }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有群发任务，点上方「新建群发」发起第一波" />
        </template>
      </el-table>
    </el-card>

    <!-- ⑤ 账号健康度：低频信息，折叠收起，不占首屏 -->
    <el-collapse class="collapse-block">
      <el-collapse-item name="health">
        <template #title>
          <div class="health-heading">
          <span class="collapse-title">账号健康度</span>
          <span class="muted collapse-meta">
            共 {{ accounts.total }} 个 · 正常 {{ accounts.normal }} · 观察 {{ accounts.watch }} ·
            暂停 {{ accounts.paused }} · 已封 {{ accounts.banned }}
          </span>
          </div>
        </template>
        <EChart :option="healthChartOption" :height="240" />
      </el-collapse-item>
    </el-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Document, Promotion, Refresh, Upload, Wallet } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { dashboardApi } from '@/api'
import type { DashboardMetrics, DashboardOverview, DashboardTaskBrief } from '@/types/api'
import { PROVIDER_KIND_LABEL, TASK_STATUS_LABEL, formatDateTime, statusTagType } from '@/utils/format'
import EChart from '@/components/EChart.vue'

const router = useRouter()
const loading = ref(false)
const loadError = ref('')

const EMPTY_METRICS: DashboardMetrics = {
  tasks: 0,
  sent: 0,
  delivered: 0,
  read: 0,
  failed: 0,
  success_rate: 0,
  read_rate: 0,
}

const today = ref<DashboardMetrics>({ ...EMPTY_METRICS })
const yesterday = ref<DashboardMetrics>({ ...EMPTY_METRICS })
const total = ref<DashboardMetrics>({ ...EMPTY_METRICS })
const balance = ref<DashboardOverview['balance']>({ balance: 0, currency: 'USDT', pending_orders: 0 })
const accounts = ref<DashboardOverview['accounts']>({
  total: 0,
  normal: 0,
  watch: 0,
  paused: 0,
  banned: 0,
})
const activeTasks = ref<DashboardTaskBrief[]>([])
const recentTasks = ref<DashboardTaskBrief[]>([])
const providers = ref<DashboardOverview['providers']>([])
const updatedAt = ref('-')

/** 有进行中的就显示进行中，否则显示最近任务 */
const taskRows = computed(() =>
  activeTasks.value.length ? activeTasks.value : recentTasks.value,
)

/* 颜色只表达含义，不做装饰：灰=正常、橙=需留意、红=需处理，其余用中性色 */
const successTone = computed(() => {
  if (!today.value.sent) return ''
  if (today.value.success_rate >= 95) return 'tone-success'
  if (today.value.success_rate >= 80) return 'tone-warning'
  return 'tone-danger'
})

/* 二级信息（趋势/对比）：昨天没有数据时不展示，避免出现无意义的数字 */
function buildTrend(current: number, previous: number) {
  if (!previous) return null
  const diff = current - previous
  if (diff === 0) return { tone: 'kpi-trend-flat', text: '与昨日持平（' + previous + ' 条）' }
  const pct = Math.round((diff / previous) * 1000) / 10
  const sign = diff > 0 ? '+' : ''
  return {
    tone: diff > 0 ? 'tone-success' : 'tone-warning',
    text: '较昨日 ' + sign + pct + '%（' + previous + ' 条）',
  }
}

const sendTrend = computed(() => buildTrend(today.value.sent, yesterday.value.sent))

const rateTrend = computed(() => {
  if (!yesterday.value.sent || !today.value.sent) return null
  const diff = today.value.success_rate - yesterday.value.success_rate
  if (Math.abs(diff) < 0.1) return { tone: 'kpi-trend-flat', text: '与昨日持平' }
  return {
    tone: diff > 0 ? 'tone-success' : 'tone-warning',
    text: '较昨日 ' + (diff > 0 ? '+' : '') + diff.toFixed(1) + ' 个百分点',
  }
})

const balanceTone = computed(() =>
  balance.value.balance > 0 && balance.value.balance < 10 ? 'tone-warning' : '',
)

const healthChartOption = computed<EChartsOption>(() => {
  const a = accounts.value
  const entries: Array<[string, number]> = [
    ['正常', a.normal],
    ['观察', a.watch],
    ['暂停', a.paused],
    ['已封', a.banned],
  ]
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
        itemStyle: { color: '#303030', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top' },
      },
    ],
  }
})

function go(path: string) {
  router.push(path)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await dashboardApi.overview()
    today.value = data.today
    yesterday.value = data.yesterday
    total.value = data.total
    balance.value = data.balance
    accounts.value = data.accounts
    activeTasks.value = data.active_tasks
    recentTasks.value = data.recent_tasks
    providers.value = data.providers
    updatedAt.value = formatDateTime(data.generated_at)
  } catch (error) {
    // 拦截器已经提示过一次，这里保留页面内的重试入口
    loadError.value =
      (error as { message?: string })?.message || '无法连接后端服务，请确认服务已启动'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.dashboard-page { container: dashboard / inline-size; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.dashboard-grid > * { min-width: 0; margin: 0; }
.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.kpi { min-width: 0; display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid var(--wa-border); border-radius: 8px; background: var(--wa-sidebar-bg); overflow-wrap: anywhere; }
.kpi-label { font-size: var(--wa-font-sm); color: var(--wa-text-muted); }
.kpi-value { font-size: 24px; font-weight: 600; line-height: 1.2; color: var(--wa-text); font-variant-numeric: tabular-nums; }
.kpi-trend { font-size: 12px; line-height: 1.5; }
.kpi-trend-flat, .kpi-hint { color: var(--wa-text-muted); }
.kpi-hint { margin-top: auto; font-size: 12px; }
.kpi-foot { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--wa-border); font-size: 12px; overflow-wrap: anywhere; }
.tone-success { color: var(--wa-brand); }
.tone-warning { color: var(--wa-warning); }
.tone-danger { color: var(--wa-danger); }
.quick-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.quick-actions :deep(.el-button) { width: 100%; min-width: 0; margin: 0; height: 36px; padding: 8px; }
.channel-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.channel { min-width: 0; display: flex; align-items: flex-start; gap: 8px; font-size: 13px; }
.channel-copy { min-width: 0; display: flex; flex-direction: column; gap: 2px; overflow-wrap: anywhere; }
.dot { width: 6px; height: 6px; margin-top: 6px; border-radius: 50%; flex: none; }
.dot-ok { background: var(--wa-brand); }
.dot-warn { background: var(--wa-warning); }
.channel-name { color: var(--wa-text); }
.channel-meta { font-size: 12px; }
.progress-cell { display: flex; align-items: center; gap: 8px; }
.progress-cell :deep(.el-progress) { flex: 1; min-width: 0; }
.progress-cell > span { flex-shrink: 0; }
.collapse-block { border: 1px solid var(--wa-border); border-radius: var(--wa-radius); background: var(--wa-surface); padding: 0 16px; }
.collapse-block :deep(.el-collapse-item__header) { height: auto; min-height: 44px; line-height: 1.5; padding: 10px 0; }
.health-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; min-width: 0; padding-right: 8px; }
.collapse-title { font-weight: 600; color: var(--wa-text); }
.collapse-meta { font-size: 12px; overflow-wrap: anywhere; }
.error-body { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
@container dashboard (min-width: 640px) { .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@container dashboard (min-width: 850px) {
  .dashboard-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .overview-card, .tasks-card, .collapse-block { grid-column: 1 / -1; }
}
@container dashboard (max-width: 260px) {
  .kpi-grid, .quick-actions { grid-template-columns: minmax(0, 1fr); }
}
@container dashboard (max-width: 420px) { .channel-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
