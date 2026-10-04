<template>
  <PageTemplate kind="dashboard" class="dashboard-page">
    <div class="page-header">
      <div><h2>数据看板</h2><div class="sub">今日运营情况与任务运行状态</div></div>
      <div class="actions"><span class="muted updated">更新于 {{ updatedAt }}</span><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button></div>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="看板数据加载失败" :description="loadError" />
    <template v-if="data">
      <el-alert v-if="data.today.mock_tasks || data.today.legacy_tasks" type="info" :closable="false" :title="`今日数据包含 ${data.today.mock_tasks || 0} 个模拟任务、${data.today.legacy_tasks || 0} 个历史任务，请结合任务模式核对。`" />
      <section class="dashboard-section" aria-label="今日概览">
        <div class="metrics">
          <div><strong>{{ data.today.sent }}</strong><span>今日发送</span><small>{{ sendTrend }}</small></div>
          <div><strong>{{ data.today.success_rate }}%</strong><span>送达率</span><small>送达 {{ data.today.delivered }} 条</small></div>
          <div><strong>{{ data.today.read_rate }}%</strong><span>阅读率</span><small>已阅读 {{ data.today.read }} 条</small></div>
          <div><strong :class="{ danger: data.today.failed > 0 }">{{ data.today.failed }}</strong><span>失败数</span><small>{{ data.today.failed ? '需要关注发送结果' : '暂无失败' }}</small></div>
        </div>
      </section>
      <section class="dashboard-section">
        <h3>任务运行</h3>
        <div class="task-summary"><span v-for="item in taskStates" :key="item.key">{{ item.label }} <b :class="{ danger: item.key === 'failed' && data.task_counts[item.key] > 0 }">{{ data.task_counts[item.key] }}</b></span></div>
        <h4>最近任务</h4>
        <el-table :data="data.recent_tasks">
          <el-table-column prop="task_name" label="任务名称" min-width="160"><template #default="{ row }"><el-button link @click="go(row.kind === 'pull-group' ? '/pull-group' : '/mass-send')">{{ row.task_name }}</el-button></template></el-table-column>
          <el-table-column label="类型" width="90"><template #default="{ row }">{{ row.kind === 'pull-group' ? '拉群' : '群发' }}</template></el-table-column>
          <el-table-column label="进度" min-width="110"><template #default="{ row }">{{ row.sent === null ? '—' : `${row.sent} / ${row.targets}` }}</template></el-table-column>
          <el-table-column label="送达" width="90"><template #default="{ row }">{{ row.delivered ?? '—' }}</template></el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ TASK_STATUS_LABEL[row.status] || row.status }}</el-tag></template></el-table-column>
          <template #empty><el-empty description="暂无任务，可前往群发任务或拉群任务创建" /></template>
        </el-table>
        <div class="task-links"><el-button link @click="go('/mass-send')">查看全部群发任务 →</el-button><el-button link @click="go('/pull-group')">查看全部拉群任务 →</el-button></div>
      </section>
      <section class="dashboard-section">
        <h3>运营资源</h3>
        <div class="metrics resources">
          <router-link to="/accounts"><span>WhatsApp 账号</span><strong>{{ data.accounts.normal }} / {{ data.accounts.total }}</strong><small>正常 / 总数</small></router-link>
          <router-link to="/numbers"><span>可用号码</span><strong>{{ data.resources.available_numbers.toLocaleString() }}</strong><small>待接入号码</small></router-link>
          <router-link to="/groups"><span>资源群</span><strong>{{ data.resources.groups }}</strong><small>有效资源群</small></router-link>
          <router-link to="/billing"><span>余额</span><strong>{{ data.balance.balance }} <small>{{ data.balance.currency }}</small></strong><small v-if="data.balance.pending_orders">{{ data.balance.pending_orders }} 笔待支付订单</small></router-link>
        </div>
      </section>
      <section class="dashboard-section">
        <h3>异常与提醒</h3>
        <ul v-if="alerts.length" class="alerts"><li v-for="alert in alerts" :key="alert">{{ alert }}</li></ul><p v-else class="muted">暂无异常</p>
        <div class="system-status"><span>系统状态</span><span :class="{ danger: unavailableProviders.length }">● {{ unavailableProviders.length ? '需关注' : data.providers.length ? '未检查' : '未获取' }}</span><el-button link @click="go('/settings?tab=services')">服务与通道 →</el-button></div>
        <ul v-if="unavailableProviders.length" class="alerts"><li v-for="provider in data.providers" :key="provider.kind">{{ PROVIDER_KIND_LABEL[provider.kind] || provider.kind }}：{{ provider.configured ? '已配置' : '未配置' }}{{ provider.mock ? '（模拟服务）' : '' }}</li></ul>
      </section>
    </template>
    <el-skeleton v-else-if="loading" :rows="10" animated />
  </PageTemplate>
