<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { MoreFilled } from '@element-plus/icons-vue'
import type { NavItem } from '../../config/navigation'
import Sheet from '../Sheet.vue'

const props = defineProps<{ items: NavItem[] }>()
const route = useRoute()
const moreOpen = ref(false)

const primary = computed(() => props.items.filter((item) => item.mobile).slice(0, 4))
const overflow = computed(() => props.items.filter((item) => !primary.value.includes(item)))

function isActive(to: string): boolean {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}
</script>

<template>
  <nav class="tabbar" aria-label="移动端主导航">
    <RouterLink
      v-for="item in primary"
      :key="item.to"
      :to="item.to"
      class="tab"
      :class="{ active: isActive(item.to) }"
      :aria-current="isActive(item.to) ? 'page' : undefined"
    >
      <el-icon class="tab-icon" aria-hidden="true"><component :is="item.icon" /></el-icon>
      <span>{{ item.label }}</span>
    </RouterLink>

    <button
      v-if="overflow.length"
      type="button"
      class="tab tab-button"
      :class="{ active: overflow.some((item) => isActive(item.to)) }"
      :aria-expanded="moreOpen"
      aria-label="更多导航"
      @click="moreOpen = true"
    >
      <el-icon class="tab-icon" aria-hidden="true"><MoreFilled /></el-icon>
      <span>更多</span>
    </button>

    <Sheet v-model="moreOpen" title="更多功能" size="auto">
      <nav class="more-list" aria-label="更多导航">
        <RouterLink
          v-for="item in overflow"
          :key="item.to"
          :to="item.to"
          class="more-item"
          :class="{ active: isActive(item.to) }"
          :aria-current="isActive(item.to) ? 'page' : undefined"
          @click="moreOpen = false"
        >
          <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </Sheet>
  </nav>
</template>

<style scoped>
.tabbar {
  position: fixed;
  inset-inline: 0;
  inset-block-end: 0;
  z-index: 30;
  display: flex;
  align-items: stretch;
  justify-content: space-around;
  min-block-size: var(--hmi-tabbar-h);
  padding-block-end: env(safe-area-inset-bottom, 0px);
  border-block-start: 1px solid var(--hmi-line);
  background: rgba(9, 15, 19, 0.94);
  backdrop-filter: blur(14px);
}

.tab {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-inline-size: 0;
  min-block-size: var(--hmi-tabbar-h);
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  border: 0;
  background: transparent;
  cursor: pointer;
}

.tab:hover {
  color: var(--hmi-text-2);
}

.tab.active {
  color: var(--hmi-accent);
}

.tab:focus-visible {
  outline-offset: -3px;
}

.tab-icon {
  font-size: 20px;
}

.tab-button {
  font-family: inherit;
}

.more-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.more-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  min-block-size: 48px;
  padding: 0.55rem 0.7rem;
  border-radius: var(--hmi-radius);
  border: 1px solid var(--hmi-line-soft);
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-4);
}

.more-item.active {
  color: var(--hmi-accent);
  border-color: var(--hmi-accent-line);
  background: var(--hmi-accent-soft);
}
</style>
