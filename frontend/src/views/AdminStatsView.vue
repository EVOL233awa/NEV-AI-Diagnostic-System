<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DIAG_STAGE_LABEL,
  fetchAdminStats,
  fmtIso,
  listAppointments,
  oneLine,
  type AdminStats,
  type AppointmentInfo,
  type AppointmentStatus,
} from '../api/client'
import Donut from '../components/Donut.vue'
import EmptyState from '../components/EmptyState.vue'
import Gauge from '../components/Gauge.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import Sparkline from '../components/Sparkline.vue'
import StatCard from '../components/StatCard.vue'
import StatusChip from '../components/StatusChip.vue'
import type { DonutSegment } from '../components/ui-types'

const stats = ref<AdminStats | null>(null)
const loading = ref(false)

const APPT_LABEL: Record<AppointmentStatus, string> = {
  pending: '待接单', accepted: '已接单', completed: '已完成', cancelled: '已取消',
}

const drillVisible = ref(false)
const drillStatus = ref<AppointmentStatus>('pending')
const drillList = ref<AppointmentInfo[]>([])
const drillLoading = ref(false)

const usageSeries = computed(() => (stats.value?.usage_daily ?? []).map((item) => item.calls))
const tokenSeries = computed(() => (stats.value?.usage_daily ?? []).map((item) => item.tokens_in + item.tokens_out))
const appointmentSeries = computed(() => (stats.value?.appointments_daily ?? []).map((item) => item.count))

const severitySegments = computed<DonutSegment[]>(() => {
  const severity = stats.value?.severity
  if (!severity) return []
  return [
    { label: '需尽快检修', value: severity.red, tone: 'danger' },
    { label: '建议到店检查', value: severity.yellow, tone: 'warn' },
    { label: '正常', value: severity.green, tone: 'ok' },
    { label: '未评估', value: severity.unknown, tone: 'neutral' },
  ]
})

const funnel = computed(() => {
  const rows = stats.value?.stage_funnel ?? []
  const max = Math.max(1, ...rows.map((item) => item.count))
  return rows.map((item) => ({
    ...item,
    label: DIAG_STAGE_LABEL[item.stage] ?? item.stage,
    percent: Math.round((item.count / max) * 100),
  }))
})

const limits = computed(() => stats.value?.consumption?.limits ?? null)
const limitsEnabled = computed(() => {
  const value = limits.value
  if (!value) return false
  return [value.asr_daily_seconds_per_user, value.search_daily_calls_per_user, value.global_daily_usd]
    .some((item) => typeof item === 'number' && item > 0)
})

const maxAsrUse = computed(() => {
  const value = stats.value?.consumption
  const limit = limits.value?.asr_daily_seconds_per_user
  if (!value || !limit) return 0
  return value.top_users.reduce((max, user) => Math.max(max, user.asr_seconds / limit), 0)
})

const maxSearchUse = computed(() => {
  const value = stats.value?.consumption
  const limit = limits.value?.search_daily_calls_per_user
  if (!value || !limit) return 0
  return value.top_users.reduce((max, user) => Math.max(max, user.search_calls / limit), 0)
})

const costUse = computed(() => {
  const value = stats.value?.consumption
  const limit = limits.value?.global_daily_usd
  if (!value || !limit) return 0
  return value.cost_today_usd / limit
})

const todayTokens = computed(() => (stats.value?.usage.today.tokens_in ?? 0) + (stats.value?.usage.today.tokens_out ?? 0))

