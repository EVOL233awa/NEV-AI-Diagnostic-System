<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  acceptAppointment,
  cancelAppointment,
  completeAppointment,
  createCase,
  fetchAppointmentDialog,
  listAppointments,
  oneLine,
  localIso,
  type AppointmentInfo,
  type AppointmentStatus,
} from '../api/client'
import DataTable from '../components/DataTable.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatusChip from '../components/StatusChip.vue'
import type { ChipTone, TableColumn } from '../components/ui-types'

const router = useRouter()

const appointments = ref<AppointmentInfo[]>([])
const loading = ref(false)
const statusFilter = ref<AppointmentStatus | ''>('')
const keyword = ref('')
const page = ref(1)
const PAGE_SIZE = 10
const pendingCount = ref(0)

const detail = ref<AppointmentInfo | null>(null)
const drawerVisible = ref(false)
const dialogMessages = ref<{ role: string; content: string }[]>([])
const dialogBlocked = ref('')

const acceptForm = reactive<{ time: Date | null; note: string }>({ time: null, note: '' })
const completeForm = reactive<{ result: string }>({ result: '' })

const STATUS_META: Record<AppointmentStatus, { label: string; tone: ChipTone }> = {
  pending: { label: '待接单', tone: 'warn' },
  accepted: { label: '已接单', tone: 'accent' },
  completed: { label: '已完成', tone: 'ok' },
  cancelled: { label: '已取消', tone: 'neutral' },
}

const columns: TableColumn[] = [
  { key: 'id', label: '工单', width: 82, primary: true },
  { key: 'status', label: '状态', width: 100 },
  { key: 'owner', label: '车主 / 车辆', minWidth: 190 },
  { key: 'appointment_time', label: '到店时间', width: 140 },
  { key: 'summary', label: '诊断摘要', minWidth: 220 },
]

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return appointments.value.filter((item) => {
    if (statusFilter.value && item.status !== statusFilter.value) return false
    if (!q) return true
    return [String(item.id), item.owner_name, item.vehicle, item.summary_card?.summary]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(q)
  })
})

const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

const rows = computed<Record<string, unknown>[]>(() =>
  paged.value.map((item) => ({
    id: `#${item.id}`,
    status: item.status,
    status_label: STATUS_META[item.status].label,
    status_tone: STATUS_META[item.status].tone,
    owner: `${item.owner_name || '车主'} · ${item.vehicle || '未关联车辆'}`,
    appointment_time: fmtTime(item.appointment_time),
    summary: item.summary_card ? oneLine(item.summary_card.summary, 50) : '—',
    severity: item.summary_card?.severity ?? '',
    raw: item,
  })),
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    appointments.value = await listAppointments()
    pendingCount.value = appointments.value.filter((a) => a.status === 'pending').length
    const maxPage = Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE))
    if (page.value > maxPage) page.value = maxPage
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

const pollTimer = window.setInterval(refresh, 30000)

onUnmounted(() => {
  window.clearInterval(pollTimer)
})

function changeStatus(): void {
  page.value = 1
  void refresh()
}

async function openDetail(row: Record<string, unknown>): Promise<void> {
  const source = row.raw as AppointmentInfo | undefined
  if (!source) return
  const a = appointments.value.find((item) => item.id === source.id) ?? source
  detail.value = a
  acceptForm.time = a.appointment_time ? new Date(a.appointment_time) : null
  acceptForm.note = a.shop_note
  completeForm.result = a.repair_result
  dialogMessages.value = []
  dialogBlocked.value = ''
  drawerVisible.value = true
  await loadDialog(a)
}

async function loadDialog(a: AppointmentInfo): Promise<void> {
  if (!a.session_id) {
    dialogBlocked.value = '该预约没有关联诊断会话'
    return
  }
  if (!a.owner_privacy_share) {
    dialogBlocked.value = '车主已关闭「店员可见对话记录」，仅可查看诊断摘要卡'
    return
  }
  try {
    const data = await fetchAppointmentDialog(a.id)
    dialogMessages.value = data.messages
  } catch (e) {
    dialogBlocked.value = extractError(e)
  }
}

