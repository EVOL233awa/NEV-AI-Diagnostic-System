<script setup lang="ts">
const visible = defineModel<boolean>({ default: false })
withDefaults(defineProps<{ title: string; size?: string }>(), { size: '56%' })
</script>

<template>
  <el-drawer
    v-model="visible"
    direction="btt"
    :size="size"
    :title="title"
    class="hmi-sheet"
    append-to-body
  >
    <slot />
  </el-drawer>
</template>

<style>
.hmi-sheet.el-drawer {
  max-block-size: 80vh;
  border-start-start-radius: var(--hmi-radius-xl);
  border-start-end-radius: var(--hmi-radius-xl);
}

.hmi-sheet .el-drawer__header {
  margin-block-end: 0.4rem;
}

.hmi-sheet .el-drawer__body {
  padding-block-end: max(1rem, env(safe-area-inset-bottom, 0px));
}
</style>
