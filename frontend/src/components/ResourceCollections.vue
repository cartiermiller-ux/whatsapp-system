<template>
  <PageTemplate kind="list">
    <div class="page-header"><div><h2>{{ kind === 'account' ? '账号分组' : '代理分组' }}</h2><p class="sub">按业务、地区或团队整理资源，已有成员的分组需先移出成员才能删除</p></div><el-button v-if="isAdmin" type="primary" @click="edit()">新建分组</el-button></div>
    <div class="filter-bar"><el-input v-model="keyword" placeholder="搜索分组名称" clearable style="width:240px" /><el-button @click="load">刷新</el-button></div>
    <el-table :data="filtered.slice((page-1)*20,page*20)" v-loading="loading"><el-table-column prop="name" label="分组名称" min-width="220"/><el-table-column prop="count" :label="kind === 'account' ? '账号数量' : '代理数量'" width="140"/><el-table-column v-if="kind === 'account'" prop="online" label="当前在线" width="140"/><el-table-column label="创建时间" width="180"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column><el-table-column v-if="isAdmin" label="操作" width="140"><template #default="{ row }"><el-button link @click="edit(row)">编辑</el-button><el-button link type="danger" :disabled="row.count > 0" @click="remove(row)">删除</el-button></template></el-table-column></el-table>
    <div class="pager"><el-pagination v-model:current-page="page" :page-size="20" :total="filtered.length" layout="total,prev,pager,next"/></div>
  </PageTemplate>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workspaceApi, type ResourceCollection } from '@/api/workspace'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import PageTemplate from './PageTemplate.vue'
const props = defineProps<{ kind: 'account' | 'proxy' }>()
const auth=useAuthStore(), isAdmin=computed(()=>['super_admin','agent_admin'].includes(auth.user?.role||''))
const rows=ref<ResourceCollection[]>([]), keyword=ref(''), page=ref(1), loading=ref(false)
const filtered=computed(()=>rows.value.filter(x=>x.name.includes(keyword.value)))
watch(keyword,()=>page.value=1)
async function load(){loading.value=true;try{rows.value=await workspaceApi.groups(props.kind)}finally{loading.value=false}}
async function edit(row?:ResourceCollection){let name:string;try{const r=await ElMessageBox.prompt('填写分组名称',row?'编辑分组':'新建分组',{inputValue:row?.name||'',inputValidator:v=>!!v?.trim()||'请输入分组名称',confirmButtonText:'保存',cancelButtonText:'取消'});name=r.value}catch{return}await workspaceApi.saveGroup(props.kind,name,row?.id);ElMessage.success('分组已保存');await load()}
async function remove(row:ResourceCollection){try{await ElMessageBox.confirm(`确认删除分组“${row.name}”？`,'删除分组',{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'})}catch{return}await workspaceApi.deleteGroup(row.id);await load()}
onMounted(load)
</script>
