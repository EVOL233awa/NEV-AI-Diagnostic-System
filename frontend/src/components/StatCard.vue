<script setup lang="ts">
type Tone = 'default' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

withDefaults(defineProps<{
  label: string
  value: string | number
  hint?: string
  tone?: Tone
  suffix?: string
}>(), { tone: 'default', hint: '', suffix: '' })
</script>

<template>
  <div class="stat-card" :data-tone="tone">
    <div class="head">
      <span class="label">{{ label }}</span>
      <slot name="icon" />
    </div>
    <div class="value hmi-mono">
      {{ value }}<span v-if="suffix" class="suffix">{{ suffix }}</span>
    </div>
    <p v-if="hint" class="hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.stat-card {
  position: relative;
  overflow: hidden;
  padding: 0.85rem 0.95rem;
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius-lg);
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.025), transparent 55%), var(--hmi-surface);
  box-shadow: var(--hmi-shadow-1);
}

.stat-card::after {
  content: '';
  position: absolute;
  inset-block-start: 0;
  inset-inline: 0;
  block-size: 2px;
  background: var(--hmi-line-strong);
  opacity: 0.5;
}

.stat-card[data-tone='accent']::after { background: var(--hmi-accent); opacity: 1; }
.stat-card[data-tone='ok']::after { background: var(--hmi-ok); opacity: 1; }
.stat-card[data-tone='warn']::after { background: var(--hmi-warn); opacity: 1; }
.stat-card[data-tone='danger']::after { background: var(--hmi-danger); opacity: 1; }
.stat-card[data-tone='info']::after { background: var(--hmi-info); opacity: 1; }

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  color: var(--hmi-text-3);
}

.label {
  font-size: var(--hmi-fs-2);
  letter-spacing: 0.02em;
}

.value {
  margin-block-start: 0.4rem;
  font-size: clamp(1.45rem, 2.6vw, 1.9rem);
  font-weight: 650;
  line-height: 1.1;
  color: var(--hmi-text);
  font-variant-numeric: tabular-nums;
}

.suffix {
  margin-inline-start: 0.2rem;
  font-size: var(--hmi-fs-3);
  color: var(--hmi-text-3);
  font-weight: 500;
}

.hint {
  margin-block-start: 0.3rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.stat-card[data-tone='danger'] .value { color: var(--hmi-danger); }
.stat-card[data-tone='warn'] .value { color: var(--hmi-warn); }
.stat-card[data-tone='ok'] .value { color: var(--hmi-ok); }
.stat-card[data-tone='accent'] .value { color: var(--hmi-accent); }
</style>
