<template>
  <el-dialog
    :model-value="modelValue"
    title="WhatsApp 账号"
    width="470px"
    :close-on-click-modal="false"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @open="onOpen"
    @closed="onClosed"
  >
    <div class="wa-login">
      <!-- 二维码 -->
      <div class="qr-box">
        <img v-if="state.qr_image" :src="state.qr_image" class="qr-img" alt="WhatsApp 登录二维码" />
        <div v-else class="qr-empty">
          <el-icon v-if="busy" class="is-loading" :size="26"><Loading /></el-icon>
          <el-icon v-else :size="26"><Iphone /></el-icon>
          <span>{{ emptyText }}</span>
        </div>
      </div>

      <div class="status-line">
        <el-tag :type="statusType" size="small" effect="plain">{{ statusLabel }}</el-tag>
        <span v-if="state.paired_phone" class="muted">
          {{ state.paired_phone }}
          <template v-if="state.registered">（账号 #{{ state.account_id }}）</template>
        </span>
        <span v-if="state.auth_name" class="muted mono">{{ state.auth_name }}</span>
      </div>

      <p class="hint" :class="{ 'hint-error': isProblem }">{{ state.hint }}</p>
      <p v-if="state.qr_image" class="hint muted">二维码约 20 秒自动轮换，扫不出来就等下一张。</p>

      <!-- 已有关联过的账号：一键切换 -->
      <div v-if="otherSessions.length" class="sessions">
        <div class="sessions-title muted">其它已关联的账号</div>
        <div v-for="item in otherSessions" :key="item.auth_name" class="session-row">
          <span class="mono">{{ item.paired_phone || item.auth_name }}</span>
          <span class="muted">账号 #{{ item.account_id }}</span>
          <el-button link type="primary" :disabled="busy" @click="switchTo(item)">使用</el-button>
          <el-button link type="danger" :disabled="busy" @click="unlink(item)">解绑</el-button>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button v-if="canStop" :loading="busy" @click="stop">停止</el-button>

      <!-- 未启动：明确给出两条路，避免"点开就已经登录"的困惑 -->
      <template v-if="canStart">
        <el-button :loading="busy" @click="start('current')">使用已登录账号</el-button>
        <el-button type="primary" :loading="busy" @click="start('new')">关联新账号（扫码）</el-button>
      </template>

      <el-button
        v-if="state.status === 'connected' && !state.registered"
        type="primary"
        :loading="busy"
        @click="register"
      >
        登记到账号池
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Iphone, Loading } from '@element-plus/icons-vue'
import { whatsappApi } from '@/api'
import type { WhatsAppSessionItem, WhatsAppStatus } from '@/types/api'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; registered: [] }>()

const POLL_MS = 3000

const empty: WhatsAppStatus = {
  status: 'idle',
  qr_image: '',
  node_running: false,
  node_owned: false,
  registered: false,
  paired_phone: '',
  account_id: null,
  number_id: null,
  hint: '',
  qr_seq: 0,
  qr_age_seconds: null,
  connected_at: null,
  last_error: '',
  auth_name: '',
  events: [],
}

const state = ref<WhatsAppStatus>({ ...empty })
const sessions = ref<WhatsAppSessionItem[]>([])
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABEL: Record<string, string> = {
  idle: '未启动',
  starting: '启动中',
  waiting_qr: '等待扫码',
  connected: '已登录',
  closed: '连接已断开',
  error: '启动失败',
  unavailable: '不可用',
}

const statusLabel = computed(() => STATUS_LABEL[state.value.status] || state.value.status)
const statusType = computed(() => {
  switch (state.value.status) {
    case 'connected':
      return 'success'
    case 'waiting_qr':
    case 'starting':
      return 'warning'
    case 'closed':
    case 'error':
    case 'unavailable':
      return 'danger'
    default:
      return 'info'
  }
})
const isProblem = computed(() => ['closed', 'error', 'unavailable'].includes(state.value.status))
const canStart = computed(() =>
  !['unavailable', 'starting', 'waiting_qr'].includes(state.value.status) || state.value.status === 'idle',
)
const canStop = computed(() => ['waiting_qr', 'starting', 'connected'].includes(state.value.status))

