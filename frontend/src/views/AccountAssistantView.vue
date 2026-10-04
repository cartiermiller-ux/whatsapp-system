<template>
  <PageTemplate kind="list">
    <div class="page-header"><div><h2>账号助手</h2><p class="sub">检查已接入账号的会话完整性与实际连接状态</p></div><div class="actions"><el-button @click="load">刷新</el-button><el-button type="primary" @click="createVisible=true">新建检测</el-button></div></div>
    <p class="muted">检测会话文件不会发送消息。会话完整不代表账号在线，也不能替代 WhatsApp 的封号或风控检测。</p>
    <div class="filter-bar"><el-input v-model="keyword" placeholder="搜索检测任务" style="width:260px" clearable/></div>
    <el-table :data="filtered.slice((page-1)*20,page*20)" v-loading="loading"><el-table-column prop="name" label="任务名称" min-width="200"/><el-table-column prop="total" label="账号总数" width="100"/><el-table-column prop="valid" label="会话完整" width="100"/><el-table-column prop="invalid" label="需要处理" width="100"/><el-table-column label="状态" width="100"><template #default>已完成</template></el-table-column><el-table-column label="创建时间" width="180"><template #default="{row}">{{formatDateTime(row.created_at)}}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{row}"><el-button link @click="current=row;detailVisible=true">查看明细</el-button></template></el-table-column></el-table>
    <div class="pager"><el-pagination v-model:current-page="page" :total="filtered.length" :page-size="20" layout="total,prev,pager,next"/></div>
    <el-dialog v-model="createVisible" title="新建账号检测" width="520px"><el-form label-position="top"><el-form-item label="任务名称"><el-input v-model="name" maxlength="100"/></el-form-item><el-form-item label="账号分组"><el-select v-model="groupId" clearable @change="selectGroup" placeholder="按分组选择"><el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id"/></el-select></el-form-item><el-form-item label="检测账号"><el-select v-model="ids" multiple filterable style="width:100%"><el-option v-for="a in accounts" :key="a.id" :label="`WA-${a.id} · ${a.phone_number||'未关联'}`" :value="a.id"/></el-select></el-form-item></el-form><template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!name.trim()||!ids.length" @click="inspect">开始检测</el-button></template></el-dialog>
    <el-drawer v-model="detailVisible" :title="current?.name" size="700px"><el-table :data="current?.results||[]"><el-table-column label="账号" width="100"><template #default="{row}">WA-{{row.account_id}}</template></el-table-column><el-table-column label="会话" width="100"><template #default="{row}"><el-tag :type="row.session_valid?'success':'danger'">{{row.session_valid?'完整':'异常'}}</el-tag></template></el-table-column><el-table-column label="连接" width="110"><template #default="{row}">{{connectionLabel(row.status)}}</template></el-table-column><el-table-column prop="reason" label="检查结果" min-width="260"/></el-table></el-drawer>
  </PageTemplate>
</template>
<script setup lang="ts">
import { computed,onMounted,ref,watch } from 'vue'
import { ElMessage } from 'element-plus'
import { accountApi } from '@/api'
import { workspaceApi,type Inspection,type ResourceCollection } from '@/api/workspace'
import type { AccountItem } from '@/types/api'
import { formatDateTime } from '@/utils/format'
import PageTemplate from '@/components/PageTemplate.vue'
const rows=ref<Inspection[]>([]),accounts=ref<AccountItem[]>([]),groups=ref<ResourceCollection[]>([]),keyword=ref(''),page=ref(1),loading=ref(false),busy=ref(false),createVisible=ref(false),detailVisible=ref(false),current=ref<Inspection>(),ids=ref<number[]>([]),groupId=ref<number>(),name=ref('账号会话检查')
const filtered=computed(()=>rows.value.filter(x=>x.name.includes(keyword.value)))
watch(keyword,()=>page.value=1)
function connectionLabel(s:string){return ({connected:'在线',closed:'连接断开',error:'连接异常',idle:'未连接',unlinked:'未关联',starting:'连接中',waiting_qr:'待扫码'} as Record<string,string>)[s]||s}
async function load(){loading.value=true;try{const [r,a,g]=await Promise.all([workspaceApi.inspections(),accountApi.list(),workspaceApi.groups('account')]);rows.value=r;accounts.value=a;groups.value=g}finally{loading.value=false}}
function selectGroup(){ids.value=accounts.value.filter(a=>!groupId.value||a.group_id===groupId.value).map(a=>a.id)}
async function inspect(){busy.value=true;try{await workspaceApi.inspect(name.value,ids.value);createVisible.value=false;ElMessage.success('检测完成');await load()}finally{busy.value=false}}
onMounted(load)
</script>
