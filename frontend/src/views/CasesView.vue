<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { fmtIso, listCases, oneLine, type CaseInfo } from '../api/client'
import DataTable from '../components/DataTable.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatusChip from '../components/StatusChip.vue'
import type { TableColumn } from '../components/ui-types'

const router = useRouter()
const cases = ref<CaseInfo[]>([])
const loading = ref(false)
const keyword = ref('')
const severityFilter = ref('')
const detailOpen = ref(false)
const selected = ref<CaseInfo | null>(null)

const SEVERITY_TAG: Record<string, { severity: string; label: string }> = {
  red: { severity: 'red', label: '需尽快检修' },
  yellow: { severity: 'yellow', label: '建议到店检查' },
  green: { severity: 'green', label: '正常' },
  需尽快检修: { severity: 'red', label: '需尽快检修' },
  建议到店检查: { severity: 'yellow', label: '建议到店检查' },
  正常: { severity: 'green', label: '正常' },
}

const columns: TableColumn[] = [
  { key: 'title', label: '案例', minWidth: 210, primary: true },
  { key: 'vehicle', label: '车型', minWidth: 150 },
  { key: 'severity', label: '严重度', width: 120 },
  { key: 'symptoms', label: '症状摘要', minWidth: 220 },
  { key: 'created_at', label: '沉淀时间', width: 130 },
]

function sevMeta(c: CaseInfo): { severity: string; label: string } | null {
  const m = /^【(.+?)】\s*/.exec(c.diagnosis)
  return (m && SEVERITY_TAG[m[1]]) || null
}

function diagBody(c: CaseInfo): string {
  const m = /^【.+?】\s*/.exec(c.diagnosis)
  return m ? c.diagnosis.slice(m[0].length) : c.diagnosis
}

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return cases.value.filter((item) => {
    if (severityFilter.value) {
      const meta = sevMeta(item)
      if (!meta || meta.severity !== severityFilter.value) return false
    }
    if (!q) return true
    const haystack = [item.title, item.symptoms, item.diagnosis, item.repair_result, item.vehicle, item.plate_no]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(q)
  })
})

const rows = computed<Record<string, unknown>[]>(() =>
  filtered.value.map((item) => {
    const meta = sevMeta(item)
    return {
      id: item.id,
      title: item.title,
      vehicle: [item.vehicle, item.plate_no].filter(Boolean).join(' · ') || '未关联车辆',
      severity: meta?.severity ?? '',
      severity_label: meta?.label ?? '',
      plate: item.plate_no || '无车牌',
      symptoms: oneLine(item.symptoms || diagBody(item), 52),
      created_at: fmtIso(item.created_at),
      raw: item,
    }
  }),
)

function openDetail(row: Record<string, unknown>): void {
  const source = row.raw as CaseInfo | undefined
  if (!source) return
  selected.value = source
  detailOpen.value = true
}

async function refresh(): Promise<void> {
  loading.value = true
  try {
    cases.value = await listCases()
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '加载案例失败')
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="案例库" subtitle="门店确认的检修案例；沉淀后自动回流知识库，进入后续诊断检索范围">
      <template #actions>
        <el-button @click="router.push('/staff/appointments')">从工单沉淀案例</el-button>
      </template>
    </PageHeader>

    <section class="filters hmi-card">
      <el-input v-model="keyword" placeholder="搜索案例标题 / 症状 / 车型 / 车牌" clearable class="q" aria-label="搜索案例" />
      <el-select v-model="severityFilter" placeholder="严重度" clearable class="sel" aria-label="按严重度筛选">
        <el-option label="红色" value="red" />
        <el-option label="黄色" value="yellow" />
        <el-option label="绿色" value="green" />
      </el-select>
      <span class="hmi-sub count">共 {{ filtered.length }} 条</span>
    </section>

    <DataTable
      :rows="rows"
      :columns="columns"
      :loading="loading"
      empty-text="暂无匹配案例"
      mobile-title-key="title"
      @row-click="openDetail"
    >
      <template #cell-title="{ row }">
        <div class="title-cell">
          <strong>{{ row.title }}</strong>
          <span class="hmi-sub">{{ row.plate }}</span>
        </div>
      </template>
      <template #cell-severity="{ row }">
        <SeverityBadge v-if="row.severity" :severity="String(row.severity)" />
        <StatusChip v-else label="未标注" tone="neutral" />
      </template>
      <template #cell-created_at="{ row }">
        <span class="hmi-mono small">{{ row.created_at }}</span>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text type="primary" @click.stop="openDetail(row)">查看</el-button>
      </template>
    </DataTable>

    <el-drawer v-model="detailOpen" title="案例详情" size="min(94vw, 520px)">
      <template v-if="selected">
        <div class="detail-head">
          <h3>{{ selected.title }}</h3>
          <SeverityBadge v-if="sevMeta(selected)" :severity="sevMeta(selected)?.severity ?? ''" />
        </div>
        <p class="hmi-sub">
          {{ selected.vehicle || '未关联车型' }} · {{ selected.plate_no || '无车牌' }} ·
          {{ fmtIso(selected.created_at) }}
        </p>

        <section class="block">
          <h4>症状</h4>
          <p class="pre">{{ selected.symptoms || '（未记录）' }}</p>
        </section>
        <section class="block">
          <h4>诊断结论</h4>
          <p class="pre">{{ diagBody(selected) || '（未记录）' }}</p>
        </section>
        <section v-if="selected.repair_result" class="block">
          <h4>维修验证</h4>
          <p class="pre">{{ selected.repair_result }}</p>
        </section>

        <el-alert
          class="flow-alert"
          type="success"
          :closable="false"
          show-icon
          title="已回流知识库"
          description="该案例已按 category=case 摄入知识库，店主/店员后续诊断可通过知识库检索命中；对话原文不进入案例。"
        />
        <div class="detail-actions">
          <el-button @click="router.push('/staff/dtc')">故障码速查</el-button>
          <el-button @click="router.push('/staff/appointments')">返回工单</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
  padding: 0.7rem 0.8rem;
}

.q {
  inline-size: min(100%, 320px);
}

.sel {
  inline-size: 120px;
}

.count {
  margin-inline-start: auto;
}

.title-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.title-cell strong {
  font-weight: 600;
}

.small {
  font-size: var(--hmi-fs-1);
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
}

.detail-head h3 {
  font-size: 1rem;
  font-weight: 650;
}

.block {
  margin-block-start: 0.9rem;
}

.block h4 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block-end: 0.3rem;
}

.block p {
  font-size: var(--hmi-fs-2);
  line-height: 1.7;
  color: var(--hmi-text-2);
}

.pre {
  white-space: pre-wrap;
}

.flow-alert {
  margin-block-start: 1rem;
}

.detail-actions {
  display: flex;
  gap: 0.5rem;
  margin-block-start: 0.8rem;
  flex-wrap: wrap;
}

@media (max-width: 560px) {
  .filters {
    flex-direction: column;
    align-items: stretch;
  }

  .q,
  .sel {
    inline-size: 100%;
  }

  .count {
    margin-inline-start: 0;
  }
}
</style>
