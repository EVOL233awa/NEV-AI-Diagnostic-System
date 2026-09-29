<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchAdminStats, listAppointments, oneLine, type AdminStats, type AppointmentInfo, type AppointmentStatus } from '../api/client'
import BackHome from '../components/BackHome.vue'

const stats = ref<AdminStats | null>(null)
const loading = ref(false)

const APPT_LABEL: Record<AppointmentStatus, string> = {
  pending: '待接单', accepted: '已接单', completed: '已完成', cancelled: '已取消',
}

/** 状态卡点开后的工单明细弹窗 */
const drillVisible = ref(false)
const drillStatus = ref<AppointmentStatus>('pending')
const drillList = ref<AppointmentInfo[]>([])
const drillLoading = ref(false)

async function openDrill(st: AppointmentStatus): Promise<void> {
  drillStatus.value = st
  drillVisible.value = true
  drillLoading.value = true
  drillList.value = []
  try {
    drillList.value = await listAppointments(st)
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '加载工单明细失败')
  } finally {
    drillLoading.value = false
  }
}

function fmtTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

onMounted(async () => {
  loading.value = true
  try {
    stats.value = await fetchAdminStats()
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '加载统计失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head"><BackHome /><h2>统计看板</h2></header>

    <template v-if="stats">
      <p class="section">模型用量（token）</p>
      <div class="grid">
        <el-card v-for="(win, key) in stats.usage" :key="key" class="stat">
          <p class="stat-title">{{ key === 'today' ? '今日' : key === 'week' ? '近 7 天' : '近 30 天' }}</p>
          <p class="stat-main">{{ win.calls }} 次调用</p>
          <p class="stat-sub">入 {{ win.tokens_in.toLocaleString() }} / 出 {{ win.tokens_out.toLocaleString() }} tokens</p>
        </el-card>
      </div>

      <p class="section">预约工单（点卡片看明细）</p>
      <div class="grid">
        <el-card
          v-for="(count, st) in stats.appointments"
          :key="st"
          class="stat clickable"
          shadow="hover"
          @click="openDrill(st as AppointmentStatus)"
        >
          <p class="stat-title">{{ APPT_LABEL[st as AppointmentStatus] ?? st }}</p>
          <p class="stat-main">{{ count }}</p>
          <p class="stat-sub">点击查看哪些工单</p>
        </el-card>
      </div>

      <p class="section">总量</p>
      <div class="grid">
        <el-card class="stat">
          <p class="stat-title">沉淀案例</p>
          <p class="stat-main">{{ stats.cases }}</p>
        </el-card>
        <el-card class="stat">
          <p class="stat-title">在职账号</p>
          <p class="stat-main">{{ stats.users }}</p>
        </el-card>
      </div>
    </template>

    <el-dialog v-model="drillVisible" :title="`「${APPT_LABEL[drillStatus]}」工单明细（${drillList.length}）`" width="560px">
      <div v-loading="drillLoading" class="drill-list">
        <el-empty v-if="!drillLoading && drillList.length === 0" description="暂无工单" :image-size="60" />
        <div v-for="a in drillList" :key="a.id" class="drill-row">
          <div class="drill-top">
            <span class="drill-id">#{{ a.id }} · {{ a.owner_name }}</span>
            <span class="drill-time">{{ fmtTime(a.appointment_time) }}</span>
          </div>
          <p class="drill-vehicle">{{ a.vehicle || '未关联车辆' }}</p>
          <p v-if="a.summary_card" class="drill-summary">{{ oneLine(a.summary_card.summary) }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
.page-head h2 { font-size: 1rem; margin: 0 0 1rem; }
.section { font-size: 0.8rem; color: var(--muted); margin: 1rem 0 0.5rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0.7rem; }
.stat-title { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.3rem; }
.stat-main { font-size: 1.15rem; font-weight: 700; margin: 0 0 0.2rem; }
.stat-sub { font-size: 0.72rem; color: var(--muted); margin: 0; }
.stat.clickable { cursor: pointer; }
.drill-list { max-height: 55vh; overflow-y: auto; }
.drill-row { padding: 0.5rem 0.6rem; border: 1px solid var(--border, rgba(255, 255, 255, 0.08)); border-radius: 8px; margin-bottom: 0.5rem; }
.drill-top { display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.8rem; font-weight: 600; }
.drill-time { color: var(--muted); font-weight: 400; font-size: 0.72rem; white-space: nowrap; }
.drill-vehicle { margin: 0.2rem 0 0; font-size: 0.75rem; color: var(--muted); }
.drill-summary { margin: 0.25rem 0 0; font-size: 0.75rem; }
</style>
