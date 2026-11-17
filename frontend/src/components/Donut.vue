<script setup lang="ts">
import { computed } from 'vue'
import type { DonutSegment } from './ui-types'

const props = withDefaults(defineProps<{
  segments: DonutSegment[]
  totalLabel?: string
  size?: number
}>(), { totalLabel: '合计', size: 132 })

const R = 42
const CIRC = 2 * Math.PI * R

const total = computed(() => props.segments.reduce((sum, item) => sum + Math.max(0, item.value), 0))

const arcs = computed(() => {
  let consumed = 0
  return props.segments
    .filter((item) => item.value > 0)
    .map((item) => {
      const length = (item.value / (total.value || 1)) * CIRC
      const arc = {
        ...item,
        length,
        offset: -consumed,
      }
      consumed += length
      return arc
    })
})

function colorOf(tone?: string): string {
  if (tone === 'ok') return 'var(--hmi-ok)'
  if (tone === 'warn') return 'var(--hmi-warn)'
  if (tone === 'danger') return 'var(--hmi-danger)'
  if (tone === 'info') return 'var(--hmi-info)'
  if (tone === 'neutral') return 'var(--hmi-text-3)'
  return 'var(--hmi-accent)'
}
</script>

<template>
  <div class="donut" :style="{ '--donut-size': `${size}px` }">
    <div class="ring">
      <svg viewBox="0 0 100 100" role="img" :aria-label="`${totalLabel} ${total}`">
        <circle cx="50" cy="50" :r="R" fill="none" stroke="var(--hmi-line)" stroke-width="11" />
        <circle
          v-for="(arc, index) in arcs"
          :key="index"
          cx="50"
          cy="50"
          :r="R"
          fill="none"
          :stroke="colorOf(arc.tone)"
          stroke-width="11"
          :stroke-dasharray="`${arc.length} ${CIRC - arc.length}`"
          :stroke-dashoffset="arc.offset"
          transform="rotate(-90 50 50)"
        />
      </svg>
      <div class="center">
        <strong class="hmi-mono">{{ total }}</strong>
        <span>{{ totalLabel }}</span>
      </div>
    </div>
    <ul class="legend">
      <li v-for="(item, index) in segments" :key="index">
        <span class="dot" :style="{ background: colorOf(item.tone) }" aria-hidden="true"></span>
        <span class="name">{{ item.label }}</span>
        <span class="value hmi-mono">{{ item.value }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.donut {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.ring {
  position: relative;
  inline-size: var(--donut-size);
  block-size: var(--donut-size);
  flex: none;
}

.ring svg {
  inline-size: 100%;
  block-size: 100%;
}

.center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  pointer-events: none;
}

.center strong {
  font-size: 1.3rem;
  color: var(--hmi-text);
  line-height: 1;
}

.center span {
  color: var(--hmi-text-3);
  font-size: 0.64rem;
}

.legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-inline-size: 120px;
}

.legend li {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.dot {
  inline-size: 7px;
  block-size: 7px;
  border-radius: 2px;
  flex: none;
}

.name {
  min-inline-size: 0;
}

.value {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}
</style>
