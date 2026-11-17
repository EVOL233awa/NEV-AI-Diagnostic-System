<script setup lang="ts">
import type { ChipTone } from './ui-types'

withDefaults(defineProps<{
  label: string
  tone?: ChipTone
  dot?: boolean
}>(), { tone: 'neutral', dot: false })
</script>

<template>
  <span class="chip" :data-tone="tone">
    <span v-if="dot" class="dot" aria-hidden="true"></span>
    {{ label }}
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.16rem 0.5rem;
  border-radius: 999px;
  border: 1px solid var(--hmi-line);
  background: var(--hmi-neutral-soft);
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-1);
  font-weight: 550;
  line-height: 1.6;
  white-space: nowrap;
}

.dot {
  inline-size: 5px;
  block-size: 5px;
  border-radius: 50%;
  background: currentColor;
}

.chip[data-tone='accent'] {
  color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
  border-color: var(--hmi-accent-line);
}

.chip[data-tone='ok'] {
  color: var(--hmi-ok);
  background: var(--hmi-ok-soft);
  border-color: rgba(70, 214, 143, 0.32);
}

.chip[data-tone='warn'] {
  color: var(--hmi-warn);
  background: var(--hmi-warn-soft);
  border-color: rgba(242, 179, 77, 0.32);
}

.chip[data-tone='danger'] {
  color: var(--hmi-danger);
  background: var(--hmi-danger-soft);
  border-color: rgba(255, 116, 116, 0.32);
}

.chip[data-tone='info'] {
  color: var(--hmi-info);
  background: var(--hmi-info-soft);
  border-color: rgba(90, 169, 255, 0.32);
}
</style>
