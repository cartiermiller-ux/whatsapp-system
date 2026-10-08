import { request } from './request'
import type {
  TaskExecutionRow, TaskLogRow, ServiceConfigField, ServiceHealth,
  WhatsAppRegisterResult,
  WhatsAppSessionsResult,
  WhatsAppStatus,
  AccountDetail,
  AccountItem,
  AdCopyQuery,
  AdCopyRow,
  AdCopySaveReq,
  AdLinkListResult,
  AdLinkRow,
  AdLinkSaveReq,
  AdStatsResult,
  AdStatsRow,
  AdminUserCreateReq,
  AdminUserUpdateReq,
  BalanceInfo,
  BillingRule,
  DashboardOverview,
  DashboardToday,
  GlobalSettings,
  GroupRow,
  InviteTaskCreateReq,
  InviteTaskCreateResult,
  InviteTaskDetail,
  InviteTaskRow,
  MassSendCreateReq,
  MassSendCreateResult,
  MassSendProgress,
  MassSendTaskRow,
  MeInfo,
  NumberExportRow,
  NumberImportItem,
  NumberImportResult,
  NumberQuery,
  NumberRow,
  OperationLogRow,
  PageResult,
  ProductRow,
  ProvidersStatus,
  ProxyRow,
  PurchaseOrderRow,
  RechargeConfirmResult,
  RechargeOrder,
  RechargeOrderListResult,
  RegisterAnalysis,
  RegisterBatchResult,
  RegisterStatusResult,
  SettingField,
  SettingsUpdateReq,
  SmsOrderRow,
  SmsPollResult,
  TransactionRow,
} from '@/types/api'

/** 号码池 —— /api/v1/numbers */
export const numberApi = {
  import(items: NumberImportItem[]) {
    return request<NumberImportResult>({
      url: '/numbers/import',
      method: 'post',
      data: items,
    })
  },
  list(query: NumberQuery = {}) {
    return request<PageResult<NumberRow>>({
      url: '/numbers',
      method: 'get',
      params: query,
    })
  },
  remove(ids: number[]) {
    return request<{ count: number }>({
      url: '/numbers',
      method: 'delete',
      data: { ids },
    })
  },
  export() {
    return request<NumberExportRow[]>({ url: '/numbers/export', method: 'get' })
  },
}

/** 注册 —— /api/v1/register/* */
export const registerApi = {
  batch(numberIds: number[]) {
    return request<RegisterBatchResult>({
      url: '/register/batch',
      method: 'post',
      data: { number_ids: numberIds },
    })
  },
  status() {
    return request<RegisterStatusResult>({
      url: '/register/status',
      method: 'get',
    })
  },
  analysis() {
    return request<RegisterAnalysis>({
      url: '/register/analysis',
      method: 'get',
    })
  },
}

/** 账号 —— /api/v1/accounts */
export const accountApi = {
  logs(id: number, params: { page: number; size: number }) { return request<PageResult<TaskLogRow>>({ url: `/accounts/${id}/logs`, method: 'get', params }) },
  assignProxy(id: number, proxy_id: number) { return request<{ message: string }>({ url: `/accounts/${id}/proxy`, method: 'post', data: { proxy_id } }) },
  remove(id: number) { return request<{ deleted: number }>({ url: `/accounts/${id}`, method: 'delete' }) },
  convert(id: number) { return request<{ account_id: number; files: number }>({ url: `/accounts/${id}/convert`, method: 'post' }) },
  convertMany(ids: number[]) { return request<{ converted: { account_id: number }[]; failures: { id: number; reason: string }[] }>({ url: '/accounts/convert', method: 'post', data: { ids } }) },
  export(ids: number[]) { return request<Blob>({ url: '/accounts/export', method: 'post', data: { ids }, responseType: 'blob', timeout: 120000 }) },
  list() {
    return request<AccountItem[]>({ url: '/accounts', method: 'get' })
  },
  detail(id: number) {
    return request<AccountDetail>({ url: `/accounts/${id}`, method: 'get' })
  },
  pause(id: number) {
    return request<unknown>({ url: `/accounts/${id}/pause`, method: 'post' })
  },
  resume(id: number) {
    return request<unknown>({ url: `/accounts/${id}/resume`, method: 'post' })
  },
}

