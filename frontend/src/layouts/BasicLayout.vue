<template>
  <el-container class="layout-root">
    <el-aside :width="collapsed ? '64px' : '220px'" class="layout-aside">
      <div class="logo">
        <el-icon :size="24" color="#25d366"><ChatDotRound /></el-icon>
        <span v-show="!collapsed" class="logo-text">WhatsApp 运营</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        background-color="#1f2d3d"
        text-color="#bfcbd9"
        active-text-color="#25d366"
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
          <el-icon class="collapse-btn" :size="20" @click="collapsed = !collapsed">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
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
import { computed, ref } from 'vue'
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
.layout-root {
  height: 100vh;
}

.layout-aside {
  background: #1f2d3d;
  transition: width 0.2s;
  overflow-x: hidden;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  color: #fff;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.layout-aside :deep(.el-menu) {
  border-right: none;
}

.layout-header {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  cursor: pointer;
  color: #606266;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.tenant-select {
  width: 130px;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}

.user-name {
  font-size: 14px;
  color: #303133;
}

.layout-main {
  /* 皮肤纹理：background-attachment 默认 scroll，滚动时纹理固定不随内容移动 */
  background-color: var(--wa-skin-base);
  background-image: var(--wa-skin-image);
  background-repeat: repeat-y;
  background-position: top center;
  background-size: 100% auto;
  padding: 0;
  overflow-y: auto;
}
</style>
