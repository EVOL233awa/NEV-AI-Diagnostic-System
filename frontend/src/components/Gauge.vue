<script setup lang="ts">
import { computed } from 'vue'
import type { ChipTone } from './ui-types'

const props = withDefaults(defineProps<{
  value: number
  label: string
  hint?: string
  tone?: ChipTone
  size?: number
}>(), { hint: '', tone: 'accent', size: 120 })

const radius = computed(() => props.size / 2 - 8)
const circumference = computed(() => 2 * Math.PI * radius.value)
const ratio = computed(() => Math.max(0, Math.min(1, props.value)))
const dash = computed(() => `${circumference.value * ratio.value} ${circumference.value}`)
const color = computed(() => {
  if (props.tone === 'ok') return 'var(--hmi-ok)'
  if (props.tone === 'warn') return 'var(--hmi-warn)'
  if (props.tone === 'danger') return 'var(--hmi-danger)'
  if (props.tone === 'info') return 'var(--hmi-info)'
  if (props.tone === 'neutral') return 'var(--hmi-text-3)'
  return 'var(--hmi-accent)'
})
const percent = computed(() => Math.round(ratio.value * 100))
</script>

<template>
  <figure class="gauge" :style="{ '--gauge-size': `${size}px` }">
    <svg
      :viewBox="`0 0 ${size} ${size}`"
      role="img"
      :aria-label="`${label}：${percent}%`"
    >
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        stroke="var(--hmi-line)"
        stroke-width="8"
      />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color"
        stroke-width="8"
        stroke-linecap="round"
        :stroke-dasharray="dash"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"
      />
    </svg>
    <div class="center">
      <strong class="hmi-mono">{{ percent }}<small>%</small></strong>
      <span class="label">{{ label }}</span>
    </div>
    <figcaption v-if="hint" class="hint">{{ hint }}</figcaption>
  </figure>
</template>

<style scoped>
.gauge {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
  margin: 0;
}

svg {
  inline-size: var(--gauge-size);
  block-size: var(--gauge-size);
}

.center {
  position: absolute;
  inset-block-start: 0;
  block-size: var(--gauge-size);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.center strong {
  font-size: 1.25rem;
  color: var(--hmi-text);
  line-height: 1;
}

.center small {
  font-size: 0.65rem;
  color: var(--hmi-text-3);
  margin-inline-start: 1px;
}

.label {
  margin-block-start: 0.2rem;
  color: var(--hmi-text-3);
  font-size: 0.66rem;
}

.hint {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  text-align: center;
}
</style>