/** 群发任务 —— /api/v1/mass-send/* */
export const massSendApi = {
  create(payload: MassSendCreateReq) {
    return request<MassSendCreateResult>({
      url: '/mass-send/tasks',
      method: 'post',
      data: payload,
    })
  },
  list(query: { page?: number; size?: number; status?: string } = {}) {
    return request<PageResult<MassSendTaskRow>>({
      url: '/mass-send/tasks',
      method: 'get',
      params: query,
    })
  },
  detail(taskId: number) {
    return request<MassSendProgress>({
      url: `/mass-send/tasks/${taskId}`,
      method: 'get',
    })
  },
  remove(ids: number[]) {
    return request<{ deleted: number; message?: string }>({
      url: '/mass-send/tasks',
      method: 'delete',
      data: { ids },
    })
  },
}

/** 资源群 —— GET /api/v1/groups */
export const groupApi = {
  import(items: { group_name: string; group_jid: string; source_channel?: string; owner_account_id?: number }[]) {
    return request<{ added: number; updated: number }>({ url: '/groups/import', method: 'post', data: items })
  },
  export(query: { keyword?: string; status?: string } = {}) {
    return request<GroupRow[]>({ url: '/groups/export', method: 'get', params: query })
  },
  remove(ids: number[]) {
    return request<{ count: number }>({ url: '/groups', method: 'delete', data: { ids } })
  },
  list(query: { page?: number; size?: number; keyword?: string; status?: string } = {}) {
    return request<PageResult<GroupRow>>({
      url: '/groups',
      method: 'get',
      params: query,
    })
  },
  fetchLinks(ids: number[]) {
    return request<{ updated: number; message: string; failures: { id: number; reason: string }[] }>({
      url: '/groups/fetch-links',
      method: 'post',
      data: { ids },
    })
  },
}

/** 拉群任务 —— /api/v1/invite/tasks */
export const inviteApi = {
  create(payload: InviteTaskCreateReq) {
    return request<InviteTaskCreateResult>({
      url: '/invite/tasks',
      method: 'post',
      data: payload,
    })
  },
  list(query: { page?: number; size?: number } = {}) {
    return request<PageResult<InviteTaskRow>>({
      url: '/invite/tasks',
      method: 'get',
      params: query,
    })
  },
  detail(id: number) {
    return request<InviteTaskDetail>({ url: `/invite/tasks/${id}`, method: 'get' })
  },
  remove(ids: number[]) {
    return request<{ deleted: number; message?: string }>({
      url: '/invite/tasks',
      method: 'delete',
      data: { ids },
    })
  },
}

/** 广告消息 —— /api/v1/ads/* */
export const adApi = {
  listCopies(query: AdCopyQuery = {}) {
    return request<PageResult<AdCopyRow>>({ url: '/ads/copies', method: 'get', params: query })
  },
  createCopy(payload: AdCopySaveReq) {
    return request<AdCopyRow>({ url: '/ads/copies', method: 'post', data: payload })
  },
  detailCopy(id: number) {
    return request<AdCopyRow>({ url: `/ads/copies/${id}`, method: 'get' })
  },
  updateCopy(id: number, payload: Partial<AdCopySaveReq>) {
    return request<AdCopyRow>({ url: `/ads/copies/${id}`, method: 'put', data: payload })
  },
  removeCopy(id: number) {
    return request<{ deleted: number }>({ url: `/ads/copies/${id}`, method: 'delete' })
  },
  removeCopies(ids: number[]) {
    return request<{ deleted: number }>({ url: '/ads/copies', method: 'delete', data: { ids } })
  },
  copyStats(id: number) {
    return request<AdStatsRow>({ url: `/ads/copies/${id}/stats`, method: 'get' })
  },
  /** 全部文案的效果汇总 */
  stats() {
    return request<AdStatsResult>({ url: '/ads/stats', method: 'get' })
  },
  listLinks(query: { page?: number; size?: number; status?: string; keyword?: string } = {}) {
    return request<AdLinkListResult>({ url: '/ads/links', method: 'get', params: query })
  },
  createLink(payload: AdLinkSaveReq) {
    return request<AdLinkRow>({ url: '/ads/links', method: 'post', data: payload })
  },
  updateLink(id: number, payload: Partial<AdLinkSaveReq>) {
    return request<AdLinkRow>({ url: `/ads/links/${id}`, method: 'put', data: payload })
  },
  removeLink(id: number) {
    return request<{ deleted: number }>({ url: `/ads/links/${id}`, method: 'delete' })
  },
}

