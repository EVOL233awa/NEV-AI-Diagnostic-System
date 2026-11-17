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
const errorText = ref('')

async function onSubmit(): Promise<void> {
  if (!form.username.trim() || !form.password) {
    errorText.value = '请输入账号与密码'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    const resp = await login(form.username.trim(), form.password)
    setAuth(resp.token, resp.user)
    ElMessage.success(`欢迎，${resp.user.display_name}`)
    router.push({ name: 'home' })
  } catch (err: unknown) {
    const resp = (err as { response?: { status?: number; data?: { detail?: string } } }).response
    if (resp?.status === 401) {
      errorText.value = '账号或密码不正确'
    } else if (resp) {
      // 服务端有明确拒绝理由（如 429 限速锁定 / 403 停用），透出原文而非误报网络故障
      errorText.value = resp.data?.detail ?? '登录失败，请稍后再试'
    } else {
      errorText.value = '无法连接服务器，请确认后端已启动'
    }
    ElMessage.error(errorText.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="intro">
      <div class="intro-grid" aria-hidden="true"></div>
      <svg class="line-car" viewBox="0 0 640 300" fill="none" aria-hidden="true">
        <path d="M64 208 112 108h416l48 100" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        <path d="M40 208h560v52a10 10 0 0 1-10 10h-44a10 10 0 0 1-10-10v-16H104v16a10 10 0 0 1-10 10H50a10 10 0 0 1-10-10v-52Z" stroke="currentColor" stroke-width="1.5" />
        <path d="M144 108 176 58h288l32 50" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 8" />
        <circle cx="124" cy="238" r="12" stroke="currentColor" stroke-width="1.5" />
        <circle cx="516" cy="238" r="12" stroke="currentColor" stroke-width="1.5" />
        <path d="M200 208h240M280 108v100M360 108v100" stroke="currentColor" stroke-width="1" opacity=".45" />
        <path d="M72 160h56M512 160h56" stroke="currentColor" stroke-width="3" stroke-linecap="round" opacity=".7" />
      </svg>

      <div class="intro-copy">
        <div class="logo-row">
          <span class="logo-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28" fill="none">
              <path d="M6 20.5 8.8 12h14.4L26 20.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              <path d="M4.5 20.5h23v4.2a1.3 1.3 0 0 1-1.3 1.3h-2.6a1.3 1.3 0 0 1-1.3-1.3v-1.2H10.7v1.2a1.3 1.3 0 0 1-1.3 1.3H6.8a1.3 1.3 0 0 1-1.3-1.3v-4.2Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="logo-text">NEV DIAG <small>2.1</small></span>
        </div>
        <h1>新能源汽车<br />AI 智能诊断系统</h1>
        <p class="lede">多轮问诊 · 知识库与网页取证 · 到店闭环</p>
        <ul class="roles">
          <li><strong>车主</strong><span>描述症状、语音输入、查看诊断与预约</span></li>
          <li><strong>服务顾问</strong><span>工单队列、车辆档案、故障码速查</span></li>
          <li><strong>管理员</strong><span>诊断质控、证据链、知识库与统计</span></li>
        </ul>
      </div>
    </section>

    <section class="panel">
      <h1 class="mobile-brand">NEV DIAG <small>2.1</small></h1>
      <div class="login-card hmi-card">
        <div class="card-head">
          <h2>登录</h2>
          <span class="hmi-sub">使用门店分配的账号</span>
        </div>

        <el-form label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="账号">
            <el-input
              v-model="form.username"
              placeholder="请输入账号"
              autocomplete="username"
              size="large"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              size="large"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <p v-if="errorText" class="error" role="alert">{{ errorText }}</p>
          <el-button class="submit" type="primary" size="large" :loading="loading" @click="onSubmit">
            登 录
          </el-button>
        </el-form>

        <p class="foot">登录即表示同意遵守门店数据与隐私管理规范</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-block-size: 100vh;
  min-block-size: 100dvh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
}

.intro {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: flex-end;
  padding: clamp(2rem, 5vw, 4rem);
  border-inline-end: 1px solid var(--hmi-line);
  background:
    radial-gradient(ellipse 70% 60% at 18% 18%, rgba(53, 214, 194, 0.16), transparent 62%),
    radial-gradient(ellipse 60% 50% at 88% 80%, rgba(71, 137, 255, 0.12), transparent 60%),
    linear-gradient(160deg, #0a1216, #070b0e 70%);
  color: var(--hmi-text);
}

.intro-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--hmi-line-soft) 1px, transparent 1px),
    linear-gradient(90deg, var(--hmi-line-soft) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(ellipse 80% 70% at 40% 30%, #000 30%, transparent 78%);
  opacity: 0.55;
}

.line-car {
  position: absolute;
  inset-inline: 2%;
  inset-block-start: 16%;
  inline-size: 96%;
  color: rgba(118, 168, 180, 0.28);
}

.intro-copy {
  position: relative;
  z-index: 1;
  max-inline-size: 560px;
}

.logo-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-block-end: 1.4rem;
}

.logo-mark {
  display: grid;
  place-items: center;
  inline-size: 40px;
  block-size: 40px;
  border-radius: 12px;
  color: var(--hmi-accent);
  border: 1px solid var(--hmi-accent-line);
  background: var(--hmi-accent-soft);
}

.logo-text {
  font-weight: 700;
  letter-spacing: 0.12em;
  font-size: 0.95rem;
}

.logo-text small {
  color: var(--hmi-accent);
  font-family: var(--hmi-font-mono);
  font-size: 0.7rem;
  margin-inline-start: 0.2rem;
}

.intro-copy h1 {
  font-size: clamp(1.8rem, 3.6vw, 3rem);
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 1.15;
}

.lede {
  margin-block-start: 0.9rem;
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-4);
}

