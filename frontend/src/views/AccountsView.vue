<template>
  <PageTemplate kind="list" class="accounts-page">
    <div class="page-header">
      <div><h2>WhatsApp 账号</h2><div class="sub">管理 WhatsApp 账号状态、养号进度与运行健康度</div></div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAccounts">刷新</el-button>
    </div>
    <el-alert v-if="apiError" type="error" show-icon :closable="false" title="账号数据加载失败，请刷新重试" class="block-gap" />
    <section class="account-overview" aria-label="账号总览">
      <div><span>全部账号</span><strong>{{ overview.total }}</strong><small>{{ overview.normal }} 个正常</small></div>
      <div><span><i class="state-dot good" />已就绪</span><strong>{{ overview.ready }}</strong><small>正常且养号已就绪</small></div>
      <div><span><i class="state-dot caution" />养号中</span><strong>{{ overview.nurturing }}</strong><small>正在养号或稳定阶段</small></div>
      <div><span><i class="state-dot bad" />异常</span><strong>{{ overview.abnormal }}</strong><small>需要检查或处理</small></div>
    </section>
    <div class="filter-bar account-filters">
      <el-input v-model="filters.keyword" placeholder="搜索账号 / 手机号 / IP" :prefix-icon="Search" clearable class="account-search" />
      <el-select v-model="filters.group_id" placeholder="账号分组" clearable style="width:150px"><el-option v-for="group in groups" :key="group.id" :value="group.id" :label="group.name"/></el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px"><el-option v-for="(label, key) in ACCOUNT_STATUS_LABEL" :key="key" :value="key" :label="label" /><el-option value="abnormal" label="全部异常" /></el-select>
      <el-select v-model="filters.stage" placeholder="阶段" clearable style="width: 140px"><el-option v-for="(label, key) in NURTURE_STAGE_LABEL" :key="key" :value="key" :label="label" /></el-select>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" :icon="Iphone" class="login-action" @click="loginVisible = true">扫码登录 WhatsApp</el-button>
      <el-button v-if="isAdmin" @click="importVisible=true">导入账号</el-button>
    </div>
    <div v-if="isAdmin && selected.length" class="actions batch-actions"><span>已选 {{ selected.length }} 个账号</span><el-button @click="assignVisible=true">分配分组</el-button><el-button :loading="converting" @click="convertSelected">验证完整会话</el-button><el-button :loading="exporting" @click="exportSelected">导出完整会话 ZIP</el-button></div>
    <el-alert v-if="conversionFailures.length" type="warning" :closable="false" title="部分账号转换失败" :description="conversionFailures.map(item => `${accountName(item.id)}：${item.reason}`).join('；')" class="block-gap" />
    <el-table v-loading="loading" :data="pagedAccounts" @selection-change="selected = $event" class="account-table" row-key="id">
      <el-table-column v-if="isAdmin" type="selection" width="44" />
      <el-table-column label="账号" min-width="190">
        <template #default="{ row }"><div class="account-identity"><strong>{{ row.phone_number ? maskedPhone(row.phone_number) : accountName(row.id) }}</strong><span class="cell-secondary">{{ row.phone_number ? `${accountName(row.id)} · 号码 #${row.number_id}` : `号码 #${row.number_id}` }}</span><span v-if="isMobile(row)" class="identity-note">{{ connectionLabel(row.connection_state) }} · 有效在线 {{ Math.floor((row.online_seconds||0)/60) }} 分钟</span><span v-if="isMobile(row) && row.mobile_error" class="identity-note text-danger">{{ mobileError(row.mobile_error) }}</span><span class="identity-note">{{ row.device_type === 'full_params' ? '手机全参账号' : row.device_type === 'six_segment' ? '六段手机账号' : row.full_params_ready ? '完整会话已验证' : row.session_name ? '已关联手机账号' : '尚未关联手机账号' }}</span></div></template>
      </el-table-column>
      <el-table-column label="健康度" min-width="145">
        <template #default="{ row }">
          <el-popover trigger="hover" placement="top" :width="290">
            <template #reference><button class="health-trigger" :aria-label="`查看健康评分 ${row.health_score} 的说明`" @click="openDetail(row.id)"><div class="health-heading"><strong :style="{ color: healthColor(row.health_score) }">{{ row.health_score }}</strong><span :style="{ color: healthColor(row.health_score) }">{{ healthLabel(row.health_score) }}</span></div><el-progress :percentage="Math.max(0, Math.min(100, row.health_score))" :color="healthColor(row.health_score)" :stroke-width="5" :show-text="false" /></button></template>
            <strong>健康评分 {{ row.health_score }}</strong><p class="muted">当前为已记录总分，细分评分尚未采集。</p><dl class="health-breakdown"><dt>登录状态</dt><dd>{{ connectionLabel(row.connection_state) }}</dd><dt>代理检测</dt><dd>{{ networkLabel(row.network_state) }}</dd><dt>近 7 天执行成功率</dt><dd>{{ row.activity_success_rate === null || row.activity_success_rate === undefined ? '暂无执行记录' : `${row.activity_success_rate}%` }}</dd><dt>风险状态</dt><dd>{{ ACCOUNT_STATUS_LABEL[row.status] || row.status }}</dd></dl>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column label="分组 / 类型" min-width="150"><template #default="{row}"><div>{{groups.find(g=>g.id===row.group_id)?.name||'未分组'}}</div><small class="cell-secondary">{{row.account_type==='business'?'商业号':'个人号'}} · {{ row.device_type === 'full_params' ? '手机全参' : row.device_type === 'six_segment' ? '六段账号' : '关联设备' }}</small></template></el-table-column>
      <el-table-column label="养号阶段" min-width="180">
        <template #default="{ row }"><div class="stage-track" :aria-label="`初始化、养号、稳定、已就绪；当前${stageLabel(row.nurture_stage)}`"><span v-for="step in 4" :key="step" :class="{ reached: step <= stageIndex(row.nurture_stage), ready: stageIndex(row.nurture_stage) === 4 }" /></div><div>{{ stageLabel(row.nurture_stage) }}<template v-if="row.nurture_days && row.nurture_stage === 'nurturing'"> · 第 {{ row.nurture_days }} 天</template></div><small class="cell-secondary">{{ row.nurture_days ? '初始化 → 养号 → 稳定 → 就绪' : row.account_age_days ? `关联第 ${row.account_age_days} 天` : '养号起始时间未记录' }}</small></template>
      </el-table-column>
      <el-table-column label="网络" min-width="190">
        <template #default="{ row }"><div>{{ row.network_country ? `${countryLabel(row.network_country)}节点` : row.ip ? '地区未记录' : '未分配代理' }}</div><span class="cell-secondary mono">{{ row.ip || '—' }}</span><small class="network-meta" :class="{ 'text-danger': row.network_state === 'failed' }">{{ networkLabel(row.network_state) }}<template v-if="row.latency_ms !== null && row.latency_ms !== undefined"> · {{ row.latency_ms }} ms</template></small></template>
      </el-table-column>
      <el-table-column label="状态" min-width="125">
        <template #default="{ row }"><div class="account-status"><i class="state-dot" :class="statusTone(row)" /><strong>{{ stateLabel(row) }}</strong></div><span class="cell-secondary">{{ connectionLabel(row.connection_state) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="115" fixed="right">
        <template #default="{ row }"><div class="row-actions"><el-button link @click="openDetail(row.id)">详情</el-button><el-dropdown trigger="click" @command="(command: string) => onRowCommand(command, row)"><button class="more-action" :aria-label="`${accountName(row.id)} 的更多操作`">⋯</button><template #dropdown><el-dropdown-menu>
          <el-dropdown-item v-if="row.status === 'normal' || row.status === 'watch'" command="pause">暂停账号</el-dropdown-item>
          <el-dropdown-item v-if="row.status === 'paused'" command="resume">恢复账号</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin" command="proxy">更换代理</el-dropdown-item>
          <el-dropdown-item command="logs">查看日志</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin && row.nurture_stage==='none'" command="nurture_start">开始养号</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin && row.nurture_stage==='nurturing'" command="nurture_pause">暂停养号</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin && row.nurture_stage==='paused'" command="nurture_resume">恢复养号</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin && row.nurture_stage==='nurturing'" command="nurture_finish">确认完成养号</el-dropdown-item>
          <el-dropdown-item v-if="isMobile(row)" command="mobile_login">手机协议登录 / 检测</el-dropdown-item><el-dropdown-item v-if="isMobile(row)" command="mobile_disconnect">断开手机连接</el-dropdown-item><el-dropdown-item v-else command="login">重新登录</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin" command="convert" :disabled="!row.session_name || converting" divided>转换全参</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin" command="export" :disabled="!row.full_params_ready || exporting">导出完整会话 ZIP</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin" command="delete" divided>删除账号</el-dropdown-item>
        </el-dropdown-menu></template></el-dropdown></div></template>
      </el-table-column>
      <template #empty><el-empty :description="accounts.length ? '没有符合筛选条件的账号' : '暂无账号，请扫码关联手机账号'" /></template>
    </el-table>
    <div class="pager"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 20, 50]" :total="filteredAccounts.length" layout="total, sizes, prev, pager, next" background /></div>
    <div class="account-distribution"><span>账号状态</span><span>正常 {{ overview.normal }}</span><div class="distribution-track" role="img" :aria-label="`正常账号占比${normalRate}%`"><span :style="{ width: `${normalRate}%` }" /></div><span>{{ normalRate }}%</span><span class="muted">异常 {{ overview.abnormal }}</span></div>
    <el-drawer v-model="detailVisible" title="账号详情" size="480px"><div v-loading="detailLoading"><el-descriptions v-if="current" :column="1" border><el-descriptions-item label="账号">{{ accountName(current.id) }}</el-descriptions-item><el-descriptions-item label="手机号">{{ current.phone_number || '未记录' }}</el-descriptions-item><el-descriptions-item label="号码 ID">{{ current.number_id }}</el-descriptions-item><el-descriptions-item label="健康度">{{ current.health_score }} · {{ healthLabel(current.health_score) }}</el-descriptions-item><el-descriptions-item label="养号阶段">{{ stageLabel(current.nurture_stage) }}</el-descriptions-item><el-descriptions-item label="当前 IP">{{ current.current_ip || '未记录' }}</el-descriptions-item><el-descriptions-item label="状态">{{ ACCOUNT_STATUS_LABEL[current.status] || current.status }}</el-descriptions-item><el-descriptions-item label="全参状态">{{ current.full_params_ready ? '已转换' : '待转换' }}</el-descriptions-item><el-descriptions-item label="关联时间">{{ formatDateTime(current.created_at) }}</el-descriptions-item></el-descriptions></div></el-drawer>
    <el-drawer v-model="logsVisible" :title="`${accountName(logAccountId)} · 执行日志`" size="700px"><el-table :data="accountLogs" v-loading="logsLoading"><el-table-column label="时间" width="160"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column><el-table-column label="结果" width="100"><template #default="{ row }">{{ row.result === 'success' ? '成功' : row.result === 'failed' ? '失败' : '待核对' }}</template></el-table-column><el-table-column prop="detail" label="说明" min-width="200" /></el-table><div class="pager"><el-pagination v-model:current-page="logPage" :page-size="20" :total="logTotal" layout="total, prev, next" @current-change="loadLogs" /></div></el-drawer>
    <el-dialog v-model="proxyVisible" title="更换账号代理" width="460px"><el-select v-model="proxyId" placeholder="选择真实、空闲的代理" style="width: 100%" filterable><el-option v-for="proxy in proxies" :key="proxy.id" :value="proxy.id" :label="`${countryLabel(proxy.country)} · ${proxy.host}:${proxy.port}`" /></el-select><p v-if="!proxies.length" class="muted">没有真实空闲代理，请先到资源对接导入或同步代理。</p><template #footer><el-button @click="proxyVisible = false">取消</el-button><el-button type="primary" :disabled="!proxyId" :loading="proxySaving" @click="saveProxy">保存</el-button></template></el-dialog>
    <WhatsAppLoginDialog v-model="loginVisible" @registered="loadAccounts" />
    <el-dialog v-model="assignVisible" title="分配账号分组" width="420px"><el-select v-model="assignedGroup" clearable placeholder="未分组" style="width:100%"><el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id"/></el-select><template #footer><el-button @click="assignVisible=false">取消</el-button><el-button type="primary" @click="assignSelected">保存</el-button></template></el-dialog>
    <el-dialog v-model="importVisible" title="导入账号" width="540px"><p class="muted">支持手机全参 JSON、六段文本和完整会话 ZIP。全参与六段导入后，在账号操作中选择手机协议登录，服务器确认在线后可开始养号。</p><el-form label-position="top"><el-form-item label="导入格式"><el-select v-model="importFormat"><el-option label="手机全参 JSON / JSONL" value="full_params"/><el-option label="六段文本（每行一个账号）" value="six_segment"/><el-option label="完整会话 ZIP" value="zip"/></el-select></el-form-item><el-form-item label="账号分组"><el-select v-model="importGroup" clearable placeholder="未分组"><el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id"/></el-select></el-form-item><el-form-item label="账号类型"><el-radio-group v-model="importType"><el-radio value="personal">个人号</el-radio><el-radio value="business">商业号</el-radio></el-radio-group></el-form-item><template v-if="importFormat!=='zip'"><el-form-item label="粘贴账号凭据（每次最多 100 个）"><el-input v-model="credentialText" type="textarea" :rows="8" placeholder="粘贴全参 JSON、JSON 数组、JSONL，或六段文本"/></el-form-item><el-form-item label="或上传 TXT / JSON / JSONL（最大 2 MB）"><input type="file" accept=".txt,.json,.jsonl,.csv" @change="chooseCredentials"/></el-form-item></template><el-form-item v-else label="会话 ZIP（最大 12 MB）"><input type="file" accept=".zip" @change="chooseArchive"/></el-form-item></el-form><template #footer><el-button @click="importVisible=false">取消</el-button><el-button type="primary" :loading="importing" :disabled="importFormat==='zip' ? !archiveData : !credentialText.trim()" @click="importArchive">导入</el-button></template></el-dialog>
  </PageTemplate>
