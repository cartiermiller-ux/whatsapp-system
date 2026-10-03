<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon :size="36" color="#25d366"><ChatDotRound /></el-icon>
        <h1>WhatsApp 运营系统</h1>
        <p class="muted">号码 · 注册 · 账号 · 群发 一体化控制台</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
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
          size="large"
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
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 与后台一致：皮肤底色 + 纹理平铺 */
  background-color: var(--wa-skin-base);
  background-image: var(--wa-skin-image);
  background-repeat: repeat-y;
  background-position: top center;
  background-size: 100% auto;
}

.login-card {
  width: 400px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(2px);
  border: 1px solid rgba(31, 45, 61, 0.06);
  border-radius: 14px;
  padding: 36px 32px 28px;
  box-shadow: 0 12px 40px rgba(31, 45, 61, 0.12);
}

.brand {
  text-align: center;
  margin-bottom: 24px;
}

.brand h1 {
  margin: 10px 0 4px;
  font-size: 20px;
  color: var(--wa-text);
  letter-spacing: 0.5px;
}

.brand p {
  margin: 0;
  font-size: 13px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.submit {
  width: 100%;
  margin-top: 10px;
}

.tip {
  margin: 14px 0 0;
  font-size: 12px;
  text-align: center;
}
</style>