<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { DiagResult, SessionInfo } from '../../api/chat'
import type { Role } from '../../config/navigation'
import type { StageStep } from '../ui-types'
import SeverityBadge from '../SeverityBadge.vue'
import StageTimeline from '../StageTimeline.vue'
import StatusChip from '../StatusChip.vue'

const props = defineProps<{
  role: Role
  vehicle: SessionInfo['vehicle']
  diag: DiagResult | null
  stages: StageStep[]
  tools: { name: string; brief: string; done: boolean }[]
  privacyDialog?: boolean
}>()

const vehicleTitle = computed(() => {
  const v = props.vehicle
  if (!v) return ''
  return [v.brand, v.model_name].filter(Boolean).join(' ') || v.plate_no
})
</script>

<template>
  <div class="context">
    <section v-if="role !== 'admin'" class="card">
      <h3>车辆上下文</h3>
      <template v-if="vehicle">
        <p class="vehicle-name">{{ vehicleTitle }}</p>
        <dl class="facts">
          <div><dt>车牌</dt><dd>{{ vehicle.plate_no || '—' }}</dd></div>
          <div><dt>里程</dt><dd class="hmi-mono">{{ vehicle.mileage != null ? `${vehicle.mileage.toLocaleString()} km` : '—' }}</dd></div>
        </dl>
        <RouterLink v-if="role === 'owner'" class="link" to="/my-vehicles">查看完整诊断历史 →</RouterLink>
        <RouterLink v-else class="link" :to="`/staff/vehicles`">车辆档案检索 →</RouterLink>
      </template>
      <p v-else class="muted">本会话未关联车辆。车主添加默认车辆后，新会话会自动归档。</p>
    </section>

    <section v-if="diag" class="card">
      <h3>当前诊断</h3>
      <div class="diag-line">
        <SeverityBadge :severity="diag.severity" />
        <span class="diag-summary">{{ diag.summary }}</span>
      </div>
      <p v-if="diag.hypotheses?.length" class="muted small">可能原因 {{ diag.hypotheses.length }} 项 · 待确认 {{ diag.pending_checks?.length ?? 0 }} 项</p>
    </section>

    <section v-if="role === 'admin'" class="card">
      <h3>诊断阶段</h3>
      <StageTimeline :history="stages" inferred />
    </section>

    <section v-if="role === 'admin'" class="card">
      <h3>查证记录</h3>
      <ul v-if="tools.length" class="tool-list">
        <li v-for="(tool, index) in tools" :key="index">
          <StatusChip :label="tool.done ? '已完成' : '进行中'" :tone="tool.done ? 'ok' : 'warn'" dot />
          <span>{{ tool.brief }}</span>
        </li>
      </ul>
      <p v-else class="muted">本轮还没有工具查证。</p>
      <RouterLink class="link" to="/admin/diagnosis">进入质控查看证据链 →</RouterLink>
    </section>

    <section v-if="role === 'staff'" class="card">
      <h3>快捷工具</h3>
      <div class="quick-links">
        <RouterLink to="/staff/dtc">故障码速查</RouterLink>
        <RouterLink to="/staff/vehicles">车辆档案</RouterLink>
        <RouterLink to="/staff/appointments">预约工单</RouterLink>
      </div>
    </section>

    <section v-if="role === 'owner'" class="card">
      <h3>隐私与预约</h3>
      <p class="muted small">工作人员可见范围：{{ privacyDialog ? '完整对话' : '仅诊断摘要' }}。</p>
      <div class="quick-links">
        <RouterLink to="/settings">隐私设置</RouterLink>
        <RouterLink to="/appointments">我的预约</RouterLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
.context {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.card {
  padding: 0.75rem 0.8rem;
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface);
}

.card h3 {
  font-size: var(--hmi-fs-2);
  font-weight: 650;
  color: var(--hmi-text-2);
  margin-block-end: 0.45rem;
}

.vehicle-name {
  font-size: var(--hmi-fs-4);
  font-weight: 600;
}

.facts {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin: 0.4rem 0;
}

.facts > div {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: var(--hmi-fs-2);
}

.facts dt {
  color: var(--hmi-text-3);
}

.facts dd {
  margin: 0;
  color: var(--hmi-text-2);
}

.link {
  display: inline-block;
  margin-block-start: 0.3rem;
  font-size: var(--hmi-fs-2);
}

.muted {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.small {
  font-size: var(--hmi-fs-1);
}

.diag-line {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.diag-summary {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.tool-list {
  list-style: none;
  margin: 0 0 0.4rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.tool-list li {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.quick-links a {
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius-sm);
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.quick-links a:hover {
  border-color: var(--hmi-accent-line);
  color: var(--hmi-accent);
}
</style>
