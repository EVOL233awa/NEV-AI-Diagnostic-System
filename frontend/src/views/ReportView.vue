<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Printer } from '@element-plus/icons-vue'
import { fetchAppointmentDetail, type AppointmentInfo, type AppointmentStatus } from '../api/client'

const STATUS_META: Record<AppointmentStatus, string> = {
  pending: '待接单',
  accepted: '已接单',
  completed: '已完成',
  cancelled: '已取消',
}

const route = useRoute()
const router = useRouter()
const appt = ref<AppointmentInfo | null>(null)
const loading = ref(true)
const error = ref('')
const generatedAt = new Date().toLocaleString('zh-CN')

const severity = computed(() => appt.value?.summary_card?.severity ?? 'green')
const severityLabel = computed(() => {
  if (severity.value === 'red') return '红色 · 尽快检修'
  if (severity.value === 'yellow') return '黄色 · 建议到店检查'
  return '绿色 · 正常范围'
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
  <main class="report-page" v-loading="loading">
    <div class="toolbar no-print">
      <el-button :icon="ArrowLeft" text @click="router.push('/staff/appointments')">返回工单</el-button>
      <span class="toolbar-title">诊断报告</span>
      <el-button v-if="appt" type="primary" :icon="Printer" @click="printReport">打印 / 另存 PDF</el-button>
    </div>

    <div v-if="error" class="error" role="alert">{{ error }}</div>

    <article v-else-if="appt" class="report-sheet">
      <header class="sheet-head">
        <div class="brand-row">
          <span class="brand-mark" aria-hidden="true">NEV</span>
          <span class="brand-text">新能源汽车 AI 智能诊断系统</span>
          <span class="doc-type">诊断报告</span>
        </div>
        <h1>车辆诊断与维修报告</h1>
        <p class="sub">工单 #{{ appt.id }} · 生成时间 {{ generatedAt }}</p>
      </header>

      <section class="meta-grid">
        <div><span>车主</span><strong>{{ appt.owner_name || '—' }}</strong></div>
        <div><span>车辆</span><strong>{{ appt.vehicle || '未登记' }}</strong></div>
        <div><span>预约时间</span><strong>{{ fmtTime(appt.appointment_time) }}</strong></div>
        <div><span>工单状态</span><strong>{{ STATUS_META[appt.status] ?? appt.status }}</strong></div>
      </section>

      <section class="diagnosis" :data-severity="severity">
        <div class="diag-head">
          <span class="sev-chip">{{ severityLabel }}</span>
          <span class="diag-label">AI 诊断结论</span>
        </div>
        <p v-if="appt.summary_card" class="summary">{{ appt.summary_card.summary }}</p>
        <p v-else class="muted">该预约没有关联的 AI 诊断结论。</p>

        <template v-if="appt.summary_card">
          <div v-if="appt.summary_card.hypotheses.length" class="section">
            <h3>故障假设</h3>
            <ul><li v-for="h in appt.summary_card.hypotheses" :key="h">{{ h }}</li></ul>
          </div>
          <div v-if="appt.summary_card.steps.length" class="section">
            <h3>建议检修步骤</h3>
            <ol><li v-for="s in appt.summary_card.steps" :key="s">{{ s }}</li></ol>
          </div>
          <div v-if="appt.summary_card.pending_checks.length" class="section">
            <h3>仍需到店确认</h3>
            <ul><li v-for="c in appt.summary_card.pending_checks" :key="c">{{ c }}</li></ul>
          </div>
          <p v-if="appt.summary_card.note" class="note">车主说明：{{ appt.summary_card.note }}</p>
        </template>
      </section>

      <section class="section avoid-break">
        <h3>维修结果</h3>
        <p v-if="appt.repair_result">{{ appt.repair_result }}</p>
        <p v-else class="muted">服务完成后由店员回填。</p>
      </section>

      <section v-if="appt.shop_note" class="section avoid-break">
        <h3>门店备注</h3>
        <p>{{ appt.shop_note }}</p>
      </section>

      <footer class="sheet-foot">
        <p>本报告由 AI 辅助生成，结论需结合实车检测；仅用于本次维修沟通与存档。</p>
        <div class="sign-row">
          <span>车主签字：________________</span>
          <span>服务顾问：________________</span>
          <span>日期：________________</span>
        </div>
      </footer>
    </article>
  </main>
</template>

<style scoped>
.report-page {
  min-block-size: 100vh;
  background: #eef1f5;
  padding: 0 1rem 2.5rem;
  color: #1f2430;
}

.toolbar {
  max-inline-size: 840px;
  margin-inline: auto;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.85rem 0.2rem;
}

.toolbar-title {
  font-weight: 650;
  font-size: 0.95rem;
}

.toolbar .el-button:last-child {
  margin-inline-start: auto;
}

.toolbar :deep(.el-button.is-text) {
  color: #334155;
}

.toolbar :deep(.el-button.is-text:hover) {
  color: #0f766e;
  background: rgba(15, 118, 110, 0.08);
}

.error {
  max-inline-size: 840px;
  margin: 1rem auto;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  color: #991b1b;
  border-radius: 10px;
  padding: 0.8rem 1rem;
}

.report-sheet {
  max-inline-size: 840px;
  margin-inline: auto;
  background: #fff;
  border-radius: 6px;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.12);
  padding: 2rem 2.4rem 1.8rem;
}

.sheet-head {
  border-block-end: 2px solid #1f2937;
  padding-block-end: 0.8rem;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #4b5563;
  font-size: 0.75rem;
}

.brand-mark {
  display: inline-grid;
  place-items: center;
  background: #0f766e;
  color: #fff;
  font-weight: 700;
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  border-radius: 4px;
  padding: 0.18rem 0.4rem;
}

.brand-text {
  letter-spacing: 0.02em;
}

.doc-type {
  margin-inline-start: auto;
  color: #6b7280;
}

.sheet-head h1 {
  margin: 0.55rem 0 0;
  font-size: 1.55rem;
  letter-spacing: 0.02em;
}

.sub {
  color: #6b7280;
  font-size: 0.8rem;
  margin-block-start: 0.25rem;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border: 1px solid #d8dce6;
  margin-block: 1.1rem;
}

.meta-grid > div {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  padding: 0.5rem 0.7rem;
  border-block-end: 1px solid #e5e7eb;
}

.meta-grid > div:nth-child(odd) {
  border-inline-end: 1px solid #e5e7eb;
}

.meta-grid > div:nth-last-child(-n + 2) {
  border-block-end: 0;
}

.meta-grid span {
  color: #6b7280;
  font-size: 0.78rem;
  min-inline-size: 4.5em;
}

.meta-grid strong {
  font-weight: 600;
  font-size: 0.88rem;
}

.diagnosis {
  border: 1px solid #e5e7eb;
  border-inline-start: 4px solid #d97706;
  border-radius: 4px;
  padding: 0.8rem 0.9rem;
  background: #fffbeb;
}

.diagnosis[data-severity='red'] {
  border-inline-start-color: #dc2626;
  background: #fef2f2;
}

.diagnosis[data-severity='green'] {
  border-inline-start-color: #059669;
  background: #ecfdf5;
}

.diag-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.sev-chip {
  font-size: 0.75rem;
  font-weight: 700;
  color: #92400e;
}

.diagnosis[data-severity='red'] .sev-chip { color: #991b1b; }
.diagnosis[data-severity='green'] .sev-chip { color: #065f46; }

.diag-label {
  color: #6b7280;
  font-size: 0.7rem;
  letter-spacing: 0.04em;
}

.summary {
  margin-block-start: 0.45rem;
  font-size: 0.95rem;
  line-height: 1.7;
  font-weight: 600;
}

.section {
  margin-block-start: 1rem;
}

.section h3 {
  font-size: 0.88rem;
  margin-block-end: 0.3rem;
  color: #374151;
}

.section p,
.diagnosis p {
  margin: 0.2rem 0;
  line-height: 1.7;
  font-size: 0.86rem;
}

.section ul,
.section ol {
  margin: 0.2rem 0;
  padding-inline-start: 1.4rem;
  line-height: 1.8;
  font-size: 0.86rem;
}

.note {
  margin-block-start: 0.5rem;
  color: #6b7280;
  font-size: 0.8rem;
}

.muted {
  color: #6b7280;
}

.sheet-foot {
  margin-block-start: 1.4rem;
  padding-block-start: 0.8rem;
  border-block-start: 1px solid #d8dce6;
  color: #6b7280;
  font-size: 0.72rem;
}

.sign-row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  margin-block-start: 1rem;
  color: #374151;
  font-size: 0.8rem;
}

.avoid-break {
  break-inside: avoid;
}

@media (max-width: 640px) {
  .report-page {
    padding-inline: 0.5rem;
  }

  .report-sheet {
    padding: 1.2rem 1rem;
  }

  .meta-grid {
    grid-template-columns: 1fr;
  }

  .meta-grid > div:nth-child(odd) {
    border-inline-end: 0;
  }

  .meta-grid > div:nth-last-child(-n + 2) {
    border-block-end: 1px solid #e5e7eb;
  }

  .meta-grid > div:last-child {
    border-block-end: 0;
  }
}

@media print {
  .report-page {
    padding: 0;
    background: #fff;
  }

  .report-sheet {
    box-shadow: none;
    border-radius: 0;
    padding: 0;
    max-inline-size: none;
  }

  .sign-row {
    margin-block-start: 1.4rem;
  }
}
</style>
