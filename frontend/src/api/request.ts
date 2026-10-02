import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

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

// 后端统一返回 { code, data, message }，此处直接解包 data，失败统一提示
service.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      const msg = body.message || `请求失败（code: ${body.code}）`
      ElMessage.error(msg)
      return Promise.reject(new Error(msg))
    }
    return body
  },
  (error) => {
    const msg =
      error?.response?.data?.message ||
      error?.message ||
      '网络请求失败，请检查后端服务是否已启动'
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

/** 统一请求入口，返回已解包的业务数据 */
export function request<T>(config: AxiosRequestConfig): Promise<T> {
  // 响应拦截器已把 { code, data } 解包为 data，这里用断言对齐类型
  return service.request(config) as unknown as Promise<T>
}

export default service
