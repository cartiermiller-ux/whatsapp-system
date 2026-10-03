// 与后端 FastAPI 的响应结构保持一致
export interface ApiResp<T> {
  code: number
  data?: T
  message?: string
}

/** 分页返回统一结构 */
export interface PageResult<T> {
  total: number
  page: number
  size: number
  list: T[]
}

/** POST /api/v1/numbers/import 的入参单项 */
export interface NumberImportItem {
  phone: string
  source_type: string
  source_channel?: string
}

/** POST /api/v1/numbers/import 返回 data */
export interface NumberImportResult {
  imported: number
  failed: number
}

/** GET /api/v1/numbers 列表项 */
export interface NumberRow {
  id: number
  phone_number: string
  source_type: string
  source_channel: string | null
  number_segment: string | null
  region: string | null
  trust_score: number
  status: string
  register_time: string | null
  account_id: number | null
  created_at: string | null
}

/** GET /api/v1/numbers 查询参数 */
export interface NumberQuery {
  page?: number
  size?: number
  status?: string
  source_type?: string
  keyword?: string
}

/** GET /api/v1/register/status 明细项 */
export interface RegisterStatusDetail {
  id: number
  phone: string
  status: string
}

/** GET /api/v1/register/status 返回 data */
export interface RegisterStatusResult {
  total: number
  success: number
  failed: number
  pending: number
  details: RegisterStatusDetail[]
}

/** GET /api/v1/accounts 列表项 */
export interface AccountItem {
  id: number
  number_id: number
  health_score: number
  status: string
  nurture_stage: string
  ip: string
}

/** GET /api/v1/accounts/{id} 详情 */
export interface AccountDetail {
  id: number
  number_id: number
  phone_number: string | null
  device_fingerprint: string | null
  current_ip: string | null
  nurture_stage: string
  health_score: number
  status: string
  created_at: string | null
}

/** POST /api/v1/mass-send/tasks 入参 */
export interface MassSendCreateReq {
  task_name: string
  /** group=资源群 ID（默认） / contact=号码池 ID 或手机号 */
  target_type?: string
  target_ids: number[]
  account_ids: number[]
  message_content: string
  link_url?: string
}

/** POST /api/v1/mass-send/tasks 返回 data */
export interface MassSendCreateResult {
  task_id: number
  status: string
}

/** GET /api/v1/mass-send/tasks/{id} 返回 data */
export interface MassSendProgress {
  task_id: number
  status: string
  target_type: string
  sent: number
  delivered: number
  read: number
}

/** GET /api/v1/mass-send/tasks 列表项 */
export interface MassSendTaskRow {
  id: number
  task_name: string
  status: string
  target_type: string
  sent: number
  delivered: number
  read: number
  created_at: string | null
}

/** 看板指标口径 */
export interface DashboardMetrics {
  tasks: number
  sent: number
  delivered: number
  read: number
  failed: number
  success_rate: number
  read_rate: number
}

/** GET /api/v1/dashboard/today 返回 data */
export type DashboardToday = DashboardMetrics

/** GET /api/v1/dashboard/overview 列表项 */
export interface DashboardTaskBrief {
  id: number
  task_name: string
  status: string
  target_type: string
  targets: number
  sent: number
  delivered: number
  read: number
  failed: number
  progress: number
  created_at: string | null
}

/** GET /api/v1/dashboard/overview 返回 data（首页一次请求拿全） */
export interface DashboardOverview {
  today: DashboardMetrics
  yesterday: DashboardMetrics
  total: DashboardMetrics
  balance: { balance: number; currency: string; pending_orders: number }
  accounts: { total: number; normal: number; watch: number; paused: number; banned: number }
  active_tasks: DashboardTaskBrief[]
  recent_tasks: DashboardTaskBrief[]
  providers: ProviderItem[]
  generated_at: string | null
}

export interface RegisterBatchResult {
  message: string
  count: number
}

/** GET /api/v1/groups 列表项 */
export interface GroupRow {
  id: number
  group_name: string
  group_jid: string
  group_link: string | null
  can_speak: boolean
  can_invite: boolean
  approval_mode: boolean
  group_owner: string | null
  marketing_score: number
  status: string
}

