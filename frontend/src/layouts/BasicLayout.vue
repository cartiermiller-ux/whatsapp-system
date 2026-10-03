<template>
  <el-container class="layout-root">
    <el-aside :width="effectiveCollapsed ? '64px' : '208px'" class="layout-aside">
      <div class="logo">
        <el-icon :size="24" color="#303030"><ChatDotRound /></el-icon>
        <span v-show="!effectiveCollapsed" class="logo-text">WhatsApp 运营</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="effectiveCollapsed"
        :collapse-transition="false"
        background-color="#f9f9f9"
        text-color="#5d5d5d"
        active-text-color="#303030"
        router
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
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
          <el-select
            v-model="tenant"
            size="small"
            class="tenant-select"
            @change="onTenantChange"
          >
            <el-option label="默认租户" value="default" />
            <el-option label="租户 A" value="tenant-a" />
            <el-option label="租户 B" value="tenant-b" />
          </el-select>

          <el-dropdown @command="onCommand">
            <span class="user-trigger">
              <el-avatar :size="28" :icon="UserFilled" />
              <span class="user-name">{{ auth.user?.username || '未登录' }}</span>
              <el-tag size="small" type="info" effect="plain">{{ auth.user?.role || '-' }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" :icon="User">个人中心</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { UserFilled, User, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

interface MenuItem {
  path: string
  title: string
  icon: string
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const collapsed = ref(false)
const narrowScreen = window.matchMedia('(max-width: 768px)')
const compact = ref(narrowScreen.matches)
const effectiveCollapsed = computed(() => collapsed.value || compact.value)
function updateCompact(event: MediaQueryListEvent) { compact.value = event.matches }
onMounted(() => narrowScreen.addEventListener('change', updateCompact))
onBeforeUnmount(() => narrowScreen.removeEventListener('change', updateCompact))
const tenant = computed({
  get: () => auth.tenant,
  set: (v: string) => auth.switchTenant(v),
})

const menuItems: MenuItem[] = [
  { path: '/dashboard', title: '数据看板', icon: 'DataLine' },
  { path: '/numbers', title: '号码池管理', icon: 'Iphone' },
  { path: '/register', title: '注册管理', icon: 'UserFilled' },
  { path: '/accounts', title: '账号管理', icon: 'Avatar' },
  { path: '/groups', title: '资源群管理', icon: 'ChatDotRound' },
  { path: '/mass-send', title: '群发任务', icon: 'Promotion' },
  { path: '/pull-group', title: '拉群任务', icon: 'Connection' },
  { path: '/integrations', title: '资源对接', icon: 'Link' },
  { path: '/ads', title: '广告消息管理', icon: 'Document' },
  { path: '/billing', title: '余额与计费', icon: 'Wallet' },
  { path: '/profile', title: '个人中心', icon: 'User' },
  { path: '/settings', title: '系统设置', icon: 'Setting' },
]

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => (route.meta.title as string) || '')

function onTenantChange(value: string) {
  ElMessageBox.alert(`已切换到「${value}」，后续请求将携带该租户标识。`, '租户切换', {
    confirmButtonText: '知道了',
  }).catch(() => {})
}

async function onCommand(command: string) {
  if (command === 'profile') {
    router.push({ name: 'profile' })
    return
  }
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
.layout-aside { background: var(--wa-sidebar-bg); border-right: 1px solid var(--wa-border); transition: width .2s; overflow-x: hidden; }
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
