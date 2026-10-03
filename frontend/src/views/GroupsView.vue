<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>资源群管理</h2>
        <div class="sub">群列表 · 营销价值分排序 · 群链接</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>


    <el-card shadow="never">
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
      </div>
      <el-table v-loading="loading" :data="rows" stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="id" label="ID" width="70" />
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
          <el-empty description="暂无资源群，可先用「批量获取群链接」或从已加入的群里采集" />
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
    </el-card>

    <el-alert
      class="section-gap"
      type="info"
      :closable="false"
      show-icon
      title="群资源导入、导出、删除及更多筛选条件暂未开放。"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Link, Refresh, Search } from '@element-plus/icons-vue'
import { groupApi } from '@/api'
import type { GroupRow } from '@/types/api'

const loading = ref(false)
const rows = ref<GroupRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const filters = reactive({ keyword: '', status: '' })

const selectedIds = ref<number[]>([])
const fetching = ref(false)

function onSelectionChange(rows: GroupRow[]) {
  selectedIds.value = rows.map((r) => r.id)
}

async function fetchLinks() {
  if (!selectedIds.value.length) return
  fetching.value = true
  try {
    const res = await groupApi.fetchLinks(selectedIds.value)
    ElMessage.success(res.message || `已处理 ${selectedIds.value.length} 个群`)
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


onMounted(load)
</script>


