import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { profileApi } from '@/api'
import { canVisitPath, allowedSettingsTabs } from '@/utils/permissions'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '数据看板', icon: 'DataLine' },
      },
      { path: 'resources', name: 'resources', component: () => import('@/views/ResourceCenterView.vue'), meta: { title: '资源中心', icon: 'Collection' } },
      { path: 'numbers', redirect: { path: '/resources', query: { tab: 'numbers' } } },
      { path: 'register', redirect: { path: '/resources', query: { tab: 'access' } } },
      { path: 'groups', redirect: { path: '/resources', query: { tab: 'groups' } } },
      { path: 'accounts', name: 'accounts', component: () => import('@/views/AccountCenterView.vue'), meta: { title: 'WhatsApp 账号', icon: 'Avatar' } },
      { path: 'account-assistant', name: 'account-assistant', component: () => import('@/views/AccountAssistantView.vue'), meta: { title: '账号助手', icon: 'CircleCheck' } },
      { path: 'downloads', name: 'downloads', component: () => import('@/views/DownloadCenterView.vue'), meta: { title: '下载中心', icon: 'Download' } },
      {
        path: 'mass-send',
        name: 'mass-send',
        component: () => import('@/views/MassSendView.vue'),
        meta: { title: '群发任务', icon: 'Promotion' },
      },
      {
        path: 'pull-group',
        name: 'pull-group',
        component: () => import('@/views/PullGroupView.vue'),
        meta: { title: '拉群任务', icon: 'Connection' },
      },
      {
        path: 'integrations',
        name: 'integrations',
        component: () => import('@/views/IntegrationsView.vue'),
        meta: { title: '资源对接', icon: 'Link' },
      },
      {
        path: 'ads',
        name: 'ads',
        component: () => import('@/views/AdsView.vue'),
        meta: { title: '广告消息', icon: 'Document' },
      },
      {
        path: 'billing',
        name: 'billing',
        component: () => import('@/views/BillingView.vue'),
        meta: { title: '余额与计费', icon: 'Wallet' },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('@/views/ProfileView.vue'),
        meta: { title: '个人中心', icon: 'User' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统设置', icon: 'Setting' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('wa_token')
  if (!to.meta.public && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && token) {
    return { name: 'dashboard' }
  }
  if (!to.meta.public) {
    const auth = useAuthStore()
    try {
      const me = await profileApi.me()
      auth.user = { username: me.username, role: me.role, tenant: me.tenant }
      auth.tenant = me.tenant
    } catch {
      if (!localStorage.getItem('wa_token')) return { name: 'login', query: { redirect: to.fullPath } }
      return false
    }
    if (!canVisitPath(to.path, auth.user?.role)) return { name: 'dashboard' }
    if (to.path === '/settings') {
      const tabs = allowedSettingsTabs(auth.user?.role)
      if (!tabs.includes(String(to.query.tab || ''))) {
        return { path: '/settings', query: { ...to.query, tab: tabs[0] }, replace: true }
      }
    }
  }
  document.title = `${(to.meta.title as string) || '控制台'} · 奥贝通讯`
  return true
})

export default router