</template>
<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Iphone, Refresh, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { accountApi, integrationApi, whatsappApi } from '@/api'
import { workspaceApi, type ResourceCollection } from '@/api/workspace'
import type { AccountDetail, AccountItem, ProxyRow, TaskLogRow } from '@/types/api'
import { ACCOUNT_STATUS_LABEL, NURTURE_STAGE_LABEL, formatDateTime } from '@/utils/format'
import PageTemplate from '@/components/PageTemplate.vue'
import WhatsAppLoginDialog from '@/components/WhatsAppLoginDialog.vue'
const auth = useAuthStore()
const isAdmin = computed(() => ['super_admin', 'agent_admin'].includes(auth.user?.role || ''))
const loading = ref(false), apiError = ref(false), loginVisible = ref(false), accounts = ref<AccountItem[]>([])
const filters = reactive({ keyword: '', status: '', stage: '', group_id: undefined as number|undefined }), page = ref(1), pageSize = ref(10)
const groups=ref<ResourceCollection[]>([]),assignVisible=ref(false),assignedGroup=ref<number>(),importVisible=ref(false),importGroup=ref<number>(),importType=ref('personal'),archiveData=ref(''),importing=ref(false)
async function assignSelected(){await workspaceApi.assignGroup('account',selected.value.map(x=>x.id),assignedGroup.value||null);assignVisible.value=false;await loadAccounts()}
function chooseArchive(event:Event){archiveData.value='';const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;if(file.size>12*1024*1024){ElMessage.warning('ZIP 文件不能超过 12 MB');return}const reader=new FileReader();reader.onload=()=>{archiveData.value=String(reader.result).split(',')[1]||''};reader.readAsDataURL(file)}
async function importArchive(){importing.value=true;try{const r=importFormat.value==='zip'?await workspaceApi.imports(archiveData.value,importGroup.value||null,importType.value):await workspaceApi.importCredentials(importFormat.value,credentialText.value,importGroup.value||null,importType.value);ElMessage.success(`已导入 ${r.imported} 个账号，请发起登录验证`);importVisible.value=false;archiveData.value='';credentialText.value='';await loadAccounts()}finally{importing.value=false}}
const importFormat=ref<'full_params'|'six_segment'|'zip'>('full_params'),credentialText=ref('')
async function chooseCredentials(event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;if(file.size>2_000_000){ElMessage.warning('文件不能超过 2 MB');return}credentialText.value=await file.text()}
const selected = ref<AccountItem[]>([]), converting = ref(false), exporting = ref(false)
const conversionFailures = ref<{ id: number; reason: string }[]>([])
const detailVisible = ref(false), detailLoading = ref(false), current = ref<AccountDetail | null>(null)
const logsVisible = ref(false), logsLoading = ref(false), accountLogs = ref<TaskLogRow[]>([]), logAccountId = ref(0), logPage = ref(1), logTotal = ref(0)
const proxyVisible = ref(false), proxySaving = ref(false), proxyId = ref<number>(), proxyAccountId = ref(0), proxies = ref<ProxyRow[]>([])
const overview = computed(() => ({ total: accounts.value.length, normal: accounts.value.filter(a => a.status === 'normal' && !a.abnormal).length, ready: accounts.value.filter(a => a.status === 'normal' && ['ready', 'done'].includes(a.nurture_stage) && !a.abnormal).length, nurturing: accounts.value.filter(a => ['nurturing', 'stable'].includes(a.nurture_stage)).length, abnormal: accounts.value.filter(a => a.abnormal ?? a.status !== 'normal').length }))
const normalRate = computed(() => overview.value.total ? Math.round(overview.value.normal / overview.value.total * 100) : 0)
const filteredAccounts = computed(() => accounts.value.filter(a => (!filters.group_id || a.group_id===filters.group_id) && (!filters.status || (filters.status === 'abnormal' ? a.abnormal : a.status === filters.status)) && (!filters.stage || a.nurture_stage === filters.stage) && (!filters.keyword || `${accountName(a.id)} ${a.id} ${a.number_id} ${a.phone_number || ''} ${a.ip}`.toLowerCase().includes(filters.keyword.toLowerCase()))))
const pagedAccounts = computed(() => filteredAccounts.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
watch([() => filters.keyword, () => filters.status, () => filters.stage, pageSize], () => { page.value = 1; selected.value = [] })
watch(() => filteredAccounts.value.length, total => { page.value = Math.min(page.value, Math.max(1, Math.ceil(total / pageSize.value))) })
function accountName(id: number) { return `WA-${String(id).padStart(3, '0')}` }
function maskedPhone(phone: string) { return `+${phone.slice(0, Math.max(1, phone.length - 8))} ${phone.slice(-8, -4)} *** ${phone.slice(-4)}` }
function healthColor(score: number) { return score >= 90 ? '#15803d' : score >= 70 ? '#b45309' : '#b42318' }
function healthLabel(score: number) { return score >= 98 ? '优秀' : score >= 90 ? '健康' : score >= 70 ? '注意' : '风险' }
function stageIndex(stage: string) { return ({ none: 1, nurturing: 2, stable: 3, ready: 4, done: 4 } as Record<string, number>)[stage] || 1 }
function stageLabel(stage: string) { return stage === 'none' ? '初始化' : (stage === 'paused' ? '养号已暂停' : NURTURE_STAGE_LABEL[stage]) || stage }
function countryLabel(country: string) { return ({ CN: '中国', US: '美国', GB: '英国', BR: '巴西', ID: '印尼', IN: '印度', MX: '墨西哥', RU: '俄罗斯' } as Record<string, string>)[country] || country || '地区未记录' }
function connectionLabel(state?: string) { return ({ starting: '手机登录中', pending_adapter: '手机引擎未安装', online: '在线', offline: '当前未连接', unlinked: '未关联', invalid: '登录失效', error: '连接异常' } as Record<string, string>)[state || ''] || '未检测' }
function networkLabel(state?: string) { return ({ healthy: '最近检测正常', failed: '代理异常', mock: '模拟代理', stale: '检测已过期', unknown: '未检测' } as Record<string, string>)[state || ''] || '未检测' }
function stateLabel(row: AccountItem) { if(isMobile(row)) return connectionLabel(row.connection_state); if (row.status !== 'normal') return ACCOUNT_STATUS_LABEL[row.status] || row.status; if (['invalid', 'error'].includes(row.connection_state || '')) return connectionLabel(row.connection_state); if (row.network_state === 'failed') return '代理异常'; if (row.health_score < 70) return '健康风险'; return '正常' }
function statusTone(row: AccountItem) { return row.abnormal ? row.status === 'paused' ? 'muted-dot' : 'bad' : 'good' }
function resetFilters() { filters.keyword = ''; filters.status = ''; filters.stage = '';filters.group_id=undefined }
async function loadAccounts() { loading.value = true; try { const [rows,collections]=await Promise.all([accountApi.list(),workspaceApi.groups('account')]);accounts.value=rows;groups.value=collections;apiError.value = false; selected.value = [] } catch { apiError.value = true } finally { loading.value = false } }
async function openDetail(id: number) { detailVisible.value = true; detailLoading.value = true; current.value = null; try { current.value = await accountApi.detail(id) } finally { detailLoading.value = false } }
async function convertAccount(id: number) { converting.value = true; try { const result = await accountApi.convert(id); ElMessage.success(`完整会话已转换，包含 ${result.files} 个文件`); await loadAccounts() } finally { converting.value = false } }
async function convertSelected() { converting.value = true; try { const result = await accountApi.convertMany(selected.value.map(row => row.id)); conversionFailures.value = result.failures; ElMessage[result.failures.length ? 'warning' : 'success'](`转换成功 ${result.converted.length} 个，失败 ${result.failures.length} 个`); await loadAccounts() } finally { converting.value = false } }
async function exportSelected() { await exportAccounts(selected.value.map(row => row.id)) }
async function exportAccounts(ids: number[]) {
  if (ids.some(id => !accounts.value.find(row => row.id === id)?.full_params_ready)) { ElMessage.warning('请先转换所选账号的全参'); return }
  exporting.value = true
  try { const archive = await accountApi.export(ids), url = URL.createObjectURL(archive), anchor = document.createElement('a'); anchor.href = url; anchor.download = `whatsapp-accounts-${ids.length}.zip`; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); ElMessage.success('完整登录会话 ZIP 已导出') } finally { exporting.value = false }
}
async function loadLogs() { logsLoading.value = true; try { const result = await accountApi.logs(logAccountId.value, { page: logPage.value, size: 20 }); accountLogs.value = result.list; logTotal.value = result.total } finally { logsLoading.value = false } }
async function saveProxy() { if (!proxyId.value) return; proxySaving.value = true; try { const result = await accountApi.assignProxy(proxyAccountId.value, proxyId.value); ElMessage.success(result.message); proxyVisible.value = false; await loadAccounts() } finally { proxySaving.value = false } }
async function onRowCommand(command: string, row: AccountItem) {
  if(command==='mobile_login'){await workspaceApi.mobileConnect(row.id);ElMessage.success('登录已发起，正在等待真实连接结果');await loadAccounts();return}
  if(command==='mobile_disconnect'){await workspaceApi.mobileDisconnect(row.id);ElMessage.success('手机连接已断开');await loadAccounts();return}
  if(command.startsWith('nurture_')){await workspaceApi.nurture(row.id,command.slice(8));ElMessage.success('养号阶段已更新');await loadAccounts();return}
  if (command === 'convert') return convertAccount(row.id)
  if (command === 'export') return exportAccounts([row.id])
  if (command === 'logs') { logAccountId.value = row.id; logPage.value = 1; accountLogs.value = []; logsVisible.value = true; return loadLogs() }
  if (command === 'proxy') { proxies.value = (await integrationApi.listProxies({ status: 'free', page: 1, size: 200 })).list.filter(p => p.provider !== 'mock'); proxyAccountId.value = row.id; proxyId.value = undefined; proxyVisible.value = true; return }
  if (command === 'login') { if (row.session_name) await whatsappApi.switchAccount(row.id); loginVisible.value = true; return }
  if (command === 'delete') { try { await ElMessageBox.confirm(`确认删除 ${accountName(row.id)} 的账号登记？登录会话文件仍会保留。`, '删除账号', { type: 'warning' }) } catch { return }; await accountApi.remove(row.id); ElMessage.success('账号登记已删除') }
  if (command === 'pause') { await accountApi.pause(row.id); ElMessage.success('账号已暂停') }
  if (command === 'resume') { await accountApi.resume(row.id); ElMessage.success('账号已恢复') }
  await loadAccounts()
}
function mobileError(code:string){return ({login_failed:'手机认证未成功，请检查账号凭据、版本和代理',protocol_login:'手机协议认证失败',connect_failed:'手机引擎连接失败',engine_stopped:'手机引擎已停止',disconnect_logged_out:'登录已失效'} as Record<string,string>)[code]||code}
function isMobile(row:AccountItem){return ['full_params','six_segment'].includes(row.device_type||'')&&!row.session_name}
let mobilePoll:ReturnType<typeof setInterval>|undefined
let pollActive=true
onMounted(()=>{loadAccounts();mobilePoll=setInterval(async()=>{if(!pollActive||loading.value||!accounts.value.some(isMobile))return;try{accounts.value=await accountApi.list()}catch{}},5000)})
onUnmounted(()=>{if(mobilePoll)clearInterval(mobilePoll)})
onActivated(()=>{pollActive=true;if(!loading.value)loadAccounts()})
onDeactivated(()=>{pollActive=false})
</script>
<style scoped>
.account-overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px; padding: 20px 0 24px; border-bottom: 1px solid var(--wa-border); margin-bottom: 20px; }
.account-overview > div { display: grid; gap: 4px; }.account-overview strong { font-size: 26px; line-height: 1.3; font-weight: 600; font-variant-numeric: tabular-nums; }.account-overview span { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--wa-text-secondary); }.account-overview small { font-size: 11px; color: var(--wa-text-muted); }
.state-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }.good { background: #15803d; }.caution { background: #b45309; }.bad { background: #b42318; }.muted-dot { background: #737373; }
.account-search { width: 250px; }.login-action { margin-left: auto; }.batch-actions { padding: 10px 0 16px; align-items: center; }.account-table :deep(.el-table__cell) { padding: 16px 0; }.account-table :deep(.cell) { line-height: 1.6; }
.account-identity { display: flex; flex-direction: column; }.account-identity strong { font-weight: 600; }.cell-secondary { display: block; font-size: 12px; color: var(--wa-text-muted); }.identity-note, .network-meta { display: block; font-size: 11px; color: var(--wa-text-muted); }.network-meta { margin-top: 2px; }.text-danger { color: #b42318; }
.health-trigger { width: 110px; border: 0; background: transparent; padding: 0; cursor: pointer; text-align: left; }.health-heading { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }.health-heading strong { font-size: 22px; line-height: 1.2; }.health-heading span { font-size: 12px; }.health-breakdown { display: grid; grid-template-columns: 1fr auto; gap: 8px; font-size: 12px; }.health-breakdown dd { margin: 0; color: var(--wa-text-muted); }
.stage-track { display: flex; gap: 5px; margin-bottom: 7px; }.stage-track span { width: 7px; height: 7px; border-radius: 50%; background: #e5e5e5; }.stage-track .reached { background: #b45309; }.stage-track .ready { background: #15803d; }
.account-status { display: flex; align-items: center; gap: 6px; }.account-status strong { font-weight: 500; }.row-actions { display: flex; align-items: center; gap: 10px; }.more-action { border: 0; background: transparent; color: var(--wa-text-secondary); font-size: 22px; cursor: pointer; padding: 0 6px; border-radius: 4px; }.more-action:hover { background: var(--wa-hover); }.more-action:focus-visible, .health-trigger:focus-visible { outline: 2px solid var(--wa-primary); outline-offset: 3px; }
.account-distribution { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding-top: 20px; margin-top: 20px; border-top: 1px solid var(--wa-border); font-size: 12px; }.distribution-track { width: 120px; height: 4px; background: #e5e5e5; overflow: hidden; border-radius: 2px; }.distribution-track span { display: block; height: 100%; background: #15803d; }
@media(max-width: 700px) { .account-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }.account-search { width: 100%; }.login-action { margin-left: 0; } }
</style>