/** POST /api/v1/invite/tasks 入参 */
export interface InviteTaskCreateReq {
  task_name: string
  target_group_id: number
  source_type: string
  source_ids: number[]
  account_ids: number[]
  billing_country: string
}

export interface InviteTaskCreateResult {
  task_id: number
  status: string
}

/** GET /api/v1/invite/tasks 列表项 */
export interface InviteTaskRow {
  id: number
  task_name: string
  target_group_id: number
  status: string
  created_at: string | null
}

/** GET /api/v1/balance 返回 data */
export interface BalanceInfo {
  balance: number
  currency: string
  total_recharge: number
  total_consume: number
  pending_orders: number
  updated_at: string | null
}

/** GET /api/v1/balance/transactions 列表项 */
export interface TransactionRow {
  id: number
  type: string
  amount: number
  balance_before: number
  balance_after: number
  currency: string
  country: string
  task: string
  task_type: string
  task_id: number | null
  result: string
  remark: string
  created_at: string | null
}

/** GET /api/v1/settings 返回 data（键值扁平结构） */
export interface GlobalSettings {
  send_interval_min: number
  send_interval_max: number
  new_device_cooldown_hours: number
  daily_send_limit: number
  currency: string
  min_recharge_amount: number
  recharge_chain: string
  recharge_address: string
  recharge_expire_minutes: number
  short_link_domain: string
  [key: string]: string | number
}

/** GET /api/v1/settings/schema 列表项 */
export interface SettingField {
  key: string
  label: string
  description: string
  type: 'int' | 'float' | 'str' | 'bool'
  category: string
  min: number | null
  max: number | null
  max_len: number | null
  default: string | number
  value: string | number
  updated_at: string | null
}

/** PUT /api/v1/settings 入参 */
export type SettingsUpdateReq = Record<string, string | number>

/** 广告文案 —— GET /api/v1/ads/copies 列表项 */
export interface AdCopyRow {
  id: number
  title: string
  content: string
  language: string
  link_url: string
  variables: string[]
  category: string
  status: string
  sent: number
  delivered: number
  read: number
  click: number
  delivery_rate: number
  read_rate: number
  click_rate: number
  created_at: string | null
  updated_at: string | null
}

/** POST/PUT /api/v1/ads/copies 入参 */
export interface AdCopySaveReq {
  title: string
  content: string
  language?: string
  link_url?: string
  category?: string
  status?: string
}

/** GET /api/v1/ads/copies 查询参数 */
export interface AdCopyQuery {
  page?: number
  size?: number
  language?: string
  status?: string
  keyword?: string
}

/** GET /api/v1/ads/copies/{id}/stats 与 /ads/stats 列表项 */
export interface AdStatsRow {
  id: number
  title: string
  language: string
  status: string
  sent: number
  delivered: number
  read: number
  click: number
  delivery_rate: number
  read_rate: number
  click_rate: number
}

/** GET /api/v1/ads/stats 返回 data */
export interface AdStatsResult {
  totals: Omit<AdStatsRow, 'id' | 'title' | 'language' | 'status'> & { copies: number }
  list: AdStatsRow[]
}

/** 超链 —— GET /api/v1/ads/links 列表项 */
export interface AdLinkRow {
  id: number
  name: string
  original_url: string
  short_code: string
  short_url: string
  domain: string
  tracking_params: string
  target_url: string
  ad_message_id: number | null
  click_count: number
  status: string
  created_at: string | null
  updated_at: string | null
}

/** POST/PUT /api/v1/ads/links 入参 */
export interface AdLinkSaveReq {
  name: string
  original_url: string
  domain?: string
  tracking_params?: string
  ad_message_id?: number | null
  status?: string
}

/** GET /api/v1/ads/links 返回 data */
export interface AdLinkListResult extends PageResult<AdLinkRow> {
  default_domain: string
}

/** 充值订单 —— /api/v1/balance/recharge* */
export interface RechargeOrder {
  id: number
  order_no: string
  amount: number
  currency: string
  chain: string
  address: string
  tx_hash: string
  status: string
  user_id: number | null
  paid_at: string | null
  expire_at: string | null
  created_at: string | null
}

