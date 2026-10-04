<template>
  <PageTemplate kind="list">
    <div class="page-header">
      <div>
        <h2>群资源</h2>
        <div class="sub">管理账号接入后的运营群资源与邀请链接</div>
      </div>
      <div class="actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button><el-button @click="exportGroups">导出</el-button><el-button type="primary" @click="importVisible = true">导入资源群</el-button></div>
    </div>


    <section>
      <div class="filter-bar">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索群名称"
          style="width: 220px"
          :prefix-icon="Search"
          clearable
          @keyup.enter="reload"
        />
        <el-select v-model="filters.status" placeholder="状态" style="width: 140px" clearable>
          <el-option label="活跃" value="active" />
          <el-option label="停用" value="disabled" />
        </el-select>
        <el-button :icon="Search" @click="reload">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-tag type="info" effect="plain">按营销价值分降序</el-tag>
      </div>
      <div v-if="selectedIds.length" class="batch-toolbar">
        <span>已选择 {{ selectedIds.length }} 个资源群</span>
        <el-button
          type="primary"
          :icon="Link"
          :loading="fetching"
          :disabled="selectedIds.length === 0"
          @click="fetchLinks"
        >
          批量获取群链接{{ selectedIds.length ? `(${selectedIds.length})` : '' }}
        </el-button>
        <el-button type="danger" plain @click="removeGroups">删除所选</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="来源平台" min-width="120"><template #default="{ row }">{{ row.source_channel || '未标注来源' }}</template></el-table-column>
        <el-table-column prop="group_name" label="群名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="group_jid" label="群 JID" min-width="170" class-name="mono" show-overflow-tooltip />
        <el-table-column label="群链接" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link
              v-if="row.group_link"
              type="primary"
              :href="row.group_link"
              target="_blank"
              :underline="false"
            >
              {{ row.group_link }}
            </el-link>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="可发言" width="80">
          <template #default="{ row }">
            <el-tag :type="row.can_speak ? 'success' : 'info'" size="small" effect="plain">
              {{ row.can_speak ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可拉人" width="80">
          <template #default="{ row }">
            <el-tag :type="row.can_invite ? 'success' : 'info'" size="small" effect="plain">
              {{ row.can_invite ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="批准模式" width="100">
          <template #default="{ row }">
            <el-tag :type="row.approval_mode ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.approval_mode ? '需批准' : '自由加入' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="group_owner" label="群主" min-width="110" />
        <el-table-column label="营销价值分" width="130" sortable>
          <template #default="{ row }">
            <el-progress
              :percentage="row.marketing_score"
              :stroke-width="12"
              :color="scoreColor(row.marketing_score)"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
              {{ row.status === 'active' ? '活跃' : row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无群资源，请导入已有群的 JID 与名称" />
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="onSizeChange"
        />
      </div>
    </section>

    <el-alert v-if="linkFailures.length" type="warning" :closable="false" title="部分群链接获取失败" :description="linkFailures.map(item => `#${item.id}：${item.reason}`).join('；')" class="section-gap" />
    <el-dialog v-model="importVisible" title="导入资源群" width="560px"><el-input v-model="importSource" placeholder="来源平台（可选）" class="block-gap" /><el-select v-model="importAccount" placeholder="所属 WhatsApp 账号（获取群链接时使用）" clearable style="width:100%;margin-top:12px"><el-option v-for="account in accounts.filter(a => a.session_name)" :key="account.id" :value="account.id" :label="`WA-${String(account.id).padStart(3, '0')}`" /></el-select><p class="muted">每行填写“群 JID, 群名称”，也可粘贴导出的 JSON 数组。</p><el-input v-model="importText" type="textarea" :rows="8" placeholder="12345@g.us, 测试资源群" /><template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="importing" @click="importGroups">导入</el-button></template></el-dialog>
  </PageTemplate>
</template>

<script setup lang="ts">
import PageTemplate from '@/components/PageTemplate.vue'
import { onActivated, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Link, Refresh, Search } from '@element-plus/icons-vue'
import { groupApi, accountApi } from '@/api'
import type { GroupRow, AccountItem } from '@/types/api'

const emit = defineEmits<{ changed: [] }>()
const loading = ref(false)
const rows = ref<GroupRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const filters = reactive({ keyword: '', status: '' })

const selectedIds = ref<number[]>([])
const fetching = ref(false)
const importVisible = ref(false), importing = ref(false), importText = ref('')
const importSource = ref('')
const importAccount = ref<number>(), accounts = ref<AccountItem[]>([])
const linkFailures = ref<{ id: number; reason: string }[]>([])
async function importGroups() {
  let items: { group_jid: string; group_name: string; source_channel?: string; owner_account_id?: number }[]
  try {
    items = importText.value.trim().startsWith('[') ? JSON.parse(importText.value) : importText.value.split(/\r?\n/).filter(line => line.trim()).map(line => { const [group_jid, ...name] = line.split(/[,，\t]/); return { group_jid: group_jid!.trim(), group_name: name.join(',').trim() } })
    if (!Array.isArray(items) || !items.length) throw new Error()
  } catch { ElMessage.error('导入格式不正确'); return }
  importing.value = true
  try { const result = await groupApi.import(items.map(item => ({ ...item, source_channel: item.source_channel || importSource.value, ...(item.owner_account_id || importAccount.value ? { owner_account_id: item.owner_account_id || importAccount.value } : {}) }))); ElMessage.success(`新增 ${result.added} 个，更新 ${result.updated} 个`); importVisible.value = false; importText.value = ''; reload(); emit('changed') } finally { importing.value = false }
}
async function exportGroups() {
  const result = await groupApi.export({ keyword: filters.keyword || undefined, status: filters.status || undefined })
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = '资源群.json'; anchor.click(); URL.revokeObjectURL(url)
}
async function removeGroups() {
  try { await ElMessageBox.confirm(`确认删除 ${selectedIds.value.length} 个资源群？`, '删除资源群', { type: 'warning' }) } catch { return }
  const result = await groupApi.remove(selectedIds.value); ElMessage.success(`已删除 ${result.count} 个`); selectedIds.value = []; reload(); emit('changed')
}

function onSelectionChange(rows: GroupRow[]) {
  selectedIds.value = rows.map((r) => r.id)
}

async function fetchLinks() {
  if (!selectedIds.value.length) return
  fetching.value = true
  try {
    const res = await groupApi.fetchLinks(selectedIds.value)
    linkFailures.value = res.failures || []
    if (res.failures?.length) ElMessage.warning(res.message)
    else ElMessage.success(res.message)
    await load()
  } finally {
    fetching.value = false
  }
}

function scoreColor(score: number) {
  if (score >= 80) return '#303030'
  if (score >= 60) return '#737373'
  if (score >= 40) return '#a16207'
  return '#b42318'
}

async function load() {
  loading.value = true
  try {
    const res = await groupApi.list({
      page: page.value,
      size: size.value,
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
    })
    rows.value = res.list
    total.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onSizeChange() {
  page.value = 1
  load()
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  reload()
}


onActivated(async () => { load(); accounts.value = await accountApi.list(); emit('changed') })
</script>


