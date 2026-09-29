<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { login } from '../api/client'
import { setAuth } from '../stores/auth'

const router = useRouter()

const form = reactive({
  username: '',
  password: '',
})
const loading = ref(false)

async function onSubmit(): Promise<void> {
  loading.value = true
  try {
    const resp = await login(form.username.trim(), form.password)
    setAuth(resp.token, resp.user)
    ElMessage.success(`欢迎，${resp.user.display_name}`)
    router.push({ name: 'home' })
  } catch (err: unknown) {
    const resp = (err as { response?: { status?: number; data?: { detail?: string } } }).response
    if (resp?.status === 401) {
      ElMessage.error('账号或密码不正确')
    } else if (resp) {
      // 服务端有明确拒绝理由（如 429 限速锁定 / 403 停用），透出原文而非误报网络故障
      ElMessage.error(resp.data?.detail ?? '登录失败，请稍后再试')
    } else {
      // 服务器地址（跨源部署）由部署者在 superadmin 后台的「前端接入地址」配置
      ElMessage.error('登录失败：无法连接服务器，请检查后端是否已启动')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <h1>新能源汽车 AI 智能诊断系统</h1>
        <span class="ver">2.0</span>
      </div>
      <p class="subtitle">多轮交互 · 可控 AI · 车主 / 店员 / 管理员三端一体</p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <!-- 不提示示例账号名：公网隧道开放下示例等于泄露有效用户名（2026-09-26 用户要求） -->
          <el-input v-model="form.username" placeholder="请输入账号" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button class="submit" type="primary" size="large" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.login-card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 2rem 1.75rem 1.5rem;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.brand h1 {
  font-size: 1.15rem;
  margin: 0;
  letter-spacing: 0.02em;
}

.ver {
  color: var(--accent);
  font-weight: 700;
  font-size: 0.95rem;
}

.subtitle {
  color: var(--muted);
  font-size: 0.75rem;
  margin: 0.4rem 0 1.5rem;
}

.submit {
  width: 100%;
  margin-top: 0.25rem;
}
</style>
