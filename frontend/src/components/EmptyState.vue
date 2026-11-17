<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  description?: string
  compact?: boolean
}>(), { title: '暂无数据', description: '', compact: false })
</script>

<template>
  <div class="empty-state" :class="{ compact }">
    <span class="glyph" aria-hidden="true">
      <svg viewBox="0 0 48 32" width="52" height="35" fill="none">
        <path d="M6 21 9.2 11h29.6L42 21" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        <path d="M4 21h40v5.6a1.4 1.4 0 0 1-1.4 1.4h-4.2a1.4 1.4 0 0 1-1.4-1.4V25H11v1.6a1.4 1.4 0 0 1-1.4 1.4H5.4A1.4 1.4 0 0 1 4 26.6V21Z" stroke="currentColor" stroke-width="1.4" />
        <circle cx="10.6" cy="24" r="1" fill="currentColor" />
        <circle cx="37.4" cy="24" r="1" fill="currentColor" />
        <path d="M18 7h12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-dasharray="2 3" />
      </svg>
    </span>
    <p class="title">{{ title }}</p>
    <p v-if="description" class="desc">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 2.4rem 1rem;
  border: 1px dashed var(--hmi-line);
  border-radius: var(--hmi-radius-lg);
  text-align: center;
  color: var(--hmi-text-3);
}

.empty-state.compact {
  padding: 1.2rem 0.8rem;
}

.glyph {
  color: var(--hmi-line-strong);
  margin-block-end: 0.2rem;
}

.title {
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-3);
  font-weight: 600;
}

.desc {
  font-size: var(--hmi-fs-2);
  max-inline-size: 44ch;
}
</style>
