<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'

const router = useRouter()

function goHome(): void {
  router.push('/')
}
</script>

<template>
  <el-button class="back-home" :icon="Back" text size="small" @click="goHome">返回主页</el-button>
</template>

<style scoped>
.back-home {
  flex-shrink: 0;
  margin-right: 0.5rem;
  color: var(--muted, #9aa3b2);
}

.back-home:hover {
  color: var(--accent, #409eff);
}

@media print {
  .back-home {
    display: none !important;
  }
}
</style>
