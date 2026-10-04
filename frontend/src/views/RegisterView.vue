<template>
  <PageTemplate kind="list">
    <div class="page-header"><div><h2>账号接入</h2><div class="sub">第三方号码或成号 → 扫码绑定到系统 → 形成可运营 WhatsApp 账号</div></div><div class="actions"><el-button :loading="loading" @click="load">刷新</el-button><el-button @click="$router.push('/integrations')">获取第三方资源</el-button><el-button type="primary" @click="loginVisible = true">扫码接入账号</el-button></div></div>
    <p class="access-hint">已有号码需要先在 WhatsApp 完成账号开通，再扫码关联到系统。已有成号可直接扫码接入；只有有效会话绑定成功才显示“已接入”。</p>
    <div class="filter-bar"><el-input v-model="keyword" placeholder="搜索号码 / 来源平台" clearable style="width:240px" @keyup.enter="reload" /><el-select v-model="status" placeholder="接入状态" clearable style="width:140px"><el-option v-for="(label, key) in labels" :key="key" :value="key" :label="label" /></el-select><el-button @click="reload">查询</el-button><el-button @click="reset">重置</el-button></div>
    <el-alert v-if="error" type="error" title="接入记录加载失败，请刷新重试" :closable="false" />
    <el-table :data="rows" v-loading="loading"><el-table-column label="接入记录" width="120"><template #default="{ row }">IN-{{ String(row.id).padStart(3, '0') }}</template></el-table-column><el-table-column prop="source_channel" label="来源平台" min-width="140" /><el-table-column prop="phone" label="号码" min-width="170" /><el-table-column label="地区" width="100"><template #default="{ row }">{{ row.region || '未记录' }}</template></el-table-column><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ labels[row.status] || row.status }}</el-tag></template></el-table-column><el-table-column label="关联账号" min-width="120"><template #default="{ row }"><router-link v-if="row.account_id" to="/accounts">WA-{{ String(row.account_id).padStart(3, '0') }}</router-link><span v-else>—</span></template></el-table-column><el-table-column prop="reason" label="接入说明" min-width="230" /><el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="!row.linked" link type="primary" @click="loginVisible = true">扫码接入</el-button><el-button v-else link @click="$router.push('/accounts')">查看账号</el-button></template></el-table-column><template #empty><el-empty description="暂无接入记录，请先获取或导入号码资源" /></template></el-table>
    <div class="pager"><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" /></div>
    <WhatsAppLoginDialog v-model="loginVisible" @registered="afterLinked" />
  </PageTemplate>
</template>
<script setup lang="ts">
import { onActivated, ref } from 'vue'
import { resourceApi } from '@/api'
import type { AccessTaskRow } from '@/types/api'
import { statusTagType } from '@/utils/format'
import PageTemplate from '@/components/PageTemplate.vue'
import WhatsAppLoginDialog from '@/components/WhatsAppLoginDialog.vue'
const emit = defineEmits<{ changed: [] }>()
const labels: Record<string,string> = { pending: '待接入', registering: '接入中', success: '已接入', failed: '接入失败' }
const loading = ref(false), error = ref(false), loginVisible = ref(false), keyword = ref(''), status = ref(''), page = ref(1), total = ref(0), rows = ref<AccessTaskRow[]>([])
async function load() { loading.value = true; try { const result = await resourceApi.accessTasks({ page: page.value, size: 20, keyword: keyword.value, status: status.value }); rows.value = result.list; total.value = result.total; error.value = false } catch { error.value = true } finally { loading.value = false } }
function reload() { page.value = 1; load() }
function reset() { keyword.value = ''; status.value = ''; reload() }
async function afterLinked() { await load(); emit('changed') }
onActivated(load)
</script>
<style scoped>
.access-hint { color: var(--wa-text-muted); font-size: 12px; line-height: 1.7; margin: 0 0 20px; }
</style>
