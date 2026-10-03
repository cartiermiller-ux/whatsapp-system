import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 20000,
})

service.interceptors.request.use((config) => {
  const token = localStorage.getItem('wa_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/* ---------------------------------------------------------------
   错误处理策略（客户体验相关）
   1. 网络抖动 / 5xx 自动重试一次，用户基本无感；
   2. 401 直接清登录态并跳登录页，不让用户卡在一个永远报错的页面上；
   3. 文案按原因区分（超时 / 断网 / 无权限 / 服务器错误），不再一律"网络请求失败"；
   4. 并发请求同时失败时只弹一条提示，避免刷屏。
   --------------------------------------------------------------- */

const RETRY_DELAY = 600
const TOAST_DEDUP_MS = 3000

let lastToastMsg = ''
let lastToastAt = 0
let redirecting = false

/** 同一原因的错误在 3 秒内只提示一次 */
function toastOnce(message: string, level: 'error' | 'warning' = 'error') {
  const now = Date.now()
  if (message === lastToastMsg && now - lastToastAt < TOAST_DEDUP_MS) return
  lastToastMsg = message
  lastToastAt = now
  if (level === 'warning') ElMessage.warning(message)
  else ElMessage.error(message)
}

/**
 * 是否值得静默重试。两个条件都要满足：
 *   1. 幂等方法（GET/HEAD）—— 对 POST 自动重试可能造成重复下单、重复建任务，
 *      尤其是"请求已到达但响应丢了"的超时场景，所以写操作一律不重试；
 *   2. 错误属于断网 / 超时 / 5xx —— 4xx 是业务错误，重试没有意义。
 */
const RETRIABLE_METHODS = ['get', 'head', 'options']

function isRetriable(
  error: { response?: { status?: number } },
  config?: { method?: string },
): boolean {
  const method = (config?.method || 'get').toLowerCase()
  if (!RETRIABLE_METHODS.includes(method)) return false
  if (!error?.response) return true
  return (error.response.status ?? 0) >= 500
}

function friendlyMessage(error: {
  response?: { status?: number; data?: { message?: string } }
  code?: string
  message?: string
}): string {
  const backend = error?.response?.data?.message
  if (backend) return backend
  const status = error?.response?.status
  if (status === 403) return '没有操作权限，请联系管理员'
  if (status === 404) return '请求的资源不存在'
  if (status === 429) return '操作过于频繁，请稍后再试'
  if (status) return `服务器错误（HTTP ${status}），请稍后重试`
  if (error?.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  return '无法连接后端服务，请确认服务已启动'
}

/** 登录态失效：清干净并跳登录页，带上回跳地址 */
async function handleUnauthorized() {
  const current = router.currentRoute.value
  // 路由守卫读的是 localStorage，先清它，保证立刻生效
  localStorage.removeItem('wa_token')
  localStorage.removeItem('wa_user')
  localStorage.removeItem('wa_tenant')
  try {
    // 动态引入避免 request -> stores/auth -> api -> request 的循环依赖
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore().logout()
  } catch {
    /* store 还不可用时忽略，localStorage 已经清了 */
  }
  if (redirecting || current.name === 'login') return
  redirecting = true
  ElMessage.warning('登录状态已失效，请重新登录')
  router
    .replace({ name: 'login', query: current.fullPath === '/' ? {} : { redirect: current.fullPath } })
    .finally(() => {
      redirecting = false
    })
}

// 后端统一返回 { code, data, message }，此处直接解包 data，失败统一提示
service.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      const msg = body.message || `请求失败（code: ${body.code}）`
      toastOnce(msg)
      return Promise.reject(new Error(msg))
    }
    return body
  },
  async (error) => {
    const config = error?.config as (AxiosRequestConfig & { __retried?: boolean }) | undefined

    // 读接口遇到断网 / 5xx：静默重试一次（写接口不重试，避免重复提交）
    if (config && isRetriable(error, config) && !config.__retried) {
      config.__retried = true
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY))
      return service.request(config)
    }

    if (error?.response?.status === 401) {
      await handleUnauthorized()
      return Promise.reject(error)
    }

    toastOnce(friendlyMessage(error))
    return Promise.reject(error)
  },
)

/** 统一请求入口，返回已解包的业务数据 */
export function request<T>(config: AxiosRequestConfig): Promise<T> {
  // 响应拦截器已把 { code, data } 解包为 data，这里用断言对齐类型
  return service.request(config) as unknown as Promise<T>
}

export default service
