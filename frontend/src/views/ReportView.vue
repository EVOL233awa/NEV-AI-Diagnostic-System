<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchAppointmentDetail, type AppointmentInfo, type AppointmentStatus } from '../api/client'
import BackHome from '../components/BackHome.vue'

const STATUS_META: Record<AppointmentStatus, string> = {
  pending: '待接单',
  accepted: '已接单',
  completed: '已完成',
  cancelled: '已取消',
}

const route = useRoute()
const appt = ref<AppointmentInfo | null>(null)
const loading = ref(true)
const error = ref('')

const severityLabel = computed(() => {
  const sev = appt.value?.summary_card?.severity
  return sev === 'red' ? '红色（尽快检修）' : sev === 'yellow' ? '黄色（建议到店检查）' : '绿色（正常范围）'
})

function fmtTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

function printReport(): void {
  window.print()
}

async function load(): Promise<void> {
  const id = Number(route.params.id)
  if (!Number.isInteger(id) || id <= 0) {
    error.value = '无效的预约编号'
    loading.value = false
    return
  }
  try {
    appt.value = await fetchAppointmentDetail(id)
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    error.value = resp?.data?.detail ?? '加载预约详情失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="report-page" v-loading="loading">
    <BackHome />
    <div v-if="error" class="error">{{ error }}</div>

    <div v-else-if="appt" class="report-sheet">
      <header class="sheet-head">
        <h1>新能源汽车诊断报告</h1>
        <p class="sub">工单 #{{ appt.id }} · 生成时间 {{ new Date().toLocaleString('zh-CN') }}</p>
      </header>

      <table class="info-table">
        <tbody>
          <tr><th>车主</th><td>{{ appt.owner_name }}</td><th>车辆</th><td>{{ appt.vehicle || '未登记' }}</td></tr>
          <tr><th>预约时间</th><td>{{ fmtTime(appt.appointment_time) }}</td><th>工单状态</th><td>{{ STATUS_META[appt.status] ?? appt.status }}</td></tr>
        </tbody>
      </table>

      <section v-if="appt.summary_card" class="sheet-section">
        <h2>诊断结论 · {{ severityLabel }}</h2>
        <p class="summary">{{ appt.summary_card.summary }}</p>
        <template v-if="appt.summary_card.hypotheses.length">
          <h3>故障假设</h3>
          <ul><li v-for="h in appt.summary_card.hypotheses" :key="h">{{ h }}</li></ul>
        </template>
        <template v-if="appt.summary_card.steps.length">
          <h3>建议检修步骤</h3>
          <ol><li v-for="s in appt.summary_card.steps" :key="s">{{ s }}</li></ol>
        </template>
        <template v-if="appt.summary_card.pending_checks.length">
          <h3>仍需到店确认</h3>
          <ul><li v-for="c in appt.summary_card.pending_checks" :key="c">{{ c }}</li></ul>
        </template>
      </section>
      <section v-else class="sheet-section">
        <h2>诊断结论</h2>
        <p class="muted">该预约没有关联的 AI 诊断结论。</p>
      </section>

      <section class="sheet-section">
        <h2>维修结果</h2>
        <p v-if="appt.repair_result">{{ appt.repair_result }}</p>
        <p v-else class="muted">服务完成后由店员回填。</p>
      </section>

      <section v-if="appt.shop_note" class="sheet-section">
        <h2>门店备注</h2>
        <p>{{ appt.shop_note }}</p>
      </section>
    </div>

    <div v-if="appt" class="sheet-actions">
      <el-button type="primary" round @click="printReport">🖨 打印 / 另存 PDF</el-button>
    </div>
  </div>
</template>

<style scoped>
.report-page {
  max-width: 820px;
  margin: 0 auto;
  padding: 1.25rem 1rem 3rem;
}

.error {
  background: var(--danger-bg, rgba(220, 38, 38, 0.12));
  border: 1px solid rgba(220, 38, 38, 0.45);
  color: #f87171;
  border-radius: 10px;
  padding: 0.8rem 1rem;
  margin: 1rem 0;
}

.sheet-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}

.report-sheet {
  background: #ffffff;
  color: #1f2430;
  border-radius: 10px;
  padding: 2rem 2.2rem;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}

.sheet-head h1 {
  margin: 0;
  font-size: 1.4rem;
}

.sub {
  color: #6b7280;
  font-size: 0.85rem;
  margin: 0.3rem 0 0;
}

.info-table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.2rem 0;
}

.info-table th,
.info-table td {
  border: 1px solid #d8dce6;
  padding: 0.45rem 0.6rem;
  font-size: 0.9rem;
  text-align: left;
}

.info-table th {
  width: 6em;
  background: #f3f5f9;
  color: #4b5563;
  font-weight: 600;
}

.sheet-section h2 {
  font-size: 1.05rem;
  margin: 1.2rem 0 0.5rem;
}

.sheet-section h3 {
  font-size: 0.92rem;
  margin: 0.9rem 0 0.3rem;
  color: #374151;
}

.summary {
  line-height: 1.7;
  margin: 0;
}

.sheet-section ul,
.sheet-section ol {
  margin: 0.2rem 0;
  padding-left: 1.4rem;
  line-height: 1.8;
}

.sheet-section p {
  margin: 0.2rem 0;
}

.muted {
  color: #9aa3b2;
}

@media print {
  .report-page {
    max-width: none;
    padding: 0;
    margin: 0;
  }

  .sheet-actions,
  :deep(.back-home) {
    display: none !important;
  }

  .report-sheet {
    box-shadow: none;
    border-radius: 0;
    padding: 0;
  }
}
</style>