/** 余额与计费 —— /api/v1/balance* */
export const billingApi = {
  balance() {
    return request<BalanceInfo>({ url: '/balance', method: 'get' })
  },
  transactions(
    query: { page?: number; size?: number; type?: string; country?: string; keyword?: string } = {},
  ) {
    return request<PageResult<TransactionRow>>({
      url: '/balance/transactions',
      method: 'get',
      params: query,
    })
  },
  /** 创建 USDT 充值订单 */
  recharge(amount: number, chain?: string) {
    return request<RechargeOrder>({
      url: '/balance/recharge',
      method: 'post',
      data: { amount, chain },
    })
  },
  orders(query: { page?: number; size?: number; status?: string } = {}) {
    return request<RechargeOrderListResult>({
      url: '/balance/recharge/orders',
      method: 'get',
      params: query,
    })
  },
  /** 模拟到账确认（链上回调接入前的过渡接口） */
  confirmOrder(id: number) {
    return request<RechargeConfirmResult>({
      url: `/balance/recharge/${id}/confirm`,
      method: 'post',
    })
  },
  cancelOrder(id: number) {
    return request<RechargeOrder>({ url: `/balance/recharge/${id}/cancel`, method: 'post' })
  },
  rules() {
    return request<BillingRule[]>({ url: '/balance/rules', method: 'get' })
  },
}

/** 系统设置 —— /api/v1/settings */
export const settingsApi = {
  get() {
    return request<GlobalSettings>({ url: '/settings', method: 'get' })
  },
  /** 参数定义（分组 / 类型 / 取值范围），用于动态渲染表单 */
  schema() {
    return request<SettingField[]>({ url: '/settings/schema', method: 'get' })
  },
  update(payload: SettingsUpdateReq) {
    return request<GlobalSettings>({ url: '/settings', method: 'put', data: payload })
  },
}

/** 个人中心 —— /api/v1/me* */
export const profileApi = {
  me() {
    return request<MeInfo>({ url: '/me', method: 'get' })
  },
  update(payload: { nickname?: string; email?: string; phone?: string }) {
    return request<MeInfo>({ url: '/me', method: 'put', data: payload })
  },
  changePassword(oldPassword: string, newPassword: string) {
    return request<{ message: string }>({
      url: '/me/password',
      method: 'post',
      data: { old_password: oldPassword, new_password: newPassword },
    })
  },
  logs(query: { page?: number; size?: number; action?: string; result?: string } = {}) {
    return request<PageResult<OperationLogRow>>({ url: '/me/logs', method: 'get', params: query })
  },
}

/** 用户管理（管理员） —— /api/v1/admin/users */
export const adminApi = {
  tenants() {
    return request<{ id: number; name: string; status: string; users: number; created_at: string }[]>({ url: '/admin/tenants', method: 'get' })
  },
  createTenant(name: string) {
    return request<{ id: number }>({ url: '/admin/tenants', method: 'post', data: { name } })
  },
  updateTenant(id: number, status: string) {
    return request({ url: `/admin/tenants/${id}`, method: 'put', data: { status } })
  },
  users(query: { page?: number; size?: number; keyword?: string; role?: string; status?: string } = {}) {
    return request<PageResult<MeInfo>>({ url: '/admin/users', method: 'get', params: query })
  },
  createUser(payload: AdminUserCreateReq) {
    return request<MeInfo>({ url: '/admin/users', method: 'post', data: payload })
  },
  updateUser(id: number, payload: AdminUserUpdateReq) {
    return request<MeInfo>({ url: `/admin/users/${id}`, method: 'put', data: payload })
  },
  removeUser(id: number) {
    return request<{ deleted: number }>({ url: `/admin/users/${id}`, method: 'delete' })
  },
}