/** 除当前会话外，其它已配对、且已登记到账号池的登录态 */
const otherSessions = computed(() =>
  sessions.value.filter(
    (item) => item.paired && item.account_id && item.auth_name !== state.value.auth_name,
  ),
)

const emptyText = computed(() => {
  if (busy.value) return '正在建立会话…'
  if (state.value.status === 'connected') return '已登录，无需扫码'
  if (isProblem.value) return '会话未建立'
  return '点下方按钮开始'
})

async function load() {
  try {
    const [status, list] = await Promise.all([whatsappApi.status(), whatsappApi.sessions()])
    state.value = status
    sessions.value = list.list
  } catch {
    /* 拦截器已提示 */
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(load, POLL_MS)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function onOpen() {
  await load()
  startPolling()
}

function onClosed() {
  stopPolling()
}

async function start(mode: 'new' | 'current') {
  busy.value = true
  try {
    state.value = await whatsappApi.start(mode)
    if (mode === 'new' && state.value.status !== 'closed' && state.value.status !== 'error') {
      ElMessage.success('已用新的登录态启动，请用要关联的手机扫码')
    } else if (state.value.status === 'connected') {
      ElMessage.success('已接入已登录的账号')
    } else if (isProblem.value) {
      ElMessage.warning('会话未能建立，请看下方原因')
    }
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function switchTo(item: WhatsAppSessionItem) {
  busy.value = true
  try {
    state.value = await whatsappApi.switchAccount(item.account_id as number)
    ElMessage.success('已切换会话')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function unlink(item: WhatsAppSessionItem) {
  try {
    await ElMessageBox.confirm(
      `解绑 ${item.paired_phone || item.auth_name}？登录态目录会被删除，手机上也要移除该设备。`,
      '解绑账号',
      { type: 'warning' },
    )
  } catch {
    return
  }
  busy.value = true
  try {
    const res = await whatsappApi.unlink(item.auth_name)
    ElMessage.success(res.message)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function stop() {
  busy.value = true
  try {
    state.value = await whatsappApi.stop()
    ElMessage.success('已停止会话')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function register() {
  busy.value = true
  try {
    const res = await whatsappApi.registerAccount()
    ElMessage.success(res.message)
    await load()
    emit('registered')
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.wa-login {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--wa-space-3);
}

.qr-box {
  width: 240px;
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--wa-border);
  border-radius: var(--wa-radius);
  background: #fff;
}

.qr-img {
  width: 220px;
  height: 220px;
}

.qr-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--wa-space-2);
  padding: 0 var(--wa-space-4);
  text-align: center;
  font-size: var(--wa-font-xs);
  color: var(--wa-text-muted);
}

.status-line {
  display: flex;
  align-items: center;
  gap: var(--wa-space-2);
  font-size: var(--wa-font-sm);
  flex-wrap: wrap;
  justify-content: center;
}

.hint {
  margin: 0;
  width: 100%;
  font-size: var(--wa-font-xs);
  line-height: 1.7;
  color: var(--wa-text-secondary);
  word-break: break-word;
}

.hint-error {
  color: var(--wa-danger);
}

.sessions {
  width: 100%;
  border-top: 1px solid var(--wa-border);
  padding-top: var(--wa-space-3);
}

.sessions-title {
  font-size: var(--wa-font-xs);
  margin-bottom: var(--wa-space-2);
}

.session-row {
  display: flex;
  align-items: center;
  gap: var(--wa-space-2);
  font-size: var(--wa-font-sm);
  padding: 2px 0;
}

.session-row :deep(.el-button) {
  margin-left: 0;
}
</style>