async function openDrill(status: AppointmentStatus): Promise<void> {
  drillStatus.value = status
  drillVisible.value = true
  drillLoading.value = true
  drillList.value = []
  try {
    drillList.value = await listAppointments(status)
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
  <div v-loading="loading" class="page">
    <PageHeader title="统计看板" subtitle="用量、工单与诊断质量；数据按当前租户统计">
      <template #actions>
        <StatusChip v-if="stats" label="近 14 天窗口" tone="neutral" />
      </template>
    </PageHeader>

    <template v-if="stats">
      <div class="hmi-grid hmi-grid--stats">
        <StatCard label="今日模型调用" :value="stats.usage.today.calls" tone="accent" :hint="`近 7 天 ${stats.usage.week.calls} 次`" />
        <StatCard label="今日 Token" :value="todayTokens.toLocaleString()" tone="info" :hint="`入 ${stats.usage.today.tokens_in.toLocaleString()} / 出 ${stats.usage.today.tokens_out.toLocaleString()}`" />
        <StatCard label="今日成本估算" :value="`$${stats.usage.today.cost.toFixed(4)}`" tone="warn" hint="按 provider 单价估算" />
        <StatCard label="沉淀案例" :value="stats.cases" tone="ok" :hint="`${stats.users} 个在职账号`" />
      </div>

      <div class="chart-grid">
        <section class="panel hmi-card">
          <div class="panel-head">
            <h3>模型调用趋势</h3>
            <span class="hmi-sub">近 14 天 · 今日 {{ usageSeries.length ? usageSeries[usageSeries.length - 1] : 0 }} 次</span>
          </div>
          <Sparkline :points="usageSeries" label="近 14 天模型调用趋势" tone="accent" :width="320" :height="64" />
          <div class="mini-metrics">
            <span>Token 趋势</span>
            <Sparkline :points="tokenSeries" label="近 14 天 Token 趋势" tone="info" :width="220" :height="34" />
          </div>
        </section>

        <section class="panel hmi-card">
          <div class="panel-head">
            <h3>预约趋势</h3>
            <span class="hmi-sub">近 14 天新建</span>
          </div>
          <Sparkline :points="appointmentSeries" label="近 14 天预约趋势" tone="ok" :width="320" :height="64" />
          <div class="appt-row">
            <button
              v-for="(count, status) in stats.appointments"
              :key="status"
              type="button"
              class="appt-pill"
              @click="openDrill(status as AppointmentStatus)"
            >
              <span>{{ APPT_LABEL[status as AppointmentStatus] ?? status }}</span>
              <strong class="hmi-mono">{{ count }}</strong>
            </button>
          </div>
        </section>
      </div>

      <div class="chart-grid">
        <section class="panel hmi-card">
          <div class="panel-head"><h3>严重度分布</h3><span class="hmi-sub">按会话最后结论</span></div>
          <Donut :segments="severitySegments" total-label="结论" :size="128" />
        </section>

        <section class="panel hmi-card">
          <div class="panel-head"><h3>阶段漏斗</h3><span class="hmi-sub">已记录阶段优先，未记录按结论/问诊回退</span></div>
          <div class="funnel">
            <div v-for="item in funnel" :key="item.stage" class="funnel-row">
              <span class="funnel-label">{{ item.label }}</span>
              <span class="funnel-bar"><span :style="{ inlineSize: `${item.percent}%` }"></span></span>
              <span class="funnel-count hmi-mono">{{ item.count }}</span>
            </div>
          </div>
        </section>
      </div>

      <section class="panel hmi-card">
        <div class="panel-head">
          <h3>ASR / 搜索消耗</h3>
          <StatusChip :label="limitsEnabled ? '已启用限额' : '未启用限额'" :tone="limitsEnabled ? 'warn' : 'ok'" dot />
        </div>
        <div class="consumption">
          <div class="consume-stats">
            <div><span>今日 ASR</span><strong class="hmi-mono">{{ stats.consumption?.asr_seconds_today ?? 0 }} 秒</strong></div>
            <div><span>今日搜索</span><strong class="hmi-mono">{{ stats.consumption?.search_calls_today ?? 0 }} 次</strong></div>
            <div><span>今日成本</span><strong class="hmi-mono">${{ (stats.consumption?.cost_today_usd ?? 0).toFixed(4) }}</strong></div>
          </div>

          <div v-if="limitsEnabled" class="gauges">
            <Gauge :value="maxAsrUse" label="ASR 单用户用量" tone="info" :size="104" />
            <Gauge :value="maxSearchUse" label="搜索单用户用量" tone="warn" :size="104" />
            <Gauge :value="costUse" label="全局预算用量" tone="danger" :size="104" />
          </div>
          <p v-else class="hmi-sub">
            三项限额均未配置（null），当前不限制；若长期公网运行，可在系统参数页填入正数启用。
          </p>

          <div v-if="stats.consumption?.top_users.length" class="top-users">
            <h4>今日消耗 Top 5</h4>
            <div v-for="user in stats.consumption.top_users" :key="`${user.user_id}`" class="user-row">
              <span>{{ user.username || '未命名用户' }}</span>
              <span class="hmi-mono">{{ user.asr_seconds }}s · {{ user.search_calls }} 次 · ${{ user.cost_usd.toFixed(4) }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="panel hmi-card">
        <div class="panel-head"><h3>最近活动</h3><span class="hmi-sub">最近 8 条审计事件</span></div>
        <EmptyState v-if="!stats.recent_activity?.length" title="暂无审计事件" compact />
        <ul v-else class="activity">
          <li v-for="item in stats.recent_activity" :key="item.id">
            <code :title="item.action">{{ item.action }}</code>
            <span class="activity-user">{{ item.username || '系统' }}</span>
            <span class="activity-time hmi-mono">{{ fmtIso(item.created_at) }}</span>
          </li>
        </ul>
      </section>
    </template>

    <el-dialog v-model="drillVisible" :title="`「${APPT_LABEL[drillStatus]}」工单明细（${drillList.length}）`" width="min(94vw, 560px)">
      <div v-loading="drillLoading" class="drill-list">
        <EmptyState v-if="!drillLoading && drillList.length === 0" title="暂无工单" compact />
        <div v-for="a in drillList" :key="a.id" class="drill-row">
          <div class="drill-top">
            <span class="drill-id">#{{ a.id }} · {{ a.owner_name }}</span>
            <span class="drill-time hmi-mono">{{ fmtTime(a.appointment_time) }}</span>
          </div>
          <p class="drill-vehicle">{{ a.vehicle || '未关联车辆' }}</p>
          <p v-if="a.summary_card" class="drill-summary">{{ oneLine(a.summary_card.summary) }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.75rem;
}

.panel {
  padding: 0.9rem 1rem;
  min-inline-size: 0;
}

.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-block-end: 0.65rem;
  flex-wrap: wrap;
}

.panel-head h3 {
  font-size: var(--hmi-fs-4);
  font-weight: 650;
}

.mini-metrics {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-block-start: 0.6rem;
  padding-block-start: 0.5rem;
  border-block-start: 1px solid var(--hmi-line-soft);
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.appt-row {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-block-start: 0.6rem;
  padding-block-start: 0.5rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.appt-pill {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.55rem;
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  background: transparent;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  cursor: pointer;
}

.appt-pill:hover {
  border-color: var(--hmi-accent-line);
  color: var(--hmi-text);
}

.appt-pill strong {
  color: var(--hmi-text);
}

.funnel {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.funnel-row {
  display: grid;
  grid-template-columns: 52px 1fr 36px;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--hmi-fs-2);
}

.funnel-label {
  color: var(--hmi-text-3);
}

.funnel-bar {
  block-size: 10px;
  border-radius: 999px;
  background: var(--hmi-surface-2);
  overflow: hidden;
}

.funnel-bar span {
  display: block;
  block-size: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--hmi-accent-dim), var(--hmi-accent));
}

.funnel-count {
  text-align: end;
  color: var(--hmi-text-2);
}

.consumption {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.consume-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.5rem;
}

.consume-stats > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface-2);
}

