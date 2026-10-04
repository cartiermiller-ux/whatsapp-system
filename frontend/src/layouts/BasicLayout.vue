<template>
  <el-container class="layout-root">
    <el-aside :width="effectiveCollapsed ? '64px' : '208px'" class="layout-aside">
      <div class="logo">
        <el-icon :size="24" color="#303030"><ChatDotRound /></el-icon>
        <span v-show="!effectiveCollapsed" class="logo-text">奥贝通讯</span>
      </div>
      <nav class="sidebar-scroll" aria-label="主导航">
        <div v-for="group in menuGroups" :key="group.title" class="nav-group">
          <div v-show="!effectiveCollapsed" class="nav-group-title">{{ group.title }}</div>
          <el-menu :default-active="activeMenu" :collapse="effectiveCollapsed" :collapse-transition="false" router>
            <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
              <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.title }}</template>
            </el-menu-item>
          </el-menu>
        </div>
      </nav>
      <el-menu class="sidebar-bottom" :default-active="activeMenu" :collapse="effectiveCollapsed" :collapse-transition="false" router>
        <el-menu-item v-for="item in bottomItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-left">
          <button class="collapse-btn" type="button" :aria-expanded="!effectiveCollapsed" aria-label="切换侧栏" @click="collapsed = !collapsed">
          <el-icon :size="18">
            <Fold v-if="!effectiveCollapsed" />
            <Expand v-else />
          </el-icon>
          </button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ name: 'dashboard' }">控制台</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <router-link to="/billing" class="header-balance">余额 {{ balance === null ? '—' : balance.balance + ' ' + balance.currency }}</router-link>
          <span v-if="auth.user?.role === 'super_admin'" class="tenant-label">{{ auth.tenant === 'default' ? '默认租户' : auth.tenant }}</span>

          <el-dropdown @command="onCommand">
            <span class="user-trigger">
              <el-avatar :size="28" :icon="UserFilled" />
              <span class="user-name">{{ auth.user?.username || '未登录' }}</span>
              <el-tag size="small" type="info" effect="plain">{{ auth.user?.role || '-' }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout" :icon="SwitchButton">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main ref="mainPanel" class="layout-main">
        <router-view v-slot="{ Component }">
          <keep-alive :max="10">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { UserFilled, SwitchButton } from '@element-plus/icons-vue'
import { billingApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { canVisitPath } from '@/utils/permissions'

interface MenuItem {
  path: string
  title: string
  icon: string
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const mainPanel = ref<{ $el: HTMLElement }>()
watch(() => route.path, async () => {
  await nextTick()
  mainPanel.value?.$el.scrollTo({ top: 0, left: 0 })
})
const collapsed = ref(false)
const narrowScreen = window.matchMedia('(max-width: 768px)')
const compact = ref(narrowScreen.matches)
const effectiveCollapsed = computed(() => collapsed.value || compact.value)
function updateCompact(event: MediaQueryListEvent) { compact.value = event.matches }
onMounted(() => narrowScreen.addEventListener('change', updateCompact))
onBeforeUnmount(() => narrowScreen.removeEventListener('change', updateCompact))

const menuItems: MenuItem[] = [
  { path: '/dashboard', title: '数据看板', icon: 'DataLine' },
  { path: '/resources', title: '资源中心', icon: 'Collection' },
  { path: '/accounts', title: 'WhatsApp 账号', icon: 'Avatar' },
  { path: '/account-assistant', title: '账号助手', icon: 'CircleCheck' },
  { path: '/downloads', title: '下载中心', icon: 'Download' },
  { path: '/mass-send', title: '群发任务', icon: 'Promotion' },
  { path: '/pull-group', title: '拉群任务', icon: 'Connection' },
  { path: '/integrations', title: '资源对接', icon: 'Link' },
  { path: '/ads', title: '广告消息', icon: 'Document' },
  { path: '/billing', title: '余额与计费', icon: 'Wallet' },
  { path: '/profile', title: '个人中心', icon: 'User' },
  { path: '/settings', title: '系统设置', icon: 'Setting' },
]

const menuGroups = computed(() => [
  { title: '工作台', paths: ['/dashboard'] },
  { title: '账号与资源', paths: ['/accounts', '/account-assistant', '/resources'] },
  { title: '运营任务', paths: ['/mass-send', '/pull-group', '/ads'] },
  { title: '资源服务', paths: ['/integrations', '/downloads'] },
  { title: '财务', paths: ['/billing'] },
].map(group => ({ title: group.title, items: group.paths.filter(path => canVisitPath(path, auth.user?.role)).map(path => menuItems.find(item => item.path === path)!) })))
const bottomItems = computed(() => menuItems.filter(item => ['/profile', '/settings'].includes(item.path) && canVisitPath(item.path, auth.user?.role)))
const balance = ref<{ balance: number; currency: string } | null>(null)
async function loadBalance() {
  balance.value = null
  try { balance.value = await billingApi.balance() } catch { /* 请求错误由拦截器处理 */ }
}
onMounted(loadBalance)
watch(() => route.path, loadBalance)
watch(() => auth.tenant, loadBalance)

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => (route.meta.title as string) || '')


async function onCommand(command: string) {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
      auth.logout()
      router.push({ name: 'login' })
    } catch {
      /* 用户取消 */
    }
  }
}
</script>

