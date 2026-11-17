<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cancelAppointment,
  createAppointment,
  listAppointments,
  localIso,
  type AppointmentInfo,
  type AppointmentStatus,
} from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatusChip from '../components/StatusChip.vue'
import type { ChipTone } from '../components/ui-types'

const appointments = ref<AppointmentInfo[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const detailOpen = ref(false)
const selected = ref<AppointmentInfo | null>(null)

const form = ref<{ time: Date | null; note: string }>({ time: null, note: '' })

const STATUS_META: Record<AppointmentStatus, { label: string; tone: ChipTone }> = {
  pending: { label: '待接单', tone: 'warn' },
  accepted: { label: '已接单', tone: 'accent' },
  completed: { label: '已完成', tone: 'ok' },
  cancelled: { label: '已取消', tone: 'neutral' },
}

const canCancel = computed(() => (a: AppointmentInfo) => a.status === 'pending' || a.status === 'accepted')

async function refresh(): Promise<void> {
  loading.value = true
  try {
    appointments.value = await listAppointments()
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  if (!form.value.time) {
    ElMessage.warning('请选择期望到店时间')
    return
  }
  try {
    await createAppointment({ appointment_time: localIso(form.value.time), note: form.value.note })
    ElMessage.success('预约已提交，等待门店接单')
    dialogVisible.value = false
    form.value = { time: null, note: '' }
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

function openDetail(item: AppointmentInfo): void {
  selected.value = item
  detailOpen.value = true
}

async function cancel(item: AppointmentInfo): Promise<void> {
  try {
    await cancelAppointment(item.id, '车主取消')
    ElMessage.success('已取消')
    detailOpen.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}

function fmtTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="我的预约" subtitle="提交后门店接单；到店时间与诊断摘要会自动同步给服务顾问">
      <template #actions>
        <el-button type="primary" @click="dialogVisible = true">新建预约</el-button>
      </template>
    </PageHeader>

    <div v-loading="loading">
      <EmptyState
        v-if="!loading && appointments.length === 0"
        title="还没有预约记录"
        description="可以在 AI 诊断出结论后一键预约，也可以在这里直接新建。"
      />
      <ol v-else class="timeline">
        <li v-for="item in appointments" :key="item.id" class="timeline-item" :data-status="item.status">
          <span class="dot" aria-hidden="true"></span>
          <button type="button" class="appt-card hmi-card" @click="openDetail(item)">
            <div class="appt-head">
              <span class="time hmi-mono">{{ fmtTime(item.appointment_time) }}</span>
              <StatusChip :label="STATUS_META[item.status].label" :tone="STATUS_META[item.status].tone" dot />
            </div>
            <p class="vehicle">{{ item.vehicle || '未关联车辆' }}</p>
            <div v-if="item.summary_card" class="summary">
              <SeverityBadge :severity="item.summary_card.severity" />
              <span>{{ item.summary_card.summary }}</span>
            </div>
            <p v-if="item.repair_result" class="result">维修结果：{{ item.repair_result }}</p>
            <p v-if="item.shop_note" class="note">门店备注：{{ item.shop_note }}</p>
            <span class="detail-link">查看详情 →</span>
          </button>
        </li>
      </ol>
    </div>

    <el-dialog v-model="dialogVisible" title="新建预约" width="min(92vw, 420px)">
      <el-form label-position="top">
        <el-form-item label="到店时间">
          <el-date-picker
            v-model="form.time"
            type="datetime"
            placeholder="选择日期和时间"
            format="YYYY-MM-DD HH:mm"
            :date-format="'YYYY-MM-DD'"
            :time-format="'HH:mm'"
          />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input v-model="form.note" type="textarea" :rows="2" maxlength="300" placeholder="选填，如故障现象补充" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">提交预约</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailOpen" title="预约详情" size="min(94vw, 440px)">
      <template v-if="selected">
        <div class="detail-head">
          <span class="time-lg hmi-mono">{{ fmtTime(selected.appointment_time) }}</span>
          <StatusChip :label="STATUS_META[selected.status].label" :tone="STATUS_META[selected.status].tone" dot />
        </div>
        <dl class="detail-grid">
          <div><dt>车辆</dt><dd>{{ selected.vehicle || '未关联车辆' }}</dd></div>
          <div><dt>车主</dt><dd>{{ selected.owner_name || '—' }}</dd></div>
          <div><dt>创建时间</dt><dd class="hmi-mono">{{ fmtTime(selected.created_at) }}</dd></div>
        </dl>

        <section v-if="selected.summary_card" class="detail-block">
          <h3>诊断摘要</h3>
          <div class="summary">
            <SeverityBadge :severity="selected.summary_card.severity" />
            <span>{{ selected.summary_card.summary }}</span>
          </div>
          <p v-if="selected.summary_card.note" class="hmi-sub">{{ selected.summary_card.note }}</p>
        </section>
        <section v-if="selected.shop_note" class="detail-block">
          <h3>门店备注</h3>
          <p>{{ selected.shop_note }}</p>
        </section>
        <section v-if="selected.repair_result" class="detail-block">
          <h3>维修结果</h3>
          <p>{{ selected.repair_result }}</p>
        </section>

        <el-button
          v-if="canCancel(selected)"
          class="cancel-btn"
          type="danger"
          plain
          @click="cancel(selected)"
        >
          取消预约
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.timeline {
  list-style: none;
  margin: 0;
  padding: 0 0 0 1.1rem;
  border-inline-start: 1px solid var(--hmi-line);
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.timeline-item {
  position: relative;
}

.dot {
  position: absolute;
  inset-inline-start: -1.42rem;
  inset-block-start: 1rem;
  inline-size: 9px;
  block-size: 9px;
  border-radius: 50%;
  background: var(--hmi-line-strong);
  border: 2px solid var(--hmi-bg);
}

.timeline-item[data-status='pending'] .dot { background: var(--hmi-warn); }
.timeline-item[data-status='accepted'] .dot { background: var(--hmi-accent); }
.timeline-item[data-status='completed'] .dot { background: var(--hmi-ok); }

.appt-card {
  inline-size: 100%;
  padding: 0.75rem 0.85rem;
  text-align: start;
  color: inherit;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.appt-card:hover {
  border-color: var(--hmi-accent-line);
}

.appt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.time {
  font-size: var(--hmi-fs-4);
  font-weight: 650;
}

.vehicle {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.summary {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
  line-height: 1.6;
}

.result,
.note {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-3);
}

.detail-link {
  color: var(--hmi-accent);
  font-size: var(--hmi-fs-1);
  align-self: flex-end;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-block-end: 0.7rem;
}

.time-lg {
  font-size: 1.1rem;
  font-weight: 650;
}

.detail-grid {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0 0 0.8rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface);
}

.detail-grid > div {
  display: flex;
  justify-content: space-between;
  gap: 0.7rem;
  font-size: var(--hmi-fs-2);
}

.detail-grid dt {
  color: var(--hmi-text-3);
}

.detail-grid dd {
  margin: 0;
  color: var(--hmi-text-2);
  text-align: end;
}

.detail-block {
  margin-block-end: 0.8rem;
}

.detail-block h3 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block-end: 0.35rem;
}

.detail-block p {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
  line-height: 1.65;
}

.cancel-btn {
  margin-block-start: 0.5rem;
}
</style>