.consume-stats span {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.consume-stats strong {
  font-size: var(--hmi-fs-4);
  color: var(--hmi-text);
}

.gauges {
  display: flex;
  gap: 0.8rem;
  flex-wrap: wrap;
}

.top-users h4 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block-end: 0.35rem;
}

.user-row {
  display: flex;
  justify-content: space-between;
  gap: 0.7rem;
  padding-block: 0.3rem;
  border-block-end: 1px solid var(--hmi-line-soft);
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.user-row span:last-child {
  color: var(--hmi-text-3);
  text-align: end;
}

.activity {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.activity li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--hmi-fs-2);
  padding-block-end: 0.35rem;
  border-block-end: 1px solid var(--hmi-line-soft);
}

.activity code {
  display: block;
  min-inline-size: 0;
  overflow: hidden;
  font-family: var(--hmi-font-mono);
  color: var(--hmi-accent);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-user {
  flex: none;
  color: var(--hmi-text-3);
  white-space: nowrap;
}

.activity-time {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  white-space: nowrap;
}

.drill-list {
  max-block-size: 55vh;
  overflow-y: auto;
}

.drill-row {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius-sm);
  margin-block-end: 0.5rem;
}

.drill-top {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: var(--hmi-fs-2);
  font-weight: 600;
}

.drill-time {
  color: var(--hmi-text-3);
  font-weight: 400;
  font-size: var(--hmi-fs-1);
  white-space: nowrap;
}

.drill-vehicle {
  margin-block-start: 0.2rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.drill-summary {
  margin-block-start: 0.25rem;
  font-size: var(--hmi-fs-2);
}

@media (max-width: 860px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
