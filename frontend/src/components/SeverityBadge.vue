<script setup lang="ts">
import { computed } from 'vue'
import { SEVERITY_LABEL } from '../api/client'
import StatusChip from './StatusChip.vue'
import type { ChipTone } from './ui-types'

const props = defineProps<{ severity: string; compact?: boolean }>()

const tone = computed<ChipTone>(() => {
  if (props.severity === 'red') return 'danger'
  if (props.severity === 'yellow') return 'warn'
  if (props.severity === 'green') return 'ok'
  return 'neutral'
})

const label = computed(() => {
  if (props.compact) {
    if (props.severity === 'red') return '红'
    if (props.severity === 'yellow') return '黄'
    if (props.severity === 'green') return '绿'
    return '—'
  }
  return SEVERITY_LABEL[props.severity] ?? '未评估'
})
</script>

<template>
  <StatusChip :label="label" :tone="tone" dot />
</template>
