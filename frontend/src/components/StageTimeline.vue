<script setup lang="ts">
import { computed } from 'vue'
import { DIAG_STAGE_LABEL, fmtIso } from '../api/client'
import type { ChipTone, StageStep } from './ui-types'

const props = defineProps<{ history: StageStep[]; inferred?: boolean }>()

const toneOf = (stage: string): ChipTone => {
  if (stage === 'conclusion') return 'ok'
  if (stage === 'verification') return 'accent'
  if (stage === 'hypothesis') return 'warn'
  return 'neutral'
}

const steps = computed(() => props.history.filter((item) => item.stage in DIAG_STAGE_LABEL))
</script>

<template>
  <div class="timeline">
    <ol class="steps">
      <li
        v-for="(item, index) in steps"
        :key="`${item.stage}-${index}`"
        class="step"
        :data-tone="toneOf(item.stage)"
        :aria-current="index === steps.length - 1 ? 'step' : undefined"
      >
        <span class="marker" aria-hidden="true">{{ index + 1 }}</span>
        <div class="text">
          <span class="name">{{ DIAG_STAGE_LABEL[item.stage] ?? item.stage }}</span>
          <span v-if="item.at" class="at">{{ fmtIso(item.at) }}</span>
        </div>
      </li>
    </ol>
    <span v-if="inferred" class="inferred">阶段由消息形状推断</span>
  </div>
</template>

<style scoped>
.timeline {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.steps {
  display: flex;
  align-items: center;
  gap: 0;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-wrap: wrap;
}

.step {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding-inline-end: 1.15rem;
}

.step:not(:last-child)::after {
  content: '';
  position: absolute;
  inset-inline-end: 0.25rem;
  inline-size: 0.55rem;
  block-size: 1px;
  background: var(--hmi-line-strong);
}

.marker {
  display: grid;
  place-items: center;
  inline-size: 20px;
  block-size: 20px;
  border-radius: 50%;
  border: 1px solid var(--hmi-line-strong);
  background: var(--hmi-surface-2);
  color: var(--hmi-text-3);
  font-size: 10px;
  font-family: var(--hmi-font-mono);
}

.step[data-tone='accent'] .marker { border-color: var(--hmi-accent-line); color: var(--hmi-accent); background: var(--hmi-accent-soft); }
.step[data-tone='ok'] .marker { border-color: rgba(70, 214, 143, 0.4); color: var(--hmi-ok); background: var(--hmi-ok-soft); }
.step[data-tone='warn'] .marker { border-color: rgba(242, 179, 77, 0.4); color: var(--hmi-warn); background: var(--hmi-warn-soft); }

.text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.name {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.step[aria-current='step'] .name {
  color: var(--hmi-text);
  font-weight: 600;
}

.at {
  color: var(--hmi-text-3);
  font-size: 0.62rem;
  font-family: var(--hmi-font-mono);
}

.inferred {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}
</style>
