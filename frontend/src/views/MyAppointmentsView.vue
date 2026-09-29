<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  SEVERITY_LABEL,
  cancelAppointment,
  createAppointment,
  listAppointments,
  localIso,
  type AppointmentInfo,
  type AppointmentStatus,
} from '../api/client'
import BackHome from '../components/BackHome.vue'

const appointments = ref<AppointmentInfo[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

const form = ref<{ time: Date | null; note: string }>({ time: null, note: '' })

const STATUS_META: Record<AppointmentStatus, { label: string; type: 'warning' | 'primary' | 'success' | 'info' }> = {
  pending: { label: '待接单', type: 'warning' },
  accepted: { label: '已接单', type: 'primary' },
  completed: { label: '已完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
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

async function cancel(a: AppointmentInfo): Promise<void> {
  try {
    await cancelAppointment(a.id, '车主取消')
    ElMessage.success('已取消')
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
    <header class="page-head">
      <BackHome />
      <h2>我的预约</h2>
      <el-button type="primary" @click="dialogVisible = true">新建预约</el-button>
    </header>

    <div v-loading="loading">
      <el-empty v-if="!loading && appointments.length === 0" description="还没有预约记录" />
      <el-card v-for="a in appointments" :key="a.id" class="appt-card">
        <div class="row">
          <div class="left">
            <div class="time">{{ fmtTime(a.appointment_time) }}</div>
            <div class="vehicle">{{ a.vehicle || '未关联车辆' }}</div>
            <div v-if="a.summary_card" class="summary">
              <el-tag :type="a.summary_card.severity === 'red' ? 'danger' : a.summary_card.severity === 'yellow' ? 'warning' : 'success'" size="small">
                {{ SEVERITY_LABEL[a.summary_card.severity] ?? '正常' }}
              </el-tag>
              <span>{{ a.summary_card.summary }}</span>
            </div>
            <div v-if="a.repair_result" class="result">维修结果：{{ a.repair_result }}</div>
            <div v-if="a.shop_note" class="note">门店备注：{{ a.shop_note }}</div>
          </div>
          <div class="right">
            <el-tag :type="STATUS_META[a.status].type" effect="dark">{{ STATUS_META[a.status].label }}</el-tag>
            <el-button v-if="canCancel(a)" size="small" text type="danger" @click="cancel(a)">取消预约</el-button>
          </div>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="dialogVisible" title="新建预约" width="420px">
      <el-form label-width="90px">
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
  </div>
</template>

<style scoped>
.page { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.page-head h2 { font-size: 1rem; margin: 0; }
.appt-card { margin-bottom: 0.7rem; }
.row { display: flex; justify-content: space-between; gap: 1rem; }
.left { flex: 1; display: flex; flex-direction: column; gap: 0.3rem; }
.time { font-weight: 600; }
.vehicle { font-size: 0.8rem; color: var(--muted); }
/* 行内流式排布：标签置行首，摘要全文宽自然换行，窄屏不再被挤成窄列 */
.summary { font-size: 0.8rem; line-height: 1.7; }
.summary .el-tag { margin-right: 0.4rem; }
.result, .note { font-size: 0.78rem; color: var(--muted); }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 0.5rem; }
</style>
