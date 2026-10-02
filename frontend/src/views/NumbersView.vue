<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>号码池管理</h2>
        <div class="sub">批量导入 · 号码状态 · 来源类型</div>
      </div>
      <div class="actions">
        <el-button type="primary" :icon="Upload" @click="importVisible = true">批量导入号码</el-button>
        <el-button :icon="Download" :loading="exporting" @click="exportNumbers">导出号码</el-button>
        <el-button
          type="danger"
          plain
          :icon="Delete"
          :disabled="selectedIds.length === 0"
          @click="batchDelete"
        >
          批量删除{{ selectedIds.length ? `(${selectedIds.length})` : '' }}
        </el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索号码"
        style="width: 200px"
        :prefix-icon="Search"
        clearable
        @keyup.enter="reload"
      />
      <el-select v-model="filters.status" placeholder="号码状态" style="width: 140px" clearable>
        <el-option
          v-for="(label, key) in NUMBER_STATUS_LABEL"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-select v-model="filters.source_type" placeholder="来源类型" style="width: 150px" clearable>
        <el-option label="实体卡" value="physical" />
        <el-option label="虚拟号" value="virtual" />
        <el-option label="接码平台" value="sms_platform" />
      </el-select>
      <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="phone_number" label="号码" min-width="150" />
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ NUMBER_SOURCE_LABEL[row.source_type] || row.source_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source_channel" label="来源渠道" min-width="110" />
        <el-table-column prop="number_segment" label="号段" width="100" />
        <el-table-column prop="region" label="地区" width="80" />
        <el-table-column prop="trust_score" label="信任分" width="90" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ NUMBER_STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="account_id" label="账号 ID" width="90" />
        <el-table-column label="注册时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.register_time) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无号码，点击右上角「批量导入号码」" />
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

    <!-- 批量导入 -->
    <el-dialog v-model="importVisible" title="批量导入号码" width="640px" @closed="resetImport">
      <el-form label-width="90px">
        <el-form-item label="来源类型">
          <el-radio-group v-model="importForm.source_type">
            <el-radio-button value="physical">实体卡</el-radio-button>
            <el-radio-button value="virtual">虚拟号</el-radio-button>
            <el-radio-button value="sms_platform">接码平台</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="来源渠道">
          <el-input v-model="importForm.source_channel" placeholder="如 卡商A / 平台B（可选）" />
        </el-form-item>
        <el-form-item label="号码列表">
          <el-input
            v-model="importForm.text"
            type="textarea"
            :rows="7"
            placeholder="每行一个号码，或用逗号 / 空格分隔，例如：&#10;8613800000001&#10;8613800000002"
          />
          <div class="import-hint">
            <span>已解析 <b>{{ parsedPhones.length }}</b> 个号码</span>
            <el-tag v-if="duplicated" type="warning" size="small" effect="plain">
              去重后 {{ uniquePhones.length }} 个
            </el-tag>
          </div>
        </el-form-item>
        <el-form-item label="或上传文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".txt,.csv"
            :on-change="onFileChange"
          >
            <el-button :icon="Document">选择 txt / csv 文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="importing"
          :disabled="uniquePhones.length === 0"
          @click="submitImport"
        >
          导入 {{ uniquePhones.length }} 个号码
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { Upload, Download, Delete, Search, Document } from '@element-plus/icons-vue'
import { numberApi } from '@/api'
import type { NumberImportItem, NumberRow } from '@/types/api'
import {
  NUMBER_SOURCE_LABEL,
  NUMBER_STATUS_LABEL,
  formatDateTime,
  parsePhoneList,
  statusTagType,
} from '@/utils/format'

const loading = ref(false)
const rows = ref<NumberRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const filters = reactive({ keyword: '', status: '', source_type: '' })

const selectedIds = ref<number[]>([])
const exporting = ref(false)

function onSelectionChange(rows: NumberRow[]) {
  selectedIds.value = rows.map((r) => r.id)
}

async function batchDelete() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个号码？`, '批量删除', {
      type: 'warning',
    })
  } catch {
    return
  }
  const res = await numberApi.remove(selectedIds.value)
  ElMessage.success(`已删除 ${res.count} 个号码`)
  selectedIds.value = []
  await load()
}

async function exportNumbers() {
  exporting.value = true
  try {
    const list = await numberApi.export()
    const header = ['ID', '号码', '来源', '来源渠道', '号段', '地区', '信任分', '状态', '创建时间']
    const lines = [header.join(',')]
    for (const r of list) {
      lines.push(
        [
          r.id,
          r.phone,
          NUMBER_SOURCE_LABEL[r.source_type] || r.source_type,
          r.source_channel ?? '',
          r.number_segment ?? '',
          r.region ?? '',
          r.trust_score,
          NUMBER_STATUS_LABEL[r.status] || r.status,
          r.created_at ?? '',
        ]
          .map((v) => `"${String(v).replace(/"/g, '""')}"`)
          .join(','),
      )
    }
    const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `numbers_${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${list.length} 条`)
  } finally {
    exporting.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const res = await numberApi.list({
      page: page.value,
      size: size.value,
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
      source_type: filters.source_type || undefined,
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
  filters.source_type = ''
  reload()
}

// ---------- 导入 ----------
const importVisible = ref(false)
const importing = ref(false)
const importForm = reactive({ source_type: 'physical', source_channel: '', text: '' })

const parsedPhones = computed(() => parsePhoneList(importForm.text))
const uniquePhones = computed(() => Array.from(new Set(parsedPhones.value)))
const duplicated = computed(() => uniquePhones.value.length !== parsedPhones.value.length)

function resetImport() {
  importForm.text = ''
  importForm.source_channel = ''
  importForm.source_type = 'physical'
}

function onFileChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  const reader = new FileReader()
  reader.onload = () => {
    const content = String(reader.result || '')
    const next = parsePhoneList(content)
    importForm.text = importForm.text ? `${importForm.text}\n${next.join('\n')}` : next.join('\n')
    ElMessage.success(`已从文件读取 ${next.length} 行`)
  }
  reader.readAsText(raw)
}

async function submitImport() {
  const items: NumberImportItem[] = uniquePhones.value.map((phone) => ({
    phone,
    source_type: importForm.source_type,
    source_channel: importForm.source_channel,
  }))
  importing.value = true
  try {
    const res = await numberApi.import(items)
    ElMessage.success(`导入完成：成功 ${res.imported} 个，失败 ${res.failed} 个（重复号码记为失败）`)
    importVisible.value = false
    reload()
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.import-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: 13px;
  color: #909399;
}
</style>
