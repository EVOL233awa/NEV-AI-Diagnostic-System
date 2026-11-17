<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchHealth } from '../../api/client'
import { ROLE_HOME_LABEL, type NavItem } from '../../config/navigation'
import { ROLE_LABELS, auth, logout } from '../../stores/auth'

const props = defineProps<{ items: NavItem[]; mobile?: boolean }>()
const emit = defineEmits<{ navigate: [] }>()
const route = useRoute()
const router = useRouter()
const online = ref<boolean | null>(null)

const roleLabel = computed(() => (auth.user ? ROLE_LABELS[auth.user.role] : ''))
const homeLabel = computed(() => (auth.user ? ROLE_HOME_LABEL[auth.user.role] : '工作台'))
const version = ref('')

function isActive(to: string): boolean {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}

function onLogout(): void {
  logout()
  router.push({ name: 'login' })
}

onMounted(async () => {
  try {
    const health = await fetchHealth()
    online.value = health.ok
    version.value = health.version
  } catch {
    online.value = false
  }
})
</script>

<template>
  <div class="sidenav" :class="{ 'is-mobile': props.mobile }">
    <RouterLink class="brand" to="/" aria-label="返回首页" @click="emit('navigate')">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="26" height="26" fill="none">
          <path d="M6 20.5 8.8 12h14.4L26 20.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          <path d="M4.5 20.5h23v4.2a1.3 1.3 0 0 1-1.3 1.3h-2.6a1.3 1.3 0 0 1-1.3-1.3v-1.2H10.7v1.2a1.3 1.3 0 0 1-1.3 1.3H6.8a1.3 1.3 0 0 1-1.3-1.3v-4.2Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
          <circle cx="9.6" cy="22.6" r="1.1" fill="currentColor" />
          <circle cx="22.4" cy="22.6" r="1.1" fill="currentColor" />
          <path d="M12 8.2h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </span>
      <span class="brand-text">
        <strong>NEV DIAG</strong>
        <small>新能源汽车智能诊断</small>
      </span>
    </RouterLink>

    <div class="role-card">
      <span class="role-dot" aria-hidden="true"></span>
      <div>
        <span class="role-name">{{ roleLabel }}</span>
        <span class="role-home">{{ homeLabel }}</span>
      </div>
    </div>

    <nav class="nav" aria-label="主导航">
      <RouterLink
        v-for="item in props.items"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ active: isActive(item.to) }"
        :aria-current="isActive(item.to) ? 'page' : undefined"
        @click="emit('navigate')"
      >
        <el-icon class="nav-icon" aria-hidden="true"><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="foot">
      <div class="health" role="status">
        <span class="health-dot" :class="online === false ? 'off' : online === true ? 'on' : 'wait'" aria-hidden="true"></span>
        <span>{{ online === false ? '服务离线' : online === true ? '服务正常' : '连接中' }}</span>
        <span v-if="version" class="version">v{{ version }}</span>
      </div>
      <button v-if="!props.mobile" type="button" class="logout" @click="onLogout">
        退出登录
      </button>
    </div>
  </div>
</template>

<style scoped>
.sidenav {
  display: flex;
  flex-direction: column;
  gap: var(--hmi-gap-3);
  padding: 1.1rem 0.85rem;
  block-size: 100%;
  overflow-y: auto;
}

.sidenav.is-mobile {
  background: var(--hmi-bg);
  padding-block-end: max(1.2rem, env(safe-area-inset-bottom, 0px));
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.2rem 0.35rem 0.5rem;
  color: var(--hmi-text);
}

.brand:hover {
  color: var(--hmi-text);
}

.brand-mark {
  display: grid;
  place-items: center;
  inline-size: 38px;
  block-size: 38px;
  border-radius: 11px;
  color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
  border: 1px solid var(--hmi-accent-line);
  box-shadow: 0 0 18px rgba(53, 214, 194, 0.12);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  min-inline-size: 0;
}

.brand-text strong {
  font-size: 0.95rem;
  letter-spacing: 0.08em;
}

.brand-text small {
  color: var(--hmi-text-3);
  font-size: 0.64rem;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.role-card {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface);
}

.role-dot {
  inline-size: 7px;
  block-size: 7px;
  border-radius: 50%;
  background: var(--hmi-accent);
  box-shadow: 0 0 0 4px var(--hmi-accent-soft);
  flex: none;
}

.role-card > div {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
}

.role-name {
  font-size: var(--hmi-fs-3);
  font-weight: 600;
}

.role-home {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-block-size: 40px;
  padding: 0.5rem 0.65rem;
  border-radius: var(--hmi-radius-sm);
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-3);
  border: 1px solid transparent;
  transition: background var(--hmi-dur-1) var(--hmi-ease), color var(--hmi-dur-1) var(--hmi-ease);
}

.nav-item:hover {
  background: var(--hmi-surface-2);
  color: var(--hmi-text);
}

.nav-item.active {
  color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
  border-color: var(--hmi-accent-line);
}

.nav-icon {
  font-size: 16px;
  flex: none;
}

.foot {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding-block-start: 0.5rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.health {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.health-dot {
  inline-size: 6px;
  block-size: 6px;
  border-radius: 50%;
  background: var(--hmi-muted);
}

.health-dot.on {
  background: var(--hmi-ok);
}

.health-dot.off {
  background: var(--hmi-danger);
}

.health-dot.wait {
  background: var(--hmi-warn);
}

.version {
  margin-inline-start: auto;
  font-family: var(--hmi-font-mono);
}

.logout {
  min-block-size: 36px;
  border-radius: var(--hmi-radius-sm);
  border: 1px solid var(--hmi-line);
  background: transparent;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  cursor: pointer;
}

.logout:hover {
  color: var(--hmi-danger);
  border-color: rgba(255, 116, 116, 0.4);
}

@media (pointer: coarse) {
  .nav-item,
  .logout {
    min-block-size: 44px;
  }
}
</style>
