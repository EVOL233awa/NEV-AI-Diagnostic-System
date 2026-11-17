<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown, Menu, SwitchButton } from '@element-plus/icons-vue'
import { fetchHealth } from '../../api/client'
import { ROLE_LABELS, auth, logout } from '../../stores/auth'

const props = defineProps<{ title: string; navOpen: boolean }>()
const emit = defineEmits<{ 'open-nav': [] }>()
const router = useRouter()
const online = ref<boolean | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const roleLabel = computed(() => (auth.user ? ROLE_LABELS[auth.user.role] : ''))
const initials = computed(() => (auth.user?.display_name || auth.user?.username || '?').slice(0, 1).toUpperCase())

async function checkHealth(): Promise<void> {
  try {
    const health = await fetchHealth()
    online.value = health.ok
  } catch {
    online.value = false
  }
}

function onCommand(command: string): void {
  if (command === 'settings') {
    router.push('/settings')
    return
  }
  if (command === 'logout') {
    logout()
    router.push({ name: 'login' })
  }
}

onMounted(() => {
  void checkHealth()
  timer = setInterval(checkHealth, 60000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <header class="topbar">
    <button
      type="button"
      class="menu-btn"
      aria-label="打开导航菜单"
      :aria-expanded="props.navOpen"
      @click="emit('open-nav')"
    >
      <el-icon :size="20" aria-hidden="true"><Menu /></el-icon>
    </button>

    <div class="titles">
      <h1>{{ title }}</h1>
      <span class="crumb">NEV DIAG / {{ roleLabel }}</span>
    </div>

    <div class="right">
      <span
        class="status"
        role="status"
        :aria-label="online === false ? '后端离线' : online === true ? '后端连接正常' : '正在连接后端'"
        :title="online === false ? '后端健康检查失败' : '后端连接正常'"
      >
        <span class="dot" :class="online === false ? 'off' : online === true ? 'on' : 'wait'" aria-hidden="true"></span>
        <span class="status-text">{{ online === false ? '离线' : online === true ? '在线' : '连接中' }}</span>
      </span>

      <el-dropdown trigger="click" @command="onCommand">
        <button type="button" class="user" aria-label="账户菜单">
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="user-text">
            <strong>{{ auth.user?.display_name || auth.user?.username }}</strong>
            <small>{{ roleLabel }}</small>
          </span>
          <el-icon class="chev" aria-hidden="true"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="settings">账户设置</el-dropdown-item>
            <el-dropdown-item command="logout" divided :icon="SwitchButton">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  inset-block-start: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  gap: 0.8rem;
  min-block-size: var(--hmi-topbar-h);
  padding: 0.5rem clamp(0.75rem, 2vw, 1.4rem);
  border-block-end: 1px solid var(--hmi-line);
  background: var(--hmi-chrome-bg);
  backdrop-filter: blur(12px);
}

.menu-btn {
  display: none;
  place-items: center;
  inline-size: 40px;
  block-size: 40px;
  border-radius: var(--hmi-radius-sm);
  border: 1px solid var(--hmi-line);
  background: var(--hmi-surface);
  color: var(--hmi-text-2);
  cursor: pointer;
}

.menu-btn:hover {
  color: var(--hmi-text);
  border-color: var(--hmi-line-strong);
}

.titles {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
}

.titles h1 {
  font-size: var(--hmi-fs-5);
  font-weight: 650;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.crumb {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.right {
  margin-inline-start: auto;
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.28rem 0.55rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: 999px;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  background: var(--hmi-surface);
}

.dot {
  inline-size: 6px;
  block-size: 6px;
  border-radius: 50%;
  background: var(--hmi-muted);
}

.dot.on {
  background: var(--hmi-ok);
  box-shadow: 0 0 6px rgba(70, 214, 143, 0.7);
}

.dot.off {
  background: var(--hmi-danger);
}

.dot.wait {
  background: var(--hmi-warn);
}

.user {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.45rem 0.25rem 0.25rem;
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  background: var(--hmi-surface);
  color: var(--hmi-text);
  cursor: pointer;
}

.user:hover {
  border-color: var(--hmi-line-strong);
}

.avatar {
  display: grid;
  place-items: center;
  inline-size: 30px;
  block-size: 30px;
  border-radius: 50%;
  background: var(--hmi-accent-soft);
  color: var(--hmi-accent);
  font-weight: 700;
  font-size: 0.8rem;
}

.user-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.15;
  max-inline-size: 130px;
}

.user-text strong {
  font-size: var(--hmi-fs-2);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-text small {
  color: var(--hmi-text-3);
  font-size: 0.65rem;
}

.chev {
  color: var(--hmi-text-3);
  font-size: 12px;
}

@media (max-width: 1023px) {
  .menu-btn {
    display: grid;
  }
}

@media (max-width: 640px) {
  .crumb,
  .status-text,
  .user-text small {
    display: none;
  }

  .user-text {
    max-inline-size: 80px;
  }

  .topbar {
    gap: 0.5rem;
  }
}
</style>
