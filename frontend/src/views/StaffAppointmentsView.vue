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
import BackHome from '../components/BackHome.vue'

const router = useRouter()

const appointments = ref<AppointmentInfo[]>([])
const loading = ref(false)
const statusFilter = ref<AppointmentStatus | ''>('')
const pendingCount = ref(0)

const detail = ref<AppointmentInfo | null>(null)
const drawerVisible = ref(false)
const dialogMessages = ref<{ role: string; content: string }[]>([])
const dialogBlocked = ref('')

const acceptForm = reactive<{ time: Date | null; note: string }>({ time: null, note: '' })
const completeForm = reactive<{ result: string }>({ result: '' })

const STATUS_META: Record<AppointmentStatus, { label: string; type: 'warning' | 'primary' | 'success' | 'info' }> = {
  pending: { label: '待接单', type: 'warning' },
  accepted: { label: '已接单', type: 'primary' },
  completed: { label: '已完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
}

const filtered = computed(() =>
  statusFilter.value ? appointments.value.filter((a) => a.status === statusFilter.value) : appointments.value,
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    appointments.value = await listAppointments()
    pendingCount.value = appointments.value.filter((a) => a.status === 'pending').length
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

const pollTimer = window.setInterval(refresh, 30000)

/** 抽屉宽度：手机上 480px 固定宽会横向溢出（内容被裁、显得放大），窄屏铺满 */
const drawerSize = ref(window.innerWidth < 640 ? '100%' : '480px')
function syncDrawerSize(): void {
  drawerSize.value = window.innerWidth < 640 ? '100%' : '480px'
}
window.addEventListener('resize', syncDrawerSize)
onUnmounted(() => {
  window.clearInterval(pollTimer)
  window.removeEventListener('resize', syncDrawerSize)
})

async function openDetail(a: AppointmentInfo): Promise<void> {
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

function fmtTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

function severityTag(sev: string): 'danger' | 'warning' | 'success' {
  return sev === 'red' ? 'danger' : sev === 'yellow' ? 'warning' : 'success'
}

function severityLabel(sev: string): string {
  return sev === 'red' ? '红色' : sev === 'yellow' ? '黄色' : '绿色'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <BackHome />
      <h2>
        预约工单
        <el-badge v-if="pendingCount" :value="pendingCount" class="badge">
          <el-tag size="small" type="warning" effect="plain">新预约</el-tag>
        </el-badge>
      </h2>
      <el-radio-group v-model="statusFilter" @change="refresh">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="pending">待接单</el-radio-button>
        <el-radio-button value="accepted">已接单</el-radio-button>
        <el-radio-button value="completed">已完成</el-radio-button>
        <el-radio-button value="cancelled">已取消</el-radio-button>
      </el-radio-group>
    </header>

    <div v-loading="loading">
      <el-empty v-if="!loading && filtered.length === 0" description="暂无预约工单" />
      <el-card v-for="a in filtered" :key="a.id" class="appt-card" shadow="hover" @click="openDetail(a)">
        <div class="row">
          <div class="line-top">
            <span class="id">#{{ a.id }}</span>
            <el-tag :type="STATUS_META[a.status].type" effect="dark" size="small">{{ STATUS_META[a.status].label }}</el-tag>
          </div>
          <div class="owner">{{ a.owner_name }} · {{ a.vehicle || '未关联车辆' }}</div>
          <div v-if="a.summary_card" class="summary">
            <el-tag :type="severityTag(a.summary_card.severity)" size="small">{{ severityLabel(a.summary_card.severity) }}</el-tag>
            <span class="summary-text">{{ oneLine(a.summary_card.summary) }}</span>
          </div>
          <div class="time">{{ fmtTime(a.appointment_time) }}</div>
        </div>
      </el-card>
    </div>

    <el-drawer v-model="drawerVisible" :title="detail ? `工单 #${detail.id}` : ''" :size="drawerSize">
      <template v-if="detail">
        <div class="detail-block">
          <p class="label">车主 / 车辆</p>
          <p>{{ detail.owner_name }} · {{ detail.vehicle || '未关联车辆' }}</p>
        </div>
        <div class="detail-block">
          <p class="label">预约时间</p>
          <p>{{ fmtTime(detail.appointment_time) }}</p>
        </div>

        <div v-if="detail.summary_card" class="detail-block summary-card">
          <p class="label">AI 诊断摘要卡（始终可见）</p>
          <p>
            <el-tag :type="severityTag(detail.summary_card.severity)" size="small">{{ severityLabel(detail.summary_card.severity) }}</el-tag>
            {{ detail.summary_card.summary }}
          </p>
          <ul v-if="detail.summary_card.hypotheses.length"><li v-for="h in detail.summary_card.hypotheses" :key="h">{{ h }}</li></ul>
          <ol v-if="detail.summary_card.steps.length"><li v-for="s in detail.summary_card.steps" :key="s">{{ s }}</li></ol>
          <p v-if="detail.summary_card.pending_checks.length" class="muted">待确认：{{ detail.summary_card.pending_checks.join('；') }}</p>
          <p v-if="detail.summary_card.note" class="muted">车主说明：{{ detail.summary_card.note }}</p>
        </div>

        <div class="detail-block">
          <p class="label">对话记录</p>
          <template v-if="dialogMessages.length">
            <div v-for="(m, i) in dialogMessages" :key="i" class="msg" :class="m.role">
              {{ m.role === 'user' ? '车主' : 'AI' }}：{{ m.content }}
            </div>
          </template>
          <p v-else class="muted">{{ dialogBlocked || '暂无对话' }}</p>
        </div>

        <div v-if="detail.status === 'pending'" class="detail-block">
          <p class="label">接单（可改约时间）</p>
          <el-date-picker v-model="acceptForm.time" type="datetime" format="YYYY-MM-DD HH:mm" placeholder="确认/修改到店时间" />
          <el-input v-model="acceptForm.note" class="gap-top" placeholder="备注（如：备件已备）" maxlength="500" />
          <div class="actions">
            <el-button type="primary" @click="accept">确认接单</el-button>
            <el-button type="danger" plain @click="cancel(detail)">取消工单</el-button>
          </div>
        </div>

        <div v-if="detail.status === 'accepted'" class="detail-block">
          <p class="label">服务完成 · 回填结果</p>
          <el-input v-model="completeForm.result" type="textarea" :rows="3" maxlength="2000" placeholder="维修/验证结果，回填后将同步车主" />
          <div class="actions">
            <el-button type="primary" @click="complete">提交并完成工单</el-button>
            <el-button type="danger" plain @click="cancel(detail)">取消工单</el-button>
          </div>
        </div>

        <div v-if="detail.status === 'completed'" class="detail-block">
          <p class="label">维修结果</p>
          <p>{{ detail.repair_result }}</p>
          <div class="actions">
            <el-button v-if="detail.session_id" @click="settleCase(detail)">沉淀为案例</el-button>
            <el-button type="primary" plain @click="router.push(`/report/appointment/${detail.id}`)">查看 / 打印报告</el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem; }
.page-head h2 { font-size: 1rem; margin: 0; display: flex; align-items: center; gap: 0.5rem; }
.appt-card { margin-bottom: 0.6rem; cursor: pointer; }
/* 竖排卡片：手机上四列横排会把描述挤成一条竖字 */
.row { display: flex; flex-direction: column; gap: 0.3rem; }
.line-top { display: flex; align-items: center; justify-content: space-between; }
.owner { font-size: 0.85rem; font-weight: 600; }
.summary { display: flex; align-items: flex-start; gap: 0.4rem; font-size: 0.78rem; }
.summary-text { line-height: 1.45; }
.time { font-size: 0.75rem; color: var(--muted); }
.id { font-size: 0.75rem; color: var(--muted); }
.detail-block { margin-bottom: 1.1rem; }
.label { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.35rem; }
.summary-card ul, .summary-card ol { margin: 0.3rem 0 0.3rem 1.2rem; font-size: 0.8rem; }
.muted { color: var(--muted); font-size: 0.78rem; }
.msg { font-size: 0.78rem; padding: 0.3rem 0.5rem; border-radius: 6px; margin-bottom: 0.3rem; background: var(--surface); }
.msg.user { background: var(--accent-dim, #eef); }
.actions { display: flex; gap: 0.5rem; margin-top: 0.6rem; flex-wrap: wrap; }
.gap-top { margin-top: 0.5rem; }
</style>
