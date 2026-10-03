import dayjs from 'dayjs'

export function formatDateTime(value?: string | number | Date | null): string {
  if (!value) return '-'
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

export function percent(part: number, total: number): string {
  if (!total) return '0%'
  return `${((part / total) * 100).toFixed(1)}%`
}

/** 把粘贴的多行文本 / 逗号分隔文本解析为号码数组 */
export function parsePhoneList(text: string): string[] {
  return text
    .split(/[\s,;\n\r\t]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 解析 "1,2,3" 形式的 id 文本为数字数组 */
export function parseIdList(text: string): number[] {
  return parsePhoneList(text)
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n) && n > 0)
}

/** 号码 / 状态等的展示文案映射 */
export const NUMBER_STATUS_LABEL: Record<string, string> = {
  pending: '待注册',
  registering: '注册中',
  success: '成功',
  failed: '失败',
  banned: '已封',
}

export const NUMBER_SOURCE_LABEL: Record<string, string> = {
  physical: '实体卡',
  virtual: '虚拟号',
  sms_platform: '接码平台',
}

export const ACCOUNT_STATUS_LABEL: Record<string, string> = {
  normal: '正常',
  watch: '观察',
  paused: '暂停',
  banned: '已封',
}

export const NURTURE_STAGE_LABEL: Record<string, string> = {
  none: '未开始',
  nurturing: '养号中',
  ready: '已就绪',
  done: '已完成',
}

export const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '进行中',
  paused: '已暂停',
  done: '已完成',
  cancelled: '已取消',
  failed: '失败',
}

export const AD_STATUS_LABEL: Record<string, string> = {
  active: '启用中',
  paused: '已暂停',
  draft: '草稿',
}

export const AD_LANGUAGE_LABEL: Record<string, string> = {
  zh: '中文',
  en: 'English',
  es: 'Español',
  pt: 'Português',
}

export const TRANSACTION_TYPE_LABEL: Record<string, string> = {
  recharge: '充值',
  consume: '消费',
  refund: '退款',
  adjust: '调账',
}

export const ORDER_STATUS_LABEL: Record<string, string> = {
  pending: '待支付',
  paid: '已到账',
  cancelled: '已取消',
  expired: '已过期',
}

export const USER_ROLE_LABEL: Record<string, string> = {
  super_admin: '超级管理员',
  agent_admin: '代理商管理员',
  operator: '操作员',
}

export const USER_STATUS_LABEL: Record<string, string> = {
  active: '正常',
  disabled: '已禁用',
}

export const OPERATION_ACTION_LABEL: Record<string, string> = {
  login: '登录',
  logout: '退出登录',
  update_password: '修改密码',
  update_profile: '更新资料',
  update_settings: '保存全局参数',
  create_ad_copy: '新建文案',
  update_ad_copy: '更新文案',
  delete_ad_copy: '删除文案',
  create_ad_link: '生成超链',
  update_ad_link: '更新超链',
  delete_ad_link: '删除超链',
  create_recharge: '创建充值订单',
  confirm_recharge: '确认充值到账',
  cancel_recharge: '取消充值订单',
  create_transaction: '手工调账',
  create_user: '新建用户',
  update_user: '更新用户',
  delete_user: '删除用户',
}

export const OPERATION_RESULT_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
}

export function statusTagType(status: string): 'success' | 'info' | 'warning' | 'danger' | 'primary' {
  switch (status) {
    case 'success':
    case 'done':
    case 'normal':
    case 'ready':
    case 'active':
    case 'paid':
      return 'success'
    case 'registering':
    case 'running':
    case 'nurturing':
      return 'primary'
    case 'pending':
    case 'watch':
    case 'paused':
      return 'warning'
    case 'failed':
    case 'banned':
    case 'cancelled':
    case 'expired':
    case 'disabled':
      return 'danger'
    default:
      return 'info'
  }
}

/** 资源对接 —— 供应商类型 */
export const PROVIDER_KIND_LABEL: Record<string, string> = {
  sms: '接码平台',
  proxy: '代理 IP',
  message: '发消息通道',
  account: '账号采购',
}

/** 资源对接 —— 代理池状态 */
export const PROXY_STATUS_LABEL: Record<string, string> = {
  free: '空闲',
  in_use: '占用',
  disabled: '停用',
}

/** 资源对接 —— 接码订单状态 */
export const SMS_ORDER_STATUS_LABEL: Record<string, string> = {
  waiting: '等待中',
  completed: '已完成',
  cancelled: '已取消',
  expired: '已过期',
}

/** 资源对接 —— 账号采购订单状态 */
export const PURCHASE_ORDER_STATUS_LABEL: Record<string, string> = {
  pending: '待交付',
  paid: '已付款',
  delivered: '已交付',
  failed: '失败',
  cancelled: '已取消',
}
