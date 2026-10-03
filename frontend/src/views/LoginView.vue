<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon :size="28" color="#303030"><ChatDotRound /></el-icon>
        <h1>WhatsApp 运营系统</h1>
        <p class="muted">号码 · 注册 · 账号 · 群发 一体化控制台</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="default" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-form-item>
          <el-select v-model="form.tenant" style="width: 100%" placeholder="选择租户">
            <el-option label="默认租户" value="default" />
            <el-option label="租户 A" value="tenant-a" />
            <el-option label="租户 B" value="tenant-b" />
          </el-select>
        </el-form-item>

        <div class="row">
          <el-checkbox v-model="form.remember">记住我</el-checkbox>
          <el-link type="primary" :underline="false" @click="onForgot">忘记密码？</el-link>
        </div>

        <el-button
          type="primary"
          size="default"
          class="submit"
          :loading="loading"
          @click="onSubmit"
        >
          登 录
        </el-button>
      </el-form>

      <p class="tip muted">
        内置管理员：admin / admin123；使用其他用户名首次登录会自动开户。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  tenant: 'default',
  remember: false,
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await auth.login({ ...form })
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.replace(redirect)
  } catch {
    /* 失败原因由 axios 拦截器统一提示（如：用户名或密码错误） */
  } finally {
    loading.value = false
  }
}

function onForgot() {
  ElMessage.info('密码找回功能待后端接口接入')
}
</script>

<style scoped>
.login-page { min-height: 100vh; min-height: 100dvh; padding: 24px 16px; display: flex; align-items: center; justify-content: center; background: var(--wa-bg); }
.login-card { width: 360px; max-width: 100%; background: var(--wa-surface); border: 1px solid var(--wa-border); border-radius: 16px; padding: 28px 24px 24px; }
.brand { text-align: center; margin-bottom: 24px; }
.brand h1 { margin: 12px 0 8px; font-size: 20px; font-weight: 600; color: var(--wa-text); letter-spacing: -.4px; }
.brand p { margin: 0; font-size: 12px; }
.row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.submit { width: 100%; height: 36px; margin-top: 8px; border-radius: 18px; }
.tip { margin: 16px 0 0; font-size: 12px; text-align: center; line-height: 1.5; }
</style>
