<script setup lang="ts">
import { computed } from 'vue'
import type { ChipTone } from './ui-types'

const props = withDefaults(defineProps<{
  points: number[]
  label?: string
  tone?: ChipTone
  width?: number
  height?: number
}>(), { label: '趋势', tone: 'accent', width: 140, height: 40 })

const color = computed(() => {
  if (props.tone === 'ok') return 'var(--hmi-ok)'
  if (props.tone === 'warn') return 'var(--hmi-warn)'
  if (props.tone === 'danger') return 'var(--hmi-danger)'
  if (props.tone === 'info') return 'var(--hmi-info)'
  if (props.tone === 'neutral') return 'var(--hmi-text-3)'
  return 'var(--hmi-accent)'
})

const geometry = computed(() => {
  const values = props.points.length ? props.points : [0, 0]
  const max = Math.max(...values)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const pad = 3
  const innerW = props.width - pad * 2
  const innerH = props.height - pad * 2
  const coords = values.map((value, index) => {
    const x = pad + (values.length === 1 ? innerW / 2 : (index / (values.length - 1)) * innerW)
    const y = pad + innerH - ((value - min) / span) * innerH
    return [Number(x.toFixed(2)), Number(y.toFixed(2))] as const
  })
  const line = coords.map(([x, y]) => `${x},${y}`).join(' ')
  const area = `M${coords[0][0]},${props.height - pad} L${line.split(' ').join(' L')} L${coords[coords.length - 1][0]},${props.height - pad} Z`
  return { line, area }
})
</script>

<template>
  <svg
    class="spark"
    :viewBox="`0 0 ${width} ${height}`"
    :width="width"
    :height="height"
    role="img"
    :aria-label="label"
    preserveAspectRatio="none"
  >
    <path :d="geometry.area" :fill="color" opacity="0.10" />
    <polyline
      :points="geometry.line"
      fill="none"
      :stroke="color"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<style scoped>
.spark {
  display: block;
  max-inline-size: 100%;
}
</style>
