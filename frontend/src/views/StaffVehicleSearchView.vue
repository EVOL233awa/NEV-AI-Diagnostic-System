<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  DIAG_STAGE_LABEL,
  fetchVehicleHistory,
  fmtIso,
  oneLine,
  searchVehicles,
  type DiagBrief,
  type VehicleInfo,
} from '../api/client'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatusChip from '../components/StatusChip.vue'
import type { TableColumn } from '../components/ui-types'

const router = useRouter()
const keyword = ref('')
const results = ref<VehicleInfo[]>([])
const searched = ref(false)
const loading = ref(false)

const historyOpen = ref(false)
const historyVehicle = ref<VehicleInfo | null>(null)
const historyItems = ref<DiagBrief[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historyLoading = ref(false)
const HISTORY_PAGE = 20

const columns: TableColumn[] = [
  { key: 'title', label: '车辆', minWidth: 180, primary: true },
  { key: 'plate_no', label: '车牌', width: 120 },
  { key: 'vin', label: 'VIN', minWidth: 170 },
  { key: 'mileage', label: '里程', width: 110 },
  { key: 'latest', label: '最近诊断', minWidth: 220 },
]

const rows = computed<Record<string, unknown>[]>(() =>
  results.value.map((vehicle) => ({
    ...vehicle,
    title: [vehicle.brand, vehicle.model_name, vehicle.model_year].filter(Boolean).join(' ') || '未命名车辆',
    latest: vehicle.history?.[0] ?? null,
    latest_severity: vehicle.history?.[0]?.severity ?? '',
    latest_stage: vehicle.history?.[0]?.stage ?? null,
    latest_at: vehicle.history?.[0]?.created_at ?? null,
    latest_summary: vehicle.history?.[0]?.summary ?? '',
  })),
)

const POWER_LABEL: Record<string, string> = { EV: '纯电', PHEV: '插混', REEV: '增程', ICE: '燃油' }

async function search(): Promise<void> {
  if (!keyword.value.trim()) {
    ElMessage.warning('请输入车牌/VIN/品牌车型关键词')
    return
  }
  loading.value = true
  try {
    results.value = await searchVehicles(keyword.value)
    searched.value = true
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

function quickSearch(value: string): void {
  keyword.value = value
  void search()
}

async function openHistory(row: Record<string, unknown>): Promise<void> {
  const vehicle = results.value.find((item) => item.id === row.id)
  if (!vehicle) return
  historyVehicle.value = vehicle
  historyOpen.value = true
  await loadHistory(0)
}

async function loadHistory(offset: number): Promise<void> {
  const vehicle = historyVehicle.value
  if (!vehicle) return
  historyLoading.value = true
  try {
    const body = await fetchVehicleHistory(vehicle.id, HISTORY_PAGE, offset)
    historyItems.value = body.items
    historyTotal.value = body.total
    historyOffset.value = offset
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    historyLoading.value = false
  }
}

function onHistoryPage(page: number): void {
  void loadHistory((page - 1) * HISTORY_PAGE)
}

function openDtc(): void {
  void router.push('/staff/dtc')
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '检索失败'
}
</script>

<template>
  <div class="page">
    <PageHeader title="车辆档案检索" subtitle="按车牌 / VIN / 品牌车型查找；对话原文仅随预约工单可见">
      <template #actions>
        <el-button :icon="Search" @click="openDtc">故障码速查</el-button>
      </template>
    </PageHeader>

    <section class="search-panel hmi-card">
      <div class="search-bar">
        <el-input
          v-model="keyword"
          placeholder="输入车牌 / VIN / 品牌车型，如：桂A·8D001"
          clearable
          size="large"
          aria-label="输入车牌、VIN 或品牌车型"
          @keyup.enter="search"
        />
        <el-button type="primary" size="large" :loading="loading" @click="search">检索</el-button>
      </div>
      <div class="quick-row">
        <span class="hmi-sub">试试：</span>
        <button type="button" class="quick-chip" @click="quickSearch('桂A')">桂A</button>
        <button type="button" class="quick-chip" @click="quickSearch('比亚迪')">比亚迪</button>
        <button type="button" class="quick-chip" @click="quickSearch('汉')">汉</button>
      </div>
    </section>

    <DataTable
      :rows="rows"
      :columns="columns"
      :loading="loading"
      :mobile-title-key="'title'"
      empty-text="未找到匹配的车辆档案"
      @row-click="openHistory"
    >
      <template #cell-title="{ row }">
        <div class="vehicle-cell">
          <strong>{{ row.title }}</strong>
          <span class="hmi-sub">{{ POWER_LABEL[String(row.power_type)] ?? row.power_type }}</span>
        </div>
      </template>
      <template #cell-plate_no="{ row }">
        <span class="hmi-mono">{{ row.plate_no || '—' }}</span>
      </template>
      <template #cell-vin="{ row }">
        <span class="hmi-mono small">{{ row.vin || '—' }}</span>
      </template>
      <template #cell-mileage="{ row }">
        <span class="hmi-mono">{{ row.mileage != null ? `${Number(row.mileage).toLocaleString()} km` : '—' }}</span>
      </template>
      <template #cell-latest="{ row }">
        <div v-if="row.latest" class="latest-cell">
          <div class="latest-top">
            <SeverityBadge :severity="String(row.latest_severity)" compact />
            <span v-if="row.latest_stage" class="stage">{{ DIAG_STAGE_LABEL[String(row.latest_stage)] }}</span>
            <span class="time hmi-mono">{{ fmtIso(String(row.latest_at ?? '')) }}</span>
          </div>
          <span class="latest-text">{{ oneLine(String(row.latest_summary ?? ''), 40) }}</span>
        </div>
        <span v-else class="muted">暂无诊断</span>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text type="primary" @click.stop="openHistory(row)">历史</el-button>
        <el-button size="small" text @click.stop="openDtc">故障码</el-button>
      </template>
    </DataTable>

    <EmptyState
      v-if="searched && results.length === 0 && !loading"
      title="未找到匹配的车辆档案"
      description="可尝试车牌片段、VIN 后六位或品牌名称。"
      compact
    />

    <el-drawer v-model="historyOpen" title="完整诊断历史" size="min(94vw, 560px)">
      <p class="history-vehicle">
        {{ historyVehicle ? [historyVehicle.brand, historyVehicle.model_name, historyVehicle.plate_no].filter(Boolean).join(' ') : '' }}
        <span class="muted">共 {{ historyTotal }} 次</span>
      </p>
      <p class="hmi-sub drawer-note">仅展示诊断摘要与阶段，不含车主对话原文；原文随预约工单授权。</p>
      <div v-loading="historyLoading" class="full-history">
        <EmptyState v-if="!historyLoading && historyItems.length === 0" title="暂无历史诊断" compact />
        <div v-for="(h, i) in historyItems" :key="i" class="history-row">
          <div class="history-top">
            <div class="history-tags">
              <SeverityBadge :severity="h.severity" />
              <StatusChip v-if="h.stage" :label="DIAG_STAGE_LABEL[h.stage]" tone="neutral" />
              <StatusChip v-if="h.has_case" label="已沉淀案例" tone="info" />
            </div>
            <span class="time hmi-mono">{{ fmtIso(h.created_at) }}</span>
          </div>
          <p class="history-session">{{ h.session_title }}</p>
          <p class="history-text">{{ oneLine(h.summary) }}</p>
        </div>
      </div>
      <el-pagination
        v-if="historyTotal > HISTORY_PAGE"
        class="history-pager"
        layout="prev, pager, next"
        :page-size="HISTORY_PAGE"
        :total="historyTotal"
        :current-page="historyOffset / HISTORY_PAGE + 1"
        @current-change="onHistoryPage"
      />
    </el-drawer>
  </div>
</template>

<style scoped>
.search-panel {
  padding: 0.85rem 0.9rem;
}

.search-bar {
  display: flex;
  gap: 0.5rem;
}

.quick-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-block-start: 0.45rem;
  flex-wrap: wrap;
}

.quick-chip {
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  background: transparent;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  padding: 0.15rem 0.55rem;
  cursor: pointer;
}

.quick-chip:hover {
  border-color: var(--hmi-accent-line);
  color: var(--hmi-accent);
}

.vehicle-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.vehicle-cell strong {
  font-weight: 600;
  color: var(--hmi-text);
}

.small {
  font-size: var(--hmi-fs-1);
}

.latest-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.latest-top {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.latest-text {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.stage {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.time {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: 0.64rem;
  white-space: nowrap;
}

.muted {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.history-vehicle {
  margin: 0 0 0.4rem;
  font-weight: 600;
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  flex-wrap: wrap;
}

.drawer-note {
  margin-block-end: 0.7rem;
}

.full-history {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-block-size: 80px;
}

.history-row {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius-sm);
}

.history-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}

.history-tags {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.history-session {
  margin-block-start: 0.2rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.history-text {
  margin-block-start: 0.2rem;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
}

.history-pager {
  margin-block-start: 0.7rem;
  justify-content: center;
}

@media (max-width: 560px) {
  .search-bar {
    flex-direction: column;
  }
}
</style>
