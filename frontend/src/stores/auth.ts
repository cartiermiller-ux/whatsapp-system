import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api'

export interface AuthUser {
  username: string
  role: string
  tenant: string
}

const LS_TOKEN = 'wa_token'
const LS_USER = 'wa_user'
const LS_TENANT = 'wa_tenant'
const LS_REMEMBER = 'wa_remember'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(LS_TOKEN) || '')
  const user = ref<AuthUser | null>(JSON.parse(localStorage.getItem(LS_USER) || 'null'))
  const tenant = ref<string>(localStorage.getItem(LS_TENANT) || 'default')
  const remember = ref<boolean>(localStorage.getItem(LS_REMEMBER) === '1')

  async function login(payload: {
    username: string
    password: string
    tenant?: string
    remember?: boolean
  }) {
    const data = await authApi.login({
      username: payload.username,
      password: payload.password,
    })

    token.value = data.token
    user.value = {
      username: data.username,
      role: data.role,
      tenant: data.tenant,
    }
    tenant.value = payload.tenant || data.tenant || 'default'
    remember.value = !!payload.remember

    localStorage.setItem(LS_TOKEN, token.value)
    localStorage.setItem(LS_USER, JSON.stringify(user.value))
    localStorage.setItem(LS_TENANT, tenant.value)
    localStorage.setItem(LS_REMEMBER, remember.value ? '1' : '0')
  }

  function logout() {
    // 先通知后端释放 token（失败也不阻塞本地登出）
    if (token.value) {
      authApi.logout(token.value).catch(() => undefined)
    }
    token.value = ''
    user.value = null
    tenant.value = 'default'
    localStorage.removeItem(LS_TOKEN)
    localStorage.removeItem(LS_USER)
    localStorage.removeItem(LS_TENANT)
    localStorage.removeItem(LS_REMEMBER)
  }

  function switchTenant(next: string) {
    tenant.value = next
    localStorage.setItem(LS_TENANT, next)
    if (user.value) {
      user.value = { ...user.value, tenant: next }
      localStorage.setItem(LS_USER, JSON.stringify(user.value))
    }
  }

  return { token, user, tenant, remember, login, logout, switchTenant }
})