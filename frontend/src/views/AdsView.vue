<template>
  <PageTemplate kind="list">
    <div class="page-header">
      <div>
        <h2>广告消息</h2>
        <div class="sub">多语言文案 · 超链管理 · 效果统计</div>
      </div>
      <div class="actions">
        <el-button v-if="activeTab === 'copy'" type="primary" :icon="Plus" @click="openCopyDialog()">新建文案</el-button>
        <el-button v-else-if="activeTab === 'link'" type="primary" :icon="Plus" @click="openLinkDialog()">新建超链</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <!-- ==================== 文案列表 ==================== -->
      <el-tab-pane label="文案列表" name="copy">


        <el-card shadow="never">
          <div class="filter-bar">
            <el-select v-model="copyFilters.language" placeholder="语言" style="width: 140px" clearable>
              <el-option
                v-for="(label, key) in AD_LANGUAGE_LABEL"
                :key="key"
                :label="label"
                :value="key"
              />
            </el-select>
            <el-select v-model="copyFilters.status" placeholder="状态" style="width: 140px" clearable>
              <el-option v-for="(label, key) in AD_STATUS_LABEL" :key="key" :label="label" :value="key" />
            </el-select>
            <el-input
              v-model="copyFilters.keyword"
              placeholder="搜索标题 / 内容"
              style="width: 220px"
              :prefix-icon="Search"
              clearable
              @keyup.enter="reloadCopies"
            />
            <el-button :icon="Search" @click="reloadCopies">查询</el-button>
            <el-button @click="resetCopyFilters">重置</el-button>
          </div>
          <el-table v-loading="copyLoading" :data="copies" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
            <el-table-column label="语言" width="100">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">
                  {{ AD_LANGUAGE_LABEL[row.language] || row.language }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="变量" min-width="150">
              <template #default="{ row }">
                <template v-if="row.variables && row.variables.length">
                  <el-tag
                    v-for="name in row.variables"
                    :key="name"
                    class="var-tag"
                    size="small"
                    type="info"
                    effect="plain"
                  >
                    {{ varLabel(name) }}
                  </el-tag>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="content" label="内容" min-width="220" show-overflow-tooltip />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ AD_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="sent" label="发送" width="80" />
            <el-table-column prop="delivered" label="送达" width="80" />
            <el-table-column prop="read" label="阅读" width="80" />
            <el-table-column prop="click" label="点击" width="80" />
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :icon="Edit" @click="openCopyDialog(row)">编辑</el-button>
                <el-button link type="danger" :icon="Delete" @click="removeCopy(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无文案，点击「新建文案」创建" />
            </template>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="copyPage"
              v-model:page-size="copySize"
              :page-sizes="[10, 20, 50]"
              :total="copyTotal"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadCopies"
              @size-change="onCopySizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 超链管理 ==================== -->
      <el-tab-pane label="超链管理" name="link">


        <el-card shadow="never">
        <div class="filter-bar">
          <el-input
            v-model="linkFilters.keyword"
            placeholder="搜索名称 / 原始链接 / 短码"
            style="width: 240px"
            :prefix-icon="Search"
            clearable
            @keyup.enter="reloadLinks"
          />
          <el-select v-model="linkFilters.status" placeholder="状态" style="width: 140px" clearable>
            <el-option v-for="(label, key) in AD_STATUS_LABEL" :key="key" :label="label" :value="key" />
          </el-select>
          <el-button :icon="Search" @click="reloadLinks">查询</el-button>
          <el-button @click="resetLinkFilters">重置</el-button>
        </div>
          <el-table v-loading="linkLoading" :data="links" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
            <el-table-column label="短链" min-width="260">
              <template #default="{ row }">
                <div class="short-link">
                  <el-link type="primary" :href="row.short_url" target="_blank" :underline="false">
                    {{ row.short_url }}
                  </el-link>
                  <el-button link type="primary" :icon="CopyDocument" @click="copyText(row.short_url)">
                    复制
                  </el-button>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="original_url" label="原始链接" min-width="200" show-overflow-tooltip />
            <el-table-column label="伪装域名" width="130">
              <template #default="{ row }">
                <span :class="{ muted: !row.domain }">{{ row.domain || '默认' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="追踪参数" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.tracking_params" class="mono">{{ row.tracking_params }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="关联文案" width="110">
              <template #default="{ row }">{{ row.ad_message_id ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="click_count" label="点击量" width="90" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ AD_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :icon="Edit" @click="openLinkDialog(row)">编辑</el-button>
                <el-button link type="danger" :icon="Delete" @click="removeLink(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无超链，点击「新建超链」生成" />
            </template>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="linkPage"
              v-model:page-size="linkSize"
              :page-sizes="[10, 20, 50]"
              :total="linkTotal"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadLinks"
              @size-change="onLinkSizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 效果统计 ==================== -->
      <el-tab-pane label="效果统计" name="stats">
        <div class="filter-bar">
          <el-button :icon="Refresh" :loading="statsLoading" @click="loadStats">刷新</el-button>
          <span class="muted">统计全部文案的累计发送 / 送达 / 阅读 / 点击，比率按发送量计算。</span>
        </div>

          <div class="stat-grid">
            <div v-for="card in statCards" :key="card.label">
              <div class="stat-card">
                <div class="label">{{ card.label }}</div>
                <div class="value" :style="{ color: card.color }">{{ card.value }}</div>
                <div class="hint">{{ card.hint }}</div>
              </div>
          </div>
        </div>

        <el-card shadow="never" class="section-gap">
          <template #header>
            <div class="card-header">
              <span>分文案效果</span>
              <span class="muted">{{ statsRows.length }} 条</span>
            </div>
          </template>
          <el-table v-loading="statsLoading" :data="statsRows" stripe>
            <el-table-column prop="title" label="文案标题" min-width="180" show-overflow-tooltip />
            <el-table-column label="语言" width="100">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">
                  {{ AD_LANGUAGE_LABEL[row.language] || row.language }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ AD_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="sent" label="发送" width="90" />
            <el-table-column prop="delivered" label="送达" width="90" />
            <el-table-column prop="read" label="阅读" width="90" />
            <el-table-column prop="click" label="点击" width="90" />
            <el-table-column label="送达率" width="100">
              <template #default="{ row }">
                {{ rateText(row.delivery_rate) }}
              </template>
            </el-table-column>
            <el-table-column label="阅读率" width="100">
              <template #default="{ row }">{{ rateText(row.read_rate) }}</template>
            </el-table-column>
            <el-table-column label="点击率" width="100">
              <template #default="{ row }">{{ rateText(row.click_rate) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无统计数据，文案被发送后这里会显示送达 / 阅读 / 点击漏斗" />
            </template>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ==================== 文案 新建 / 编辑 ==================== -->
    <el-dialog
      v-model="copyDialogVisible"
      :title="editingCopyId === null ? '新建文案' : `编辑文案 #${editingCopyId}`"
      width="680px"
    >
      <el-form label-width="92px">
        <el-form-item label="标题">
          <el-input v-model="copyForm.title" placeholder="例如：拉美市场首触达" maxlength="120" />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="copyForm.language" style="width: 100%">
            <el-option
              v-for="(label, key) in AD_LANGUAGE_LABEL"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="文案内容">
          <el-input
            v-model="copyForm.content"
            type="textarea"
            :rows="6"
            placeholder="Hi {name}，点击了解详情：{link}"
          />
          <div class="form-hint">支持 {name}、{link} 等变量，保存后自动提取</div>
        </el-form-item>
        <el-form-item label="变量">
          <template v-if="copyVariables.length">
            <el-tag
              v-for="name in copyVariables"
              :key="name"
              class="var-tag"
              size="small"
              type="info"
              effect="plain"
            >
              {{ varLabel(name) }}
            </el-tag>
          </template>
          <span v-else class="muted">未检测到变量</span>
        </el-form-item>
        <el-form-item label="关联链接">
          <el-input v-model="copyForm.link_url" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="分组/场景">
          <el-input v-model="copyForm.category" placeholder="例如：拉美 - 首触达" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="copyForm.status" style="width: 100%">
            <el-option
              v-for="(label, key) in AD_STATUS_LABEL"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="预览">
          <div class="preview-box">{{ previewContent || '（请输入文案内容）' }}</div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="copyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="copySubmitting" @click="submitCopy">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 超链 新建 / 编辑 ==================== -->
    <el-dialog
      v-model="linkDialogVisible"
      :title="editingLinkId === null ? '新建超链' : `编辑超链 #${editingLinkId}`"
      width="620px"
    >
      <el-form label-width="92px">
        <el-form-item label="名称">
          <el-input v-model="linkForm.name" placeholder="例如：拉美首触达短链" maxlength="120" />
        </el-form-item>
        <el-form-item label="原始链接">
          <el-input v-model="linkForm.original_url" placeholder="https://example.com/landing" />
        </el-form-item>
        <el-form-item label="伪装域名">
          <el-input v-model="linkForm.domain" :placeholder="domainPlaceholder" />
        </el-form-item>
        <el-form-item label="追踪参数">
          <el-input v-model="linkForm.tracking_params" placeholder="utm_source=wa&click_id={click_id}" />
        </el-form-item>
        <el-form-item label="关联文案">
          <el-select
            v-model="linkForm.ad_message_id"
            placeholder="不关联文案"
            style="width: 100%"
            clearable
            filterable
          >
            <el-option
              v-for="item in copyOptions"
              :key="item.id"
              :label="`#${item.id} ${item.title}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="linkForm.status">
            <el-radio-button value="active">启用</el-radio-button>
            <el-radio-button value="paused">停用</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="linkDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="linkSubmitting" @click="submitLink">保存</el-button>
      </template>
    </el-dialog>
  </PageTemplate>
</template>

<script setup lang="ts">
import PageTemplate from '@/components/PageTemplate.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Plus, Search, Edit, Delete, CopyDocument, Refresh } from '@element-plus/icons-vue'
import { adApi } from '@/api'
import type {
  AdCopyRow,
  AdCopySaveReq,
  AdLinkRow,
  AdLinkSaveReq,
  AdStatsResult,
} from '@/types/api'
import {
  AD_LANGUAGE_LABEL,
  AD_STATUS_LABEL,
  formatDateTime,
  statusTagType,
} from '@/utils/format'

/** 文案变量正则：{name} / {link} / {city} ... */
const VARIABLE_RE = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g

const activeTab = ref('copy')

function aiNotReady() {
  ElMessage.info('AI 生成 / 改写文案需要接入大模型服务，已列为待接入。')
}

function varLabel(name: string) {
  return `{${name}}`
}

/** 后端统一返回 0-100 的比率数值（送达/发送、阅读/送达、点击/阅读） */
function rateText(rate: number | null | undefined): string {
  const value = typeof rate === 'number' && Number.isFinite(rate) ? rate : 0
  return `${value.toFixed(1)}%`
}

// ---------------------------------------------------------------- 文案列表
const copyLoading = ref(false)
const copies = ref<AdCopyRow[]>([])
const copyTotal = ref(0)
const copyPage = ref(1)
const copySize = ref(20)
const copyFilters = reactive({ language: '', status: '', keyword: '' })

async function loadCopies() {
  copyLoading.value = true
  try {
    const res = await adApi.listCopies({
      page: copyPage.value,
      size: copySize.value,
      language: copyFilters.language || undefined,
      status: copyFilters.status || undefined,
      keyword: copyFilters.keyword || undefined,
    })
    copies.value = res.list
    copyTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    copyLoading.value = false
  }
}

function reloadCopies() {
  copyPage.value = 1
  loadCopies()
}

function onCopySizeChange() {
  copyPage.value = 1
  loadCopies()
}

function resetCopyFilters() {
  copyFilters.language = ''
  copyFilters.status = ''
  copyFilters.keyword = ''
  reloadCopies()
}

// ---------------------------------------------------------------- 文案 新建 / 编辑
const copyDialogVisible = ref(false)
const copySubmitting = ref(false)
const editingCopyId = ref<number | null>(null)
const editingCopyRow = ref<AdCopyRow | null>(null)
const copyForm = reactive({
  title: '',
  language: 'zh',
  content: '',
  link_url: '',
  category: '',
  status: 'active',
})

/** 实时从文案内容中提取变量名（去重） */
const copyVariables = computed(() => {
  const matched = copyForm.content.match(VARIABLE_RE) ?? []
  return Array.from(new Set(matched.map((item) => item.replace(/[{}]/g, ''))))
})

/** 预览：{name} -> 张三，{link} -> 关联链接或示例短链 */
const previewContent = computed(() =>
  copyForm.content
    .replace(/\{name\}/g, '张三')
    .replace(/\{link\}/g, copyForm.link_url || 'https://go.wa-link.com/demo'),
)

function openCopyDialog(row?: AdCopyRow) {
  editingCopyId.value = row ? row.id : null
  editingCopyRow.value = row ?? null
  if (row) {
    copyForm.title = row.title
    copyForm.language = row.language
    copyForm.content = row.content
    copyForm.link_url = row.link_url ?? ''
    copyForm.category = row.category ?? ''
    copyForm.status = row.status
  } else {
    copyForm.title = ''
    copyForm.language = 'zh'
    copyForm.content = ''
    copyForm.link_url = ''
    copyForm.category = ''
    copyForm.status = 'active'
  }
  copyDialogVisible.value = true
}

async function submitCopy() {
  if (!copyForm.title.trim()) {
    ElMessage.warning('请填写文案标题')
    return
  }
  if (!copyForm.content.trim()) {
    ElMessage.warning('请填写文案内容')
    return
  }
  copySubmitting.value = true
  try {
    if (editingCopyId.value === null) {
      await adApi.createCopy({
        title: copyForm.title.trim(),
        content: copyForm.content,
        language: copyForm.language,
        link_url: copyForm.link_url,
        category: copyForm.category,
        status: copyForm.status,
      })
      ElMessage.success('文案已创建')
    } else {
      // 仅提交发生变化的字段
      const payload: Partial<AdCopySaveReq> = {}
      const origin = editingCopyRow.value
      if (origin) {
        if (copyForm.title !== origin.title) payload.title = copyForm.title
        if (copyForm.content !== origin.content) payload.content = copyForm.content
        if (copyForm.language !== origin.language) payload.language = copyForm.language
        if (copyForm.link_url !== (origin.link_url ?? '')) payload.link_url = copyForm.link_url
        if (copyForm.category !== (origin.category ?? '')) payload.category = copyForm.category
        if (copyForm.status !== origin.status) payload.status = copyForm.status
      }
      if (Object.keys(payload).length === 0) {
        ElMessage.info('内容没有变化，无需保存')
        return
      }
      await adApi.updateCopy(editingCopyId.value, payload)
      ElMessage.success('文案已更新')
    }
    copyDialogVisible.value = false
    await loadCopies()
  } catch {
    /* 拦截器已提示 */
  } finally {
    copySubmitting.value = false
  }
}

async function removeCopy(row: AdCopyRow) {
  try {
    await ElMessageBox.confirm(`确认删除文案「${row.title}」？删除后不可恢复。`, '删除文案', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await adApi.removeCopy(row.id)
    ElMessage.success('文案已删除')
    await loadCopies()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------------------------------------------------------------- 超链列表
const linkLoading = ref(false)
const links = ref<AdLinkRow[]>([])
const linkTotal = ref(0)
const linkPage = ref(1)
const linkSize = ref(20)
const linkFilters = reactive({ keyword: '', status: '' })
const defaultDomain = ref('')

async function loadLinks() {
  linkLoading.value = true
  try {
    const res = await adApi.listLinks({
      page: linkPage.value,
      size: linkSize.value,
      status: linkFilters.status || undefined,
      keyword: linkFilters.keyword || undefined,
    })
    links.value = res.list
    linkTotal.value = res.total
    defaultDomain.value = res.default_domain
  } catch {
    /* 拦截器已提示 */
  } finally {
    linkLoading.value = false
  }
}

function reloadLinks() {
  linkPage.value = 1
  loadLinks()
}

function onLinkSizeChange() {
  linkPage.value = 1
  loadLinks()
}

function resetLinkFilters() {
  linkFilters.keyword = ''
  linkFilters.status = ''
  reloadLinks()
}

async function copyText(text: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

// ---------------------------------------------------------------- 超链 新建 / 编辑
const linkDialogVisible = ref(false)
const linkSubmitting = ref(false)
const editingLinkId = ref<number | null>(null)
const editingLinkRow = ref<AdLinkRow | null>(null)
const linkForm = reactive({
  name: '',
  original_url: '',
  domain: '',
  tracking_params: '',
  ad_message_id: null as number | null,
  status: 'active',
})

const domainPlaceholder = computed(() =>
  defaultDomain.value ? `留空使用默认域名 ${defaultDomain.value}` : '留空使用默认域名',
)

/** 关联文案下拉：首次打开超链弹窗时懒加载 */
const copyOptions = ref<AdCopyRow[]>([])
const copyOptionsLoaded = ref(false)

async function loadCopyOptions() {
  if (copyOptionsLoaded.value) return
  try {
    const res = await adApi.listCopies({ page: 1, size: 200 })
    copyOptions.value = res.list
    copyOptionsLoaded.value = true
  } catch {
    /* 拦截器已提示 */
  }
}

function openLinkDialog(row?: AdLinkRow) {
  editingLinkId.value = row ? row.id : null
  editingLinkRow.value = row ?? null
  if (row) {
    linkForm.name = row.name
    linkForm.original_url = row.original_url
    linkForm.domain = row.domain ?? ''
    linkForm.tracking_params = row.tracking_params ?? ''
    linkForm.ad_message_id = row.ad_message_id ?? null
    linkForm.status = row.status || 'active'
  } else {
    linkForm.name = ''
    linkForm.original_url = ''
    linkForm.domain = ''
    linkForm.tracking_params = ''
    linkForm.ad_message_id = null
    linkForm.status = 'active'
  }
  linkDialogVisible.value = true
  loadCopyOptions()
}

async function submitLink() {
  const url = linkForm.original_url.trim()
  if (!linkForm.name.trim()) {
    ElMessage.warning('请填写超链名称')
    return
  }
  if (!url) {
    ElMessage.warning('请填写原始链接')
    return
  }
  if (!/^https?:\/\//i.test(url)) {
    ElMessage.error('原始链接必须以 http:// 或 https:// 开头')
    return
  }
  const adMessageId = typeof linkForm.ad_message_id === 'number' ? linkForm.ad_message_id : null
  linkSubmitting.value = true
  try {
    if (editingLinkId.value === null) {
      await adApi.createLink({
        name: linkForm.name.trim(),
        original_url: url,
        domain: linkForm.domain.trim(),
        tracking_params: linkForm.tracking_params.trim(),
        ad_message_id: adMessageId,
        status: linkForm.status,
      })
      ElMessage.success('超链已创建')
    } else {
      // 仅提交发生变化的字段
      const payload: Partial<AdLinkSaveReq> = {}
      const origin = editingLinkRow.value
      if (origin) {
        if (linkForm.name !== origin.name) payload.name = linkForm.name
        if (url !== origin.original_url) payload.original_url = url
        if (linkForm.domain !== (origin.domain ?? '')) payload.domain = linkForm.domain
        if (linkForm.tracking_params !== (origin.tracking_params ?? '')) {
          payload.tracking_params = linkForm.tracking_params
        }
        if (adMessageId !== (origin.ad_message_id ?? null)) payload.ad_message_id = adMessageId
        if (linkForm.status !== origin.status) payload.status = linkForm.status
      }
      if (Object.keys(payload).length === 0) {
        ElMessage.info('内容没有变化，无需保存')
        return
      }
      await adApi.updateLink(editingLinkId.value, payload)
      ElMessage.success('超链已更新')
    }
    linkDialogVisible.value = false
    await loadLinks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    linkSubmitting.value = false
  }
}

async function removeLink(row: AdLinkRow) {
  try {
    await ElMessageBox.confirm(`确认删除超链「${row.name}」？删除后短链将立即失效。`, '删除超链', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await adApi.removeLink(row.id)
    ElMessage.success('超链已删除')
    await loadLinks()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------------------------------------------------------------- 效果统计
const statsLoading = ref(false)
const statsLoaded = ref(false)
const stats = ref<AdStatsResult | null>(null)

type StatTotals = AdStatsResult['totals']

const EMPTY_TOTALS: StatTotals = {
  copies: 0,
  sent: 0,
  delivered: 0,
  read: 0,
  click: 0,
  delivery_rate: 0,
  read_rate: 0,
  click_rate: 0,
}

const statTotals = computed<StatTotals>(() => stats.value?.totals ?? EMPTY_TOTALS)
const statsRows = computed(() => stats.value?.list ?? [])

const statCards = computed(() => [
  {
    label: '文案数',
    value: String(statTotals.value.copies),
    hint: '已创建文案',
    color: '#303030',
  },
  {
    label: '发送',
    value: String(statTotals.value.sent),
    hint: '累计发送',
    color: '#737373',
  },
  {
    label: '送达',
    value: String(statTotals.value.delivered),
    hint: `送达率 ${rateText(statTotals.value.delivery_rate)}`,
    color: '#303030',
  },
  {
    label: '阅读',
    value: String(statTotals.value.read),
    hint: `阅读率 ${rateText(statTotals.value.read_rate)}`,
    color: '#a16207',
  },
  {
    label: '点击',
    value: String(statTotals.value.click),
    hint: `点击率 ${rateText(statTotals.value.click_rate)}`,
    color: '#737373',
  },
  {
    label: '送达率',
    value: rateText(statTotals.value.delivery_rate),
    hint: '送达 / 发送',
    color: '#303030',
  },
  {
    label: '阅读率',
    value: rateText(statTotals.value.read_rate),
    hint: '阅读 / 送达',
    color: '#a16207',
  },
  {
    label: '点击率',
    value: rateText(statTotals.value.click_rate),
    hint: '点击 / 阅读',
    color: '#737373',
  },
])

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await adApi.stats()
    statsLoaded.value = true
  } catch {
    /* 拦截器已提示 */
  } finally {
    statsLoading.value = false
  }
}

// 首次切到「效果统计」时再拉取数据
watch(activeTab, (tab) => {
  if (tab === 'stats' && !statsLoaded.value) loadStats()
})

onMounted(() => {
  loadCopies()
  loadLinks()
})
</script>

<style scoped>
.var-tag {
  margin: 0 4px 4px 0;
}

.form-hint {
  font-size: 12px;
  color: #737373;
  line-height: 1.6;
  margin-top: 4px;
}

.preview-box {
  width: 100%;
  min-height: 64px;
  padding: 10px 12px;
  border: 1px dashed var(--wa-border);
  border-radius: 4px;
  background: #fafafa;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.short-link {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.short-link .el-link {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
