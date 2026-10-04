<template>
  <PageTemplate kind="list"><div class="page-header"><div><h2>下载中心</h2><p class="sub">查看本人导出的登录会话记录，重新下载时会验证并打包当前会话</p></div><el-button @click="load">刷新</el-button></div><div class="filter-bar"><el-input v-model="keyword" placeholder="文件名 / 账号 ID" clearable style="width:280px"/></div><el-table :data="filtered.slice((page-1)*20,page*20)" v-loading="loading"><el-table-column prop="filename" label="文件名" min-width="280"/><el-table-column prop="account_ids" label="账号 ID" min-width="180"/><el-table-column label="创建时间" width="180"><template #default="{row}">{{formatDateTime(row.created_at)}}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{row}"><el-button link :loading="downloading===row.id" @click="download(row)">下载</el-button></template></el-table-column><template #empty><el-empty description="暂无导出记录，请到 WhatsApp 账号选择账号并导出完整会话"/></template></el-table><div class="pager"><el-pagination v-model:current-page="page" :page-size="20" :total="filtered.length" layout="total,prev,pager,next"/></div></PageTemplate>
</template>
<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {workspaceApi,type ExportRecord} from '@/api/workspace'
import {formatDateTime} from '@/utils/format'
import PageTemplate from '@/components/PageTemplate.vue'
const rows=ref<ExportRecord[]>([]),keyword=ref(''),page=ref(1),loading=ref(false),downloading=ref<number>()
const filtered=computed(()=>rows.value.filter(x=>`${x.filename} ${x.account_ids}`.includes(keyword.value)))
watch(keyword,()=>page.value=1)
async function load(){loading.value=true;try{rows.value=await workspaceApi.exports()}finally{loading.value=false}}
async function download(row:ExportRecord){downloading.value=row.id;try{const blob=await workspaceApi.download(row.id),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=row.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}finally{downloading.value=undefined}}
onMounted(load)
</script>
