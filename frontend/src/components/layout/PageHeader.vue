<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'

const props = defineProps<{
  title: string
  subtitle?: string
  back?: boolean | string
}>()
const router = useRouter()

function goBack(): void {
  if (typeof props.back === 'string') {
    router.push(props.back)
    return
  }
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}
</script>

<template>
  <header class="page-header">
    <button v-if="props.back" type="button" class="back" aria-label="返回上一页" @click="goBack">
      <el-icon :size="17" aria-hidden="true"><ArrowLeft /></el-icon>
    </button>
    <div class="titles">
      <h2>{{ props.title }}</h2>
      <p v-if="props.subtitle" class="sub">{{ props.subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.back {
  display: grid;
  place-items: center;
  inline-size: 36px;
  block-size: 36px;
  border-radius: var(--hmi-radius-sm);
  border: 1px solid var(--hmi-line);
  background: var(--hmi-surface);
  color: var(--hmi-text-2);
  cursor: pointer;
  flex: none;
}

.back:hover {
  color: var(--hmi-text);
  border-color: var(--hmi-line-strong);
}

.titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-inline-size: 0;
}

.titles h2 {
  font-size: clamp(1.05rem, 1.5vw, 1.3rem);
  font-weight: 650;
}

.sub {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.actions {
  margin-inline-start: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

@media (pointer: coarse) {
  .back {
    inline-size: 44px;
    block-size: 44px;
  }
}
</style>