/** 数据看板 —— /api/v1/dashboard/* */
export const dashboardApi = {
  today() {
    return request<DashboardToday>({ url: '/dashboard/today', method: 'get' })
  },
  /** 首页聚合：一次请求拿到概览 / 余额 / 任务 / 通道状态 */
  overview() {
    return request<DashboardOverview>({ url: '/dashboard/overview', method: 'get' })
  },
}

/** 登录 —— POST /api/v1/auth/login */
export interface LoginReq {
  username: string
  password: string
}

export interface LoginResult {
  token: string
  username: string
  role: string
  tenant: string
}

export const authApi = {
  login(payload: LoginReq) {
    return request<LoginResult>({
      url: '/auth/login',
      method: 'post',
      data: payload,
    })
  },
  /** token 显式传入：本地登录态会被立即清空，不能依赖拦截器再去读取 */
  logout(token?: string) {
    return request<{ message: string }>({
      url: '/auth/logout',
      method: 'post',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
  },
}

/** 资源对接 —— /api/v1/providers、/proxies、/sms、/purchase */
export const integrationApi = {
  config() { return request<ServiceConfigField[]>({ url: '/providers/config', method: 'get' }) },
  saveConfig(data: Record<string, string>) { return request<ServiceConfigField[]>({ url: '/providers/config', method: 'put', data }) },
  health() { return request<ServiceHealth>({ url: '/providers/health', method: 'get' }) },
  checkHealth() { return request<ServiceHealth>({ url: '/providers/health', method: 'post', timeout: 120000 }) },
  /** 供应商（接码 / 代理 / 账号采购 / 发消息通道）状态汇总 */
  status() {
    return request<ProvidersStatus>({ url: '/providers/status', method: 'get' })
  },
  listProxies(query: { page?: number; size?: number; status?: string; country?: string; proxy_type?: string; group_id?: number } = {}) {
    return request<PageResult<ProxyRow>>({ url: '/proxies', method: 'get', params: query })
  },
  syncProxies(payload: { limit?: number; country?: string } = {}) {
    return request<{ provider: string; fetched: number; added: number; updated: number }>({
      url: '/proxies/sync',
      method: 'post',
      data: payload,
    })
  },
  importProxies(payload: { text: string; country?: string; proxy_type?: string; group_id?: number }) {
    return request<{ added: number; skipped: number }>({
      url: '/proxies/import',
      method: 'post',
      data: payload,
    })
  },
  testProxy(id: number) {
    return request<{ ok: boolean; detail: string; proxy: ProxyRow }>({
      url: `/proxies/${id}/test`,
      method: 'post',
    })
  },
  releaseProxy(id: number) {
    return request<ProxyRow>({ url: `/proxies/${id}/release`, method: 'post' })
  },
  removeProxies(ids: number[]) {
    return request<{ deleted: number }>({ url: '/proxies', method: 'delete', data: { ids } })
  },
  defaultProxy(id: number) {
    return request<ProxyRow>({ url: `/proxies/${id}/default`, method: 'post' })
  },
  editProxy(id: number, text: string) {
    return request<ProxyRow>({ url: `/proxies/${id}`, method: 'put', data: { text } })
  },
  listSmsOrders(query: { page?: number; size?: number; status?: string } = {}) {
    return request<PageResult<SmsOrderRow>>({ url: '/sms/orders', method: 'get', params: query })
  },
  createSmsOrder(payload: { service: string; country: string }) {
    return request<SmsOrderRow>({ url: '/sms/orders', method: 'post', data: payload })
  },
  pollSmsOrder(id: number) {
    return request<SmsOrderRow>({ url: `/sms/orders/${id}/poll`, method: 'post' })
  },
  /** 阻塞等待验证码：后端最坏会等待 180 秒，必须覆盖默认的 20 秒超时 */
  waitSmsOrder(id: number, payload: { timeout?: number; interval?: number } = { timeout: 180, interval: 5 }) {
    return request<SmsPollResult>({
      url: `/sms/orders/${id}/wait`,
      method: 'post',
      data: payload,
      timeout: 200000,
    })
  },
  cancelSmsOrder(id: number) {
    return request<SmsOrderRow>({ url: `/sms/orders/${id}/cancel`, method: 'post' })
  },
  removeSmsOrders(ids: number[]) {
    return request<{ deleted: number }>({ url: '/sms/orders', method: 'delete', data: { ids } })
  },
  listProducts() {
    return request<{ provider: string; list: ProductRow[] }>({
      url: '/purchase/products',
      method: 'get',
    })
  },
  listPurchaseOrders(
    query: { page?: number; size?: number; status?: string; keyword?: string } = {},
  ) {
    return request<PageResult<PurchaseOrderRow>>({
      url: '/purchase/orders',
      method: 'get',
      params: query,
    })
  },
  createPurchaseOrder(payload: { product_id: string; quantity: number; remark?: string }) {
    return request<PurchaseOrderRow>({ url: '/purchase/orders', method: 'post', data: payload })
  },
  syncPurchaseOrder(id: number) {
    return request<PurchaseOrderRow>({ url: `/purchase/orders/${id}/sync`, method: 'post' })
  },
  removePurchaseOrder(id: number) {
    return request<{ deleted: number }>({ url: `/purchase/orders/${id}`, method: 'delete' })
  },
}

/** 面板内扫码登录 WhatsApp —— /api/v1/whatsapp/* */
export const whatsappApi = {
  status(authName = '') {
    return request<WhatsAppStatus>({ url: '/whatsapp/status', method: 'get', params: { auth_name: authName } })
  },
  /** 本机已有的登录态目录及其对应账号 */
  sessions() {
    return request<WhatsAppSessionsResult>({ url: '/whatsapp/sessions', method: 'get' })
  },
  /**
   * 启动会话（需要时后端会拉起 wasock 的 Node 服务）
   * mode="new" 用全新登录态目录，必然出二维码，用于关联新账号；
   * mode="current" 用已登录的目录，直接以该号上线。
   */
  start(mode: 'new' | 'current' = 'current') {
    return request<WhatsAppStatus>({
      url: '/whatsapp/start',
      method: 'post',
      data: { mode },
      timeout: 120000,
    })
  },
  /** 选择账号会话，其他账号继续在线 */
  switchAccount(accountId: number) {
    return request<WhatsAppStatus>({
      url: '/whatsapp/switch',
      method: 'post',
      data: { account_id: accountId },
      timeout: 120000,
    })
  },
  /** 解绑：删除登录态目录 */
  unlink(authName: string) {
    return request<{ removed: boolean; auth_name: string; message: string }>({
      url: '/whatsapp/unlink',
      method: 'post',
      data: { auth_name: authName },
    })
  },
  stop(authName = '') {
    return request<WhatsAppStatus>({ url: '/whatsapp/stop', method: 'post', data: { auth_name: authName } })
  },
  /** 把扫码登录的号登记进号码池 / 账号池 */
  registerAccount(authName = '') {
    return request<WhatsAppRegisterResult>({
      url: '/whatsapp/register-account',
      method: 'post', data: { auth_name: authName },
    })
  },
}

export const taskApi = {
  resolve(kind: string, id: number, executionId: number, data: { status: string; note: string; message_id?: string }) {
    return request<unknown>({ url: `/tasks/${kind}/${id}/executions/${executionId}`, method: 'patch', data })
  },
  executions(kind: string, id: number, params: { page: number; size: number }) {
    return request<PageResult<TaskExecutionRow>>({ url: `/tasks/${kind}/${id}/executions`, method: 'get', params })
  },
  logs(kind: string, id: number, params: { page: number; size: number }) {
    return request<PageResult<TaskLogRow>>({ url: `/tasks/${kind}/${id}/logs`, method: 'get', params })
  },
  control(kind: string, id: number, action: string) {
    return request<unknown>({ url: `/tasks/${kind}/${id}/${action}`, method: 'post' })
  },
}

export const resourceApi = {
  overview() { return request<import('@/types/api').ResourcePlatformOverview[]>({ url: '/resources/overview', method: 'get' }) },
  accessTasks(params: { page: number; size: number; keyword?: string; status?: string }) { return request<PageResult<import('@/types/api').AccessTaskRow>>({ url: '/resources/access-tasks', method: 'get', params }) },
}