.roles {
  list-style: none;
  margin: 1.8rem 0 0;
  padding: 0;
  display: grid;
  gap: 0.55rem;
}

.roles li {
  display: flex;
  align-items: baseline;
  gap: 0.7rem;
  padding: 0.5rem 0.7rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: rgba(15, 23, 29, 0.6);
  font-size: var(--hmi-fs-2);
}

.roles strong {
  min-inline-size: 4.5em;
  color: var(--hmi-accent);
  font-weight: 600;
}

.roles span {
  color: var(--hmi-text-3);
}

.panel {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: clamp(1.5rem, 4vw, 3rem);
  background:
    radial-gradient(ellipse 90% 50% at 50% 0%, rgba(53, 214, 194, 0.05), transparent 60%),
    var(--hmi-bg);
}

.mobile-brand {
  display: none;
}

.login-card {
  inline-size: 100%;
  max-inline-size: 400px;
  padding: 1.8rem 1.6rem 1.4rem;
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin-block-end: 1.2rem;
}

.card-head h2 {
  font-size: 1.35rem;
  font-weight: 650;
}

.submit {
  inline-size: 100%;
  margin-block-start: 0.35rem;
}

.error {
  margin: 0 0 0.5rem;
  color: var(--hmi-danger);
  font-size: var(--hmi-fs-2);
}

.foot {
  margin-block-start: 1rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  text-align: center;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .intro {
    display: none;
  }

  .mobile-brand {
    position: absolute;
    inset-block-start: clamp(1.8rem, 10vh, 4rem);
    inset-inline: 0;
    display: block;
    text-align: center;
    font-size: 1rem;
    letter-spacing: 0.18em;
    color: var(--hmi-text-2);
  }

  .mobile-brand small {
    color: var(--hmi-accent);
    font-size: 0.7rem;
    letter-spacing: 0.08em;
  }

  .panel {
    min-block-size: 100vh;
    min-block-size: 100dvh;
  }
}
</style>