<style scoped>
.layout-root { height: 100vh; height: 100dvh; }
.layout-root > .el-container { min-width: 0; }
.layout-aside { display: flex; flex-direction: column; background: var(--wa-sidebar-bg); border-right: 1px solid var(--wa-border); transition: width .2s; overflow-x: hidden; }
.logo { height: 52px; display: flex; align-items: center; gap: 8px; padding: 0 20px; color: var(--wa-text); font-size: 14px; font-weight: 600; white-space: nowrap; }
.layout-aside :deep(.el-menu) { padding: 4px 8px; }
.layout-aside :deep(.el-menu-item) { height: 36px; line-height: 36px; margin-bottom: 4px; border-radius: 8px; padding-left: 12px !important; }
.layout-aside :deep(.el-menu-item.is-active) { background: var(--wa-sidebar-active); font-weight: 600; }
.layout-aside :deep(.el-menu--collapse) { width: 48px; }
.layout-header { height: 52px; padding: 0 16px; background: var(--wa-surface); border-bottom: 1px solid var(--wa-border); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.header-left, .header-right, .user-trigger { display: flex; align-items: center; gap: 12px; }
.header-left { min-width: 0; }
.collapse-btn { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; background: transparent; cursor: pointer; color: var(--wa-text-secondary); flex-shrink: 0; }
.collapse-btn:hover { background: var(--wa-hover); }
.collapse-btn:focus-visible { outline: 2px solid var(--wa-primary); outline-offset: 2px; }
.tenant-select { width: 120px; }
.user-trigger { gap: 8px; cursor: pointer; }
.user-name { font-size: 13px; color: var(--wa-text); }
.layout-main { min-width: 0; background: var(--wa-bg); padding: 0; overflow-y: auto; }
@media (max-width: 768px) {
  .layout-aside { width: 64px !important; }
  .logo { padding: 0 20px; }
  .logo-text, .layout-aside :deep(.el-menu-item span) { display: none; }
  .layout-aside :deep(.el-menu-item) { padding: 0 12px !important; }
  .layout-header { padding: 0 8px; gap: 8px; }
  .header-left, .header-right { gap: 8px; }
  .header-left :deep(.el-breadcrumb) { display: none; }
  .user-name, .user-trigger :deep(.el-tag) { display: none; }
  .tenant-select { width: 104px; }
}
@media (prefers-reduced-motion: reduce) { .layout-aside { transition: none; } }
</style>

<style scoped>
.logo { flex-shrink: 0; }
.sidebar-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.nav-group { margin-bottom: 10px; }
.nav-group-title { padding: 8px 20px 3px; font-size: 11px; color: var(--wa-text-muted); }
.layout-aside :deep(.el-menu) { background: transparent; }
.sidebar-bottom { border-top: 1px solid var(--wa-border); flex-shrink: 0; }
.header-balance { color: var(--wa-text-secondary); text-decoration: none; font-size: 12px; white-space: nowrap; }
</style>
