<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_BY_ROLE, titleForPath } from '../../config/navigation'
import { auth } from '../../stores/auth'
import MobileTabBar from './MobileTabBar.vue'
import SideNav from './SideNav.vue'
import TopBar from './TopBar.vue'

const route = useRoute()
const drawerOpen = defineModel<boolean>('drawerOpen', { default: false })

const items = computed(() => (auth.user ? NAV_BY_ROLE[auth.user.role] : []))
const isChat = computed(() => route.path === '/chat')
</script>

<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <div class="shell">
    <SideNav class="shell__nav" :items="items" />
    <div class="shell__body">
      <TopBar :title="titleForPath(route.path)" :nav-open="drawerOpen" @open-nav="drawerOpen = true" />
      <main id="main-content" class="shell__content" :class="{ 'is-chat': isChat }" tabindex="-1">
        <slot />
      </main>
    </div>
    <MobileTabBar class="shell__tabbar" :items="items" />
    <el-drawer
      v-model="drawerOpen"
      direction="ltr"
      size="280px"
      :with-header="false"
      class="nav-drawer"
      aria-label="主导航"
    >
      <SideNav :items="items" mobile @navigate="drawerOpen = false" />
    </el-drawer>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-block-size: 100vh;
  min-block-size: 100dvh;
}

.shell__nav {
  flex: 0 0 var(--hmi-sidenav-w);
  inline-size: var(--hmi-sidenav-w);
  position: sticky;
  inset-block-start: 0;
  block-size: 100vh;
  block-size: 100dvh;
  border-inline-end: 1px solid var(--hmi-line);
  background: rgba(9, 15, 19, 0.82);
  backdrop-filter: blur(10px);
  z-index: 20;
}

.shell__body {
  flex: 1 1 auto;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  min-block-size: 100vh;
  min-block-size: 100dvh;
}

.shell__content {
  flex: 1 1 auto;
  min-inline-size: 0;
}

.shell__content.is-chat {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

@media (max-width: 1023px) {
  .shell__nav {
    display: none;
  }

  .shell__content {
    padding-block-end: var(--hmi-tabbar-h);
  }

  .shell__content.is-chat {
    padding-block-end: 0;
  }
}

@media (min-width: 1024px) {
  .shell__tabbar {
    display: none;
  }
}
</style>

<style>
.nav-drawer .el-drawer__body {
  padding: 0;
}

.nav-drawer .el-drawer {
  background: var(--hmi-bg);
}
</style>