</template>
<script setup lang="ts">
import PageTemplate from '@/components/PageTemplate.vue'
import { computed, onActivated, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { dashboardApi } from '@/api'
import type { DashboardOverview } from '@/types/api'
import { TASK_STATUS_LABEL, PROVIDER_KIND_LABEL, statusTagType, formatDateTime } from '@/utils/format'
const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const data = ref<DashboardOverview | null>(null)
const taskStates = [{ key: 'running', label: '正在运行' }, { key: 'pending', label: '等待' }, { key: 'done', label: '已完成' }, { key: 'failed', label: '异常' }] as const
const updatedAt = computed(() => data.value ? formatDateTime(data.value.generated_at) : '—')
const sendTrend = computed(() => {
  if (!data.value?.yesterday.sent) return `${data.value?.today.tasks || 0} 个今日任务`
  const diff = (data.value.today.sent - data.value.yesterday.sent) / data.value.yesterday.sent * 100
  return `较昨日 ${diff > 0 ? '+' : ''}${diff.toFixed(1)}%`
})
// 配置状态不是实时健康探测结果，模拟服务也需要提醒。
const unavailableProviders = computed(() => data.value?.providers.filter(item => !item.configured || item.mock) || [])
const alerts = computed(() => {
  if (!data.value) return []
  const d = data.value, items: string[] = []
  if (d.today.failed) items.push(`今日 ${d.today.failed} 个目标失败或结果待核对，请检查执行明细。`)
  if (d.task_counts.failed) items.push(`${d.task_counts.failed} 个任务异常，请前往任务列表处理。`)
  if (d.accounts.banned || d.accounts.paused) items.push(`账号已封 ${d.accounts.banned} 个、暂停 ${d.accounts.paused} 个，请检查 WhatsApp 账号。`)
  if (unavailableProviders.value.length) items.push('部分服务未配置或正在使用模拟服务，请检查服务与通道。')
  return items
})
function go(path: string) { router.push(path) }
async function load() {
  loading.value = true; loadError.value = ''
  try { data.value = await dashboardApi.overview() }
  catch (error) { loadError.value = (error as Error).message || '无法加载运营数据，请重试' }
  finally { loading.value = false }
}
onActivated(load)
</script>
<style scoped>
.dashboard-page { max-width: 1280px; margin: 0 auto; }
.dashboard-section { padding: 24px 0; border-bottom: 1px solid var(--wa-border); }
.dashboard-section:last-child { border-bottom: 0; }
h3 { font-size: 15px; margin: 0 0 18px; } h4 { font-size: 13px; margin: 24px 0 10px; font-weight: 500; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px; }
.metrics > div, .metrics > a { display: flex; flex-direction: column; gap: 6px; color: var(--wa-text); text-decoration: none; min-width: 0; }
.metrics strong { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.metrics span, .metrics small { font-size: 12px; color: var(--wa-text-muted); }
.resources strong { font-size: 22px; }
.task-summary { display: flex; flex-wrap: wrap; gap: 32px; color: var(--wa-text-secondary); }.task-summary b { margin-left: 8px; }
.task-links { display: flex; justify-content: flex-end; flex-wrap: wrap; margin-top: 14px; gap: 12px; }
.system-status { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; font-size: 12px; margin-top: 20px; }
.alerts { padding-left: 20px; line-height: 2; color: var(--wa-warning); }.danger { color: var(--wa-danger) !important; }.updated { align-self: center; font-size: 12px; }
@media(max-width: 768px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.updated { display: none; } }
</style>
