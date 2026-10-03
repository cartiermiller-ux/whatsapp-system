import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

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
      {
        path: 'numbers',
        name: 'numbers',
        component: () => import('@/views/NumbersView.vue'),
        meta: { title: '号码池管理', icon: 'Iphone' },
      },
      {
        path: 'register',
        name: 'register',
        component: () => import('@/views/RegisterView.vue'),
        meta: { title: '注册管理', icon: 'UserFilled' },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { title: '账号管理', icon: 'Avatar' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('@/views/GroupsView.vue'),
        meta: { title: '资源群管理', icon: 'ChatDotRound' },
      },
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
        meta: { title: '广告消息管理', icon: 'Document' },
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

router.beforeEach((to) => {
  const token = localStorage.getItem('wa_token')
  if (!to.meta.public && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && token) {
    return { name: 'dashboard' }
  }
  document.title = `${(to.meta.title as string) || '控制台'} · WhatsApp 运营系统`
  return true
})

export default router
