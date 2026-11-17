<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/layout/AppShell.vue'

const route = useRoute()
/** 登录页与打印报告不套应用壳；报告页自身负责浅色打印排版。 */
const chromeless = computed(() => Boolean(route.meta.public || route.meta.standalone))
</script>

<template>
  <RouterView v-if="chromeless" />
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>