/** GET /api/v1/balance/recharge/orders 返回 data */
export interface RechargeOrderListResult extends PageResult<RechargeOrder> {
  address: string
  chain: string
  currency: string
  min_amount: number
}

/** POST /api/v1/balance/recharge/{id}/confirm 返回 data */
export interface RechargeConfirmResult {
  order: RechargeOrder
  transaction: TransactionRow
  balance: number
}

/** GET /api/v1/balance/rules 列表项 */
export interface BillingRule {
  country: string
  country_name: string
  dimension: string
  unit_price: number
  currency: string
}

/** GET /api/v1/me 返回 data */
export interface MeInfo {
  id: number
  username: string
  nickname: string
  email: string
  phone: string
  role: string
  tenant: string
  status: string
  last_login_at: string | null
  login_count: number
  created_at: string | null
  updated_at: string | null
}

/** GET /api/v1/me/logs 列表项 */
export interface OperationLogRow {
  id: number
  action: string
  target: string
  result: string
  detail: string
  created_at: string | null
}

/** POST /api/v1/admin/users 入参 */
export interface AdminUserCreateReq {
  username: string
  password: string
  nickname?: string
  email?: string
  phone?: string
  role?: string
  tenant?: string
}

/** PUT /api/v1/admin/users/{id} 入参 */
export interface AdminUserUpdateReq {
  nickname?: string
  email?: string
  phone?: string
  role?: string
  tenant?: string
  status?: string
  password?: string
}

/** GET /api/v1/numbers/export 行 */
export interface NumberExportRow {
  id: number
  phone: string
  source_type: string
  source_channel: string | null
  number_segment: string | null
  region: string | null
  trust_score: number
  status: string
  created_at: string | null
}

/** GET /api/v1/register/analysis 返回 data */
export interface RegisterAnalysis {
  total: number
  details: {
    id: number
    phone: string
    source_type: string
    source_channel: string | null
  }[]
}

/** GET /api/v1/invite/tasks/{id} 返回 data */
export interface InviteTaskDetail {
  task_id: number
  task_name: string
  target_group_id: number
  status: string
  created_at: string | null
}

/** 批量 ID 入参 */
export interface BatchIds {
  ids: number[]
}

/** GET /api/v1/providers/status 明细项 */
export interface ProviderItem {
  kind: string
  name: string
  configured: boolean
  mock: boolean
  detail: string
  balance: number | null
  extra: Record<string, unknown>
  pool?: { free: number; in_use: number; disabled: number }
}

/** GET /api/v1/providers/status 返回 data */
export interface ProvidersStatus {
  available: boolean
  error?: string
  items: ProviderItem[]
  config: { message_provider: string; proxy_required: boolean }
}

/** GET /api/v1/proxies 列表项 */
export interface ProxyRow {
  id: number
  host: string
  port: number
  protocol: string
  username: string
  address: string
  country: string
  asn: string
  provider: string
  status: string
  bound_number_id: number | null
  used_count: number
  ok_count: number
  fail_count: number
  latency_ms: number | null
  last_checked_at: string | null
  last_used_at: string | null
  created_at: string | null
}

/** GET /api/v1/sms/orders 列表项 */
export interface SmsOrderRow {
  id: number
  provider: string
  order_id: string
  phone: string
  phone_digits: string
  service: string
  country: string
  status: string
  price: number | null
  code: string
  text: string
  number_id: number | null
  expires_at: string | null
  created_at: string | null
  updated_at: string | null
}

/** POST /api/v1/sms/orders/{id}/wait 返回 data */
export interface SmsPollResult {
  ok: boolean
  code: string
  detail: string
  order: SmsOrderRow
}

/** GET /api/v1/purchase/products 列表项 */
export interface ProductRow {
  product_id: string
  name: string
  price: number
  currency: string
  country: string
  stock: number
  description: string
}

/** GET /api/v1/purchase/orders 列表项 */
export interface PurchaseOrderRow {
  id: number
  order_no: string
  provider: string
  product_id: string
  product_name: string
  quantity: number
  unit_price: number
  amount: number
  currency: string
  status: string
  accounts: string[]
  message: string
  remark: string
  created_by: string
  created_at: string | null
  updated_at: string | null
}
