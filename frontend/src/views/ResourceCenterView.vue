<template>
  <PageTemplate kind="list" class="resource-center">
    <div class="page-header"><div><h2>资源中心</h2><div class="sub">从第三方平台接入号码与账号，管理可用于运营的群资源</div></div><el-button :loading="loading" @click="loadOverview">刷新概览</el-button></div>
    <section class="platform-overview"><h3>第三方资源接入概览</h3><el-alert v-if="overviewError" type="error" title="资源概览加载失败，请重试" :closable="false" /><el-table :data="platforms" v-loading="loading" size="small"><el-table-column prop="platform" label="第三方平台" min-width="180" /><el-table-column prop="available_numbers" label="可用号码" min-width="120" /><el-table-column prop="connected_accounts" label="已接入账号" min-width="120" /><el-table-column prop="groups" label="群资源" min-width="120" /><template #empty><el-empty description="暂无资源，请先导入或从资源对接获取" /></template></el-table><p class="muted">可用号码为待接入资源；已接入账号须有有效关联会话。未标注来源的资源单独汇总。</p></section>
    <el-tabs v-model="tab"><el-tab-pane label="号码资源" name="numbers" /><el-tab-pane label="接入任务" name="access" /><el-tab-pane label="群资源" name="groups" /></el-tabs>
    <keep-alive><component :is="activeView" class="resource-content" @changed="loadOverview" /></keep-alive>
  </PageTemplate>
</template>
<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resourceApi } from '@/api'
import type { ResourcePlatformOverview } from '@/types/api'
import PageTemplate from '@/components/PageTemplate.vue'
import NumbersView from '@/views/NumbersView.vue'
import RegisterView from '@/views/RegisterView.vue'
import GroupsView from '@/views/GroupsView.vue'
const route = useRoute(), router = useRouter()
const tab = computed({ get: () => ['numbers','access','groups'].includes(String(route.query.tab)) ? String(route.query.tab) : 'numbers', set: (value: string) => { router.replace({ path: '/resources', query: { tab: value } }) } })
const activeView = computed(() => ({ numbers: NumbersView, access: RegisterView, groups: GroupsView })[tab.value as 'numbers' | 'access' | 'groups'])
const platforms = ref<ResourcePlatformOverview[]>([]), loading = ref(false), overviewError = ref(false)
async function loadOverview() { if (loading.value) return; loading.value = true; try { platforms.value = await resourceApi.overview(); overviewError.value = false } catch { overviewError.value = true } finally { loading.value = false } }
onActivated(loadOverview)
</script>
<style scoped>
.platform-overview { margin-bottom: 24px; }.platform-overview h3 { font-size: 14px; margin: 20px 0 12px; font-weight: 600; }.platform-overview p { font-size: 11px; margin: 10px 0; }.resource-content { padding: 12px 0 0; }
.resource-content :deep(.page-header h2) { font-size: 16px; }
</style>