async function accept(): Promise<void> {
  const a = detail.value
  if (!a) return
  try {
    await acceptAppointment(a.id, {
      appointment_time: acceptForm.time ? localIso(acceptForm.time) : undefined,
      shop_note: acceptForm.note,
    })
    ElMessage.success('已接单')
    drawerVisible.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

async function complete(): Promise<void> {
  const a = detail.value
  if (!a) return
  if (!completeForm.result.trim()) {
    ElMessage.warning('请填写维修/验证结果')
    return
  }
  try {
    await completeAppointment(a.id, completeForm.result)
    ElMessage.success('结果已回填，工单完成')
    drawerVisible.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

async function cancel(a: AppointmentInfo): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('填写取消原因（店员备注）', '取消预约', {
      inputPlaceholder: '如：备件缺货 / 车主要求',
      inputValue: a.shop_note,
    })
    await cancelAppointment(a.id, value ?? '')
    ElMessage.success('已取消')
    drawerVisible.value = false
    await refresh()
  } catch {
    /* 用户取消对话框 */
  }
}

async function settleCase(a: AppointmentInfo): Promise<void> {
  if (!a.session_id) {
    ElMessage.warning('该预约没有关联诊断会话，无法沉淀案例')
    return
  }
  try {
    const res = await createCase(a.session_id, a.repair_result)
    ElMessage.success(`案例已沉淀入库（${res.chunks} 个知识块）`)
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}

function toneOf(value: unknown): ChipTone {
  return typeof value === 'string' ? (value as ChipTone) : 'neutral'
}

function fmtTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="预约工单" subtitle="接单、改约、完成与案例沉淀；对话原文按车主隐私开关显示">
      <template #actions>
        <StatusChip v-if="pendingCount" :label="`${pendingCount} 个待接单`" tone="warn" dot />
        <el-button @click="refresh">刷新</el-button>
      </template>
    </PageHeader>

    <section class="toolbar hmi-card">
      <el-radio-group v-model="statusFilter" @change="changeStatus">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="pending">待接单</el-radio-button>
        <el-radio-button value="accepted">已接单</el-radio-button>
        <el-radio-button value="completed">已完成</el-radio-button>
        <el-radio-button value="cancelled">已取消</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" placeholder="搜索工单号 / 车主 / 车辆 / 摘要" clearable class="search" aria-label="搜索工单" />
    </section>

    <DataTable
      :rows="rows"
      :columns="columns"
      :loading="loading"
      empty-text="暂无预约工单"
      mobile-title-key="id"
      @row-click="openDetail"
    >
      <template #cell-id="{ row }">
        <span class="hmi-mono id-cell">{{ row.id }}</span>
      </template>
      <template #cell-status="{ row }">
        <StatusChip :label="String(row.status_label)" :tone="toneOf(row.status_tone)" dot />
      </template>
      <template #cell-summary="{ row }">
        <div class="summary-cell">
          <SeverityBadge v-if="row.severity" :severity="String(row.severity)" compact />
          <span>{{ row.summary }}</span>
        </div>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text type="primary" @click.stop="openDetail(row)">处理</el-button>
      </template>
    </DataTable>

    <el-pagination
      v-if="filtered.length > PAGE_SIZE"
      class="pager"
      layout="total, prev, pager, next"
      :page-size="PAGE_SIZE"
      :total="filtered.length"
      :current-page="page"
      @current-change="page = $event"
    />

    <el-drawer v-model="drawerVisible" :title="detail ? `工单 #${detail.id}` : ''" size="min(96vw, 500px)">
      <template v-if="detail">
        <div class="detail-head">
          <div>
            <p class="owner">{{ detail.owner_name }} · {{ detail.vehicle || '未关联车辆' }}</p>
            <p class="hmi-sub">到店时间 {{ fmtTime(detail.appointment_time) }}</p>
          </div>
          <StatusChip :label="STATUS_META[detail.status].label" :tone="STATUS_META[detail.status].tone" dot />
        </div>

        <section v-if="detail.summary_card" class="detail-block summary-card">
          <h3>AI 诊断摘要卡（始终可见）</h3>
          <div class="summary-line">
            <SeverityBadge :severity="detail.summary_card.severity" />
            <span>{{ detail.summary_card.summary }}</span>
          </div>
          <ul v-if="detail.summary_card.hypotheses.length">
            <li v-for="h in detail.summary_card.hypotheses" :key="h">{{ h }}</li>
          </ul>
          <ol v-if="detail.summary_card.steps.length">
            <li v-for="s in detail.summary_card.steps" :key="s">{{ s }}</li>
          </ol>
          <p v-if="detail.summary_card.pending_checks.length" class="muted">
            待确认：{{ detail.summary_card.pending_checks.join('；') }}
          </p>
          <p v-if="detail.summary_card.note" class="muted">车主说明：{{ detail.summary_card.note }}</p>
        </section>

        <section class="detail-block">
          <h3>对话记录</h3>
          <div v-if="dialogMessages.length" class="dialog-list">
            <div v-for="(m, i) in dialogMessages" :key="i" class="msg" :class="m.role">
              <span class="msg-role">{{ m.role === 'user' ? '车主' : 'AI' }}</span>
              <span>{{ m.content }}</span>
            </div>
          </div>
          <p v-else class="muted">{{ dialogBlocked || '暂无对话' }}</p>
        </section>

        <section v-if="detail.status === 'pending'" class="detail-block">
          <h3>接单（可改约时间）</h3>
          <el-date-picker v-model="acceptForm.time" type="datetime" format="YYYY-MM-DD HH:mm" placeholder="确认/修改到店时间" class="full" />
          <el-input v-model="acceptForm.note" class="gap-top" placeholder="备注（如：备件已备）" maxlength="500" />
          <div class="actions">
            <el-button type="primary" @click="accept">确认接单</el-button>
            <el-button type="danger" plain @click="cancel(detail)">取消工单</el-button>
          </div>
        </section>

        <section v-if="detail.status === 'accepted'" class="detail-block">
          <h3>服务完成 · 回填结果</h3>
          <el-input v-model="completeForm.result" type="textarea" :rows="3" maxlength="2000" placeholder="维修/验证结果，回填后将同步车主" />
          <div class="actions">
            <el-button type="primary" @click="complete">提交并完成工单</el-button>
            <el-button type="danger" plain @click="cancel(detail)">取消工单</el-button>
          </div>
        </section>

        <section v-if="detail.status === 'completed'" class="detail-block">
          <h3>维修结果</h3>
          <p>{{ detail.repair_result || '未填写' }}</p>
          <div class="actions">
            <el-button v-if="detail.session_id" @click="settleCase(detail)">沉淀为案例</el-button>
            <el-button type="primary" plain @click="router.push(`/report/appointment/${detail.id}`)">查看 / 打印报告</el-button>
          </div>
        </section>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  padding: 0.7rem 0.8rem;
}

.search {
  margin-inline-start: auto;
  inline-size: min(100%, 280px);
}

.id-cell {
  color: var(--hmi-accent);
  font-weight: 600;
}

.summary-cell {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.pager {
  margin-block-start: 0.7rem;
  justify-content: flex-end;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
  padding-block-end: 0.6rem;
  border-block-end: 1px solid var(--hmi-line-soft);
}

.owner {
  font-size: var(--hmi-fs-4);
  font-weight: 600;
}

.detail-block {
  margin-block-start: 0.9rem;
}

.detail-block h3 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block-end: 0.4rem;
}

.summary-line {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.summary-card ul,
.summary-card ol {
  margin: 0.3rem 0 0.3rem 1.2rem;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.muted {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.dialog-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-block-size: 35vh;
  overflow-y: auto;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0.4rem 0.55rem;
  border-radius: var(--hmi-radius-sm);
  margin-block-end: 0.2rem;
  background: var(--hmi-surface);
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
  white-space: pre-wrap;
}

.msg.user {
  background: var(--hmi-accent-soft);
}

.msg-role {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.actions {
  display: flex;
  gap: 0.5rem;
  margin-block-start: 0.6rem;
  flex-wrap: wrap;
}

.gap-top {
  margin-block-start: 0.5rem;
}

.full {
  inline-size: 100%;
}

@media (max-width: 640px) {
  .search {
    margin-inline-start: 0;
    inline-size: 100%;
  }
}
</style>
