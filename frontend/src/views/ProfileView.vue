<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>个人中心</h2>
        <div class="sub">账号信息 · 修改密码 · 操作日志</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :md="10">
        <el-card shadow="never" v-loading="loading">
          <template #header>
            <div class="card-header">
              <span>账号信息</span>
              <el-button v-if="!editing" link type="primary" :icon="Edit" @click="startEdit">
                编辑资料
              </el-button>
            </div>
          </template>

          <el-form v-if="editing" label-width="90px" @submit.prevent>
            <el-form-item label="昵称">
              <el-input v-model="editForm.nickname" placeholder="用于界面展示" maxlength="64" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="editForm.email" placeholder="ops@example.com" />
            </el-form-item>
            <el-form-item label="手机号">
              <el-input v-model="editForm.phone" placeholder="选填" />
            </el-form-item>
            <div class="form-actions">
              <el-button type="primary" :loading="savingProfile" @click="submitProfile">保存</el-button>
              <el-button @click="editing = false">取消</el-button>
            </div>
          </el-form>

          <el-descriptions v-else :column="1" border>
            <el-descriptions-item label="用户名">{{ me.username || '-' }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ me.nickname || '-' }}</el-descriptions-item>
            <el-descriptions-item label="角色">
              <el-tag size="small" effect="plain">{{ roleLabel(me.role) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="当前租户">{{ me.tenant || '-' }}</el-descriptions-item>
            <el-descriptions-item label="邮箱">{{ me.email || '-' }}</el-descriptions-item>
            <el-descriptions-item label="手机号">{{ me.phone || '-' }}</el-descriptions-item>
            <el-descriptions-item label="账号状态">
              <el-tag :type="statusTagType(me.status || '')" size="small">
                {{ USER_STATUS_LABEL[me.status || ''] || me.status || '-' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="最后登录">
              {{ formatDateTime(me.last_login_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="登录次数">{{ me.login_count ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="注册时间">{{ formatDateTime(me.created_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <template #header>修改密码</template>
          <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px">
            <el-form-item label="当前密码" prop="old_password">
              <el-input v-model="pwdForm.old_password" type="password" show-password autocomplete="off" />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwdForm.new_password" type="password" show-password autocomplete="off" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input v-model="pwdForm.confirm_password" type="password" show-password autocomplete="off" />
            </el-form-item>
            <el-button type="primary" :loading="changingPassword" @click="submitPassword">
              提交
            </el-button>
            <div class="field-hint">修改成功后所有登录态会失效，需要使用新密码重新登录。</div>
          </el-form>
        </el-card>

      </el-col>
    </el-row>

    <el-card shadow="never" class="section-gap">
      <template #header>
        <div class="card-header">
          <span>操作日志</span>
          <span class="muted">时间 / 操作 / 对象 / 结果 / 详情</span>
        </div>
      </template>
      <el-table v-loading="loadingLogs" :data="logs" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            {{ OPERATION_ACTION_LABEL[row.action] || row.action }}
          </template>
        </el-table-column>
        <el-table-column prop="target" label="对象" min-width="160" show-overflow-tooltip />
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
              {{ OPERATION_RESULT_LABEL[row.result] || row.result }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
        <template #empty>
          <el-empty description="暂无操作日志，登录、改密、保存参数等操作都会记录在这里" />
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
          @current-change="loadLogs"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Refresh, Edit } from '@element-plus/icons-vue'
import { profileApi } from '@/api'
import type { MeInfo, OperationLogRow } from '@/types/api'
import { useAuthStore } from '@/stores/auth'
import {
  OPERATION_ACTION_LABEL,
  OPERATION_RESULT_LABEL,
  USER_ROLE_LABEL,
  USER_STATUS_LABEL,
  formatDateTime,
  statusTagType,
} from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()

const loading = ref(false)
const me = ref<Partial<MeInfo>>({})

const editing = ref(false)
const savingProfile = ref(false)
const editForm = reactive({ nickname: '', email: '', phone: '' })

const loadingLogs = ref(false)
const logs = ref<OperationLogRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)

const changingPassword = ref(false)
const pwdFormRef = ref<FormInstance>()
const pwdForm = reactive({ old_password: '', new_password: '', confirm_password: '' })

const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码长度至少 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== pwdForm.new_password) callback(new Error('两次输入的新密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

function roleLabel(role?: string) {
  if (!role) return '-'
  return USER_ROLE_LABEL[role] || role
}

async function loadMe() {
  loading.value = true
  try {
    const data = await profileApi.me()
    me.value = data
    editForm.nickname = data.nickname
    editForm.email = data.email
    editForm.phone = data.phone
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    const res = await profileApi.logs({ page: page.value, size: size.value })
    logs.value = res.list
    total.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    loadingLogs.value = false
  }
}

function loadAll() {
  loadMe()
  loadLogs()
}

function onSizeChange() {
  page.value = 1
  loadLogs()
}

function startEdit() {
  editForm.nickname = me.value.nickname || ''
  editForm.email = me.value.email || ''
  editForm.phone = me.value.phone || ''
  editing.value = true
}

async function submitProfile() {
  savingProfile.value = true
  try {
    const data = await profileApi.update({ ...editForm })
    me.value = data
    editing.value = false
    ElMessage.success('资料已更新')
    loadLogs()
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingProfile.value = false
  }
}

async function submitPassword() {
  const form = pwdFormRef.value
  if (!form) return
  const valid = await form.validate().catch(() => false)
  if (!valid) return
  changingPassword.value = true
  try {
    await profileApi.changePassword(pwdForm.old_password, pwdForm.new_password)
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
    form.clearValidate()
    await ElMessageBox.alert('密码已更新，请使用新密码重新登录。', '修改成功', {
      confirmButtonText: '重新登录',
      type: 'success',
    }).catch(() => undefined)
    auth.logout()
    router.push({ name: 'login' })
  } catch {
    /* 拦截器已提示 */
  } finally {
    changingPassword.value = false
  }
}

onMounted(loadAll)
</script>


