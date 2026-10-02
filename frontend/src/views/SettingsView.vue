<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>系统设置</h2>
        <div class="sub">全局参数 · 用户 / 租户 / 权限（管理员）</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="全局参数" name="params">
        <el-card shadow="never" v-loading="loading">
          <el-alert
            v-if="!isAdmin"
            class="section-gap"
            type="warning"
            :closable="false"
            show-icon
            title="当前账号不是管理员，只能查看全局参数。"
          />
          <el-alert
            v-else-if="dirty"
            class="section-gap"
            type="info"
            :closable="false"
            show-icon
            title="参数已修改但尚未保存，保存后立即对发送策略与充值下单生效。"
          />

          <el-form label-width="200px" class="param-form" @submit.prevent>
            <template v-for="group in groups" :key="group.category">
              <div class="group-title">{{ group.label }}</div>
              <el-form-item v-for="field in group.items" :key="field.key" :label="field.label">
                <el-input-number
                  v-if="field.type === 'int' || field.type === 'float'"
                  v-model="form[field.key]"
                  :min="field.min ?? undefined"
                  :max="field.max ?? undefined"
                  :precision="field.type === 'float' ? 2 : 0"
                  :disabled="!isAdmin"
                />
                <el-switch v-else-if="field.type === 'bool'" v-model="form[field.key]" :disabled="!isAdmin" />
                <el-input
                  v-else
                  v-model="form[field.key]"
                  :maxlength="field.max_len || 255"
                  :disabled="!isAdmin"
                  class="text-input"
                  :placeholder="field.key === 'recharge_address' ? '例如 TRC20 收款地址' : ''"
                />
                <div class="field-hint">
                  {{ field.description }}
                  <span class="muted"> · 默认值 {{ field.default === '' ? '（空）' : field.default }}</span>
                </div>
              </el-form-item>
            </template>
          </el-form>

          <div class="form-actions">
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!isAdmin || !dirty"
              @click="saveSettings"
            >
              保存
            </el-button>
            <el-button :disabled="!dirty" @click="resetForm">重置</el-button>
            <span v-if="savedAt" class="muted saved-at">最近保存：{{ formatDateTime(savedAt) }}</span>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="用户管理" name="users">
        <el-card shadow="never">
          <el-alert
            v-if="!isAdmin"
            class="section-gap"
            type="warning"
            :closable="false"
            show-icon
            title="用户管理仅管理员可见（GET/POST/PUT/DELETE /api/v1/admin/users）。"
          />
          <template v-else>
            <div class="filter-bar">
              <el-input
                v-model="userFilters.keyword"
                placeholder="搜索用户名 / 昵称"
                style="width: 200px"
                :prefix-icon="Search"
                clearable
                @keyup.enter="reloadUsers"
              />
              <el-select v-model="userFilters.role" placeholder="角色" style="width: 160px" clearable>
                <el-option
                  v-for="(label, key) in USER_ROLE_LABEL"
                  :key="key"
                  :label="label"
                  :value="key"
                />
              </el-select>
              <el-select v-model="userFilters.status" placeholder="状态" style="width: 130px" clearable>
                <el-option
                  v-for="(label, key) in USER_STATUS_LABEL"
                  :key="key"
                  :label="label"
                  :value="key"
                />
              </el-select>
              <el-button type="primary" :icon="Search" @click="reloadUsers">查询</el-button>
              <el-button @click="resetUserFilters">重置</el-button>
              <el-button type="primary" :icon="Plus" @click="openUserDialog()">新建用户</el-button>
            </div>

            <el-table v-loading="loadingUsers" :data="users" stripe>
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="username" label="用户名" min-width="130" />
              <el-table-column prop="nickname" label="昵称" min-width="120" />
              <el-table-column label="角色" width="140">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ roleLabel(row.role) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="tenant" label="租户" width="110" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row.status)" size="small">
                    {{ USER_STATUS_LABEL[row.status] || row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="最后登录" width="170">
                <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
              </el-table-column>
              <el-table-column label="创建时间" width="170">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="140" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openUserDialog(row)">编辑</el-button>
                  <el-button
                    link
                    type="danger"
                    :disabled="row.username === auth.user?.username"
                    @click="removeUser(row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="暂无用户" />
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="userPage"
                v-model:page-size="userSize"
                :page-sizes="[10, 20, 50]"
                :total="userTotal"
                layout="total, sizes, prev, pager, next"
                background
                @current-change="loadUsers"
                @size-change="onUserSizeChange"
              />
            </div>
          </template>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="租户管理" name="tenants">
        <el-card shadow="never">
          <PlaceholderPanel description="租户管理待接入后端接口" api="/api/v1/admin/tenants" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="权限配置" name="perms">
        <el-card shadow="never">
          <PlaceholderPanel
            description="权限配置待接入后端接口"
            api="/api/v1/admin/permissions（角色 - 权限映射）"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建 / 编辑用户 -->
    <el-dialog
      v-model="userDialogVisible"
      :title="userForm.id ? '编辑用户' : '新建用户'"
      width="520px"
    >
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" :disabled="!!userForm.id" placeholder="字母 / 数字 / 下划线" />
        </el-form-item>
        <el-form-item :label="userForm.id ? '重置密码' : '密码'">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="userForm.id ? '留空表示不修改' : '至少 6 位'"
          />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="userForm.nickname" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role" style="width: 100%">
            <el-option
              v-for="(label, key) in USER_ROLE_LABEL"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="租户">
          <el-input v-model="userForm.tenant" placeholder="默认 default" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="userForm.email" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="userForm.phone" />
        </el-form-item>
        <el-form-item v-if="userForm.id" label="状态">
          <el-radio-group v-model="userForm.status">
            <el-radio-button value="active">正常</el-radio-button>
            <el-radio-button value="disabled">禁用</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingUser" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Plus } from '@element-plus/icons-vue'
import { adminApi, settingsApi } from '@/api'
import type { MeInfo, SettingField } from '@/types/api'
import { useAuthStore } from '@/stores/auth'
import {
  USER_ROLE_LABEL,
  USER_STATUS_LABEL,
  formatDateTime,
  statusTagType,
} from '@/utils/format'
import PlaceholderPanel from '@/components/PlaceholderPanel.vue'

const auth = useAuthStore()

const CATEGORY_LABEL: Record<string, string> = {
  send: '发送策略',
  billing: '计费与充值',
  general: '通用',
}

const activeTab = ref('params')
const loading = ref(false)
const saving = ref(false)
const savedAt = ref('')

const fields = ref<SettingField[]>([])
const form = ref<Record<string, any>>({})
const original = ref<Record<string, any>>({})

const isAdmin = computed(() => ['super_admin', 'agent_admin'].includes(auth.user?.role || ''))

const groups = computed(() => {
  const map = new Map<string, SettingField[]>()
  for (const field of fields.value) {
    if (!map.has(field.category)) map.set(field.category, [])
    map.get(field.category)!.push(field)
  }
  return Array.from(map, ([category, items]) => ({
    category,
    label: CATEGORY_LABEL[category] || category,
    items,
  }))
})

const dirty = computed(() =>
  fields.value.some((field) => form.value[field.key] !== original.value[field.key]),
)

function roleLabel(role?: string) {
  if (!role) return '-'
  return USER_ROLE_LABEL[role] || role
}

async function loadSettings() {
  loading.value = true
  try {
    const schema = await settingsApi.schema()
    fields.value = schema
    const next: Record<string, any> = {}
    for (const field of schema) {
      next[field.key] =
        field.type === 'bool'
          ? ['1', 'true', 'yes', 'on'].includes(String(field.value).toLowerCase())
          : field.value
    }
    form.value = next
    original.value = { ...next }
    savedAt.value = schema.reduce(
      (latest, field) => (field.updated_at && field.updated_at > latest ? field.updated_at : latest),
      '',
    )
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value = { ...original.value }
}

async function saveSettings() {
  const payload: Record<string, string | number> = {}
  for (const field of fields.value) {
    if (form.value[field.key] !== original.value[field.key]) {
      payload[field.key] = form.value[field.key]
    }
  }
  if (!Object.keys(payload).length) {
    ElMessage.info('没有需要保存的参数')
    return
  }
  saving.value = true
  try {
    const result = await settingsApi.update(payload)
    for (const field of fields.value) {
      if (field.key in result) field.value = result[field.key]
    }
    const next: Record<string, any> = {}
    for (const field of fields.value) next[field.key] = field.value
    form.value = next
    original.value = { ...next }
    savedAt.value = new Date().toISOString()
    ElMessage.success(`已保存 ${Object.keys(payload).length} 项全局参数`)
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 403) ElMessage.warning('当前账号没有修改全局参数的权限')
  } finally {
    saving.value = false
  }
}

// ---------- 用户管理 ----------
const users = ref<MeInfo[]>([])
const userTotal = ref(0)
const userPage = ref(1)
const userSize = ref(20)
const loadingUsers = ref(false)
const savingUser = ref(false)
const userDialogVisible = ref(false)
const userFilters = reactive({ keyword: '', role: '', status: '' })
const userForm = reactive({
  id: 0,
  username: '',
  password: '',
  nickname: '',
  email: '',
  phone: '',
  role: 'operator',
  tenant: 'default',
  status: 'active',
})

async function loadUsers() {
  if (!isAdmin.value) return
  loadingUsers.value = true
  try {
    const res = await adminApi.users({
      page: userPage.value,
      size: userSize.value,
      keyword: userFilters.keyword || undefined,
      role: userFilters.role || undefined,
      status: userFilters.status || undefined,
    })
    users.value = res.list
    userTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    loadingUsers.value = false
  }
}

function reloadUsers() {
  userPage.value = 1
  loadUsers()
}

function onUserSizeChange() {
  userPage.value = 1
  loadUsers()
}

function resetUserFilters() {
  userFilters.keyword = ''
  userFilters.role = ''
  userFilters.status = ''
  reloadUsers()
}

function openUserDialog(row?: MeInfo) {
  userForm.id = row?.id ?? 0
  userForm.username = row?.username ?? ''
  userForm.password = ''
  userForm.nickname = row?.nickname ?? ''
  userForm.email = row?.email ?? ''
  userForm.phone = row?.phone ?? ''
  userForm.role = row?.role ?? 'operator'
  userForm.tenant = row?.tenant ?? 'default'
  userForm.status = row?.status ?? 'active'
  userDialogVisible.value = true
}

async function submitUser() {
  if (!userForm.id) {
    if (!userForm.username.trim()) {
      ElMessage.error('请填写用户名')
      return
    }
    if (userForm.password.length < 6) {
      ElMessage.error('密码长度至少 6 位')
      return
    }
  } else if (userForm.password && userForm.password.length < 6) {
    ElMessage.error('密码长度至少 6 位')
    return
  }

  savingUser.value = true
  try {
    if (userForm.id) {
      const payload: Record<string, string> = {
        nickname: userForm.nickname,
        email: userForm.email,
        phone: userForm.phone,
        role: userForm.role,
        tenant: userForm.tenant,
        status: userForm.status,
      }
      if (userForm.password) payload.password = userForm.password
      await adminApi.updateUser(userForm.id, payload)
      ElMessage.success('用户已更新')
    } else {
      await adminApi.createUser({
        username: userForm.username.trim(),
        password: userForm.password,
        nickname: userForm.nickname,
        email: userForm.email,
        phone: userForm.phone,
        role: userForm.role,
        tenant: userForm.tenant,
      })
      ElMessage.success('用户已创建')
    }
    userDialogVisible.value = false
    loadUsers()
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingUser.value = false
  }
}

async function removeUser(row: MeInfo) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.username}」？该操作不可恢复。`, '删除用户', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await adminApi.removeUser(row.id)
    ElMessage.success('用户已删除')
    loadUsers()
  } catch {
    /* 拦截器已提示 */
  }
}

function loadAll() {
  loadSettings()
  if (activeTab.value === 'users') loadUsers()
}

watch(activeTab, (tab) => {
  if (tab === 'users' && !users.value.length) loadUsers()
})

onMounted(loadAll)
</script>

<style scoped>
.param-form {
  max-width: 640px;
}

.group-title {
  margin: 6px 0 14px;
  padding-left: 10px;
  border-left: 3px solid #25d366;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.field-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}

.text-input {
  max-width: 420px;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding-left: 200px;
}

.saved-at {
  font-size: 12px;
}

.filter-bar {
  margin-bottom: 14px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
