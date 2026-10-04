<template>
  <div class="account-center">
    <el-tabs v-model="tab" class="center-tabs"><el-tab-pane label="账号列表" name="list"/><el-tab-pane label="账号分组" name="groups"/><el-tab-pane label="账号日志" name="logs"/><el-tab-pane v-if="isAdmin" label="账号商城" name="shop"/><el-tab-pane v-if="isAdmin" label="购买历史" name="history"/></el-tabs>
    <AccountsView v-if="tab==='list'"/>
    <ResourceCollections v-else-if="tab==='groups'" kind="account"/>
    <IntegrationsView v-else-if="tab==='shop'||tab==='history'" :key="tab" initial-tab="purchase" :purchase-mode="tab==='shop'?'catalog':'history'" embedded/>
    <PageTemplate v-else kind="list"><div class="page-header"><div><h2>账号日志</h2><p class="sub">账号接入、分组、代理分配和导出操作的真实记录</p></div><el-button @click="loadLogs">刷新</el-button></div><div class="filter-bar"><el-input v-model="keyword" placeholder="操作类型 / 对象" clearable style="width:260px" @keyup.enter="searchLogs"/><el-button @click="searchLogs">查询</el-button></div><el-table :data="logs" v-loading="loading"><el-table-column label="时间" width="180"><template #default="{row}">{{formatDateTime(row.created_at)}}</template></el-table-column><el-table-column prop="username" label="操作人" width="120"/><el-table-column label="操作" width="180"><template #default="{row}">{{actionLabel(row.action)}}</template></el-table-column><el-table-column prop="target" label="对象" width="180"/><el-table-column prop="detail" label="说明" min-width="240"/><el-table-column label="结果" width="100"><template #default="{row}">{{row.result==='success'?'成功':row.result}}</template></el-table-column></el-table><div class="pager"><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" @current-change="loadLogs"/></div></PageTemplate>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AccountsView from './AccountsView.vue'
import IntegrationsView from './IntegrationsView.vue'
import ResourceCollections from '@/components/ResourceCollections.vue'
import PageTemplate from '@/components/PageTemplate.vue'
import { useAuthStore } from '@/stores/auth'
import { workspaceApi, type AccountAudit } from '@/api/workspace'
import { formatDateTime } from '@/utils/format'
const route=useRoute(), router=useRouter(), auth=useAuthStore()
const isAdmin=computed(()=>['super_admin','agent_admin'].includes(auth.user?.role||''))
const tab=ref(['list','groups','logs','shop','history'].includes(String(route.query.tab))?String(route.query.tab):'list')
const logs=ref<AccountAudit[]>([]),page=ref(1),total=ref(0),keyword=ref(''),loading=ref(false)
function actionLabel(a:string){return ({convert_account:'验证会话',convert_accounts:'批量验证会话',export_accounts:'导出会话',import_sessions:'导入会话',assign_group:'分配分组',delete_account:'删除账号',assign_proxy:'分配代理',create_inspection:'账号检测'} as Record<string,string>)[a]||a}
async function loadLogs(){loading.value=true;try{const r=await workspaceApi.logs(page.value,keyword.value);logs.value=r.list;total.value=r.total}finally{loading.value=false}}
function searchLogs(){page.value=1;loadLogs()}
watch(tab,v=>{router.replace({query:{tab:v}});if(v==='logs')loadLogs()},{immediate:true})
watch(()=>route.query.tab,v=>{if(v&&['list','groups','logs','shop','history'].includes(String(v)))tab.value=String(v)})
</script>
<style scoped>.center-tabs{padding:0 16px}.center-tabs :deep(.el-tabs__header){margin-bottom:0}</style>
