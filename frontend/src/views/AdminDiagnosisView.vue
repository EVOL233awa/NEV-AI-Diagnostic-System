<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  DIAG_STAGE_LABEL,
  fetchDiagDetail,
  fetchDiagOverview,
  fmtIso,
  listDiagSessions,
  type DiagDetail,
  type DiagOverview,
  type DiagSessionRow,
  type DiagTrace,
} from '../api/client'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StageTimeline from '../components/StageTimeline.vue'
import StatCard from '../components/StatCard.vue'
import StatusChip from '../components/StatusChip.vue'
import type { ChipTone, TableColumn } from '../components/ui-types'

interface DiagPayload {
  severity?: string
  summary?: string
  hypotheses?: { title?: string; evidence_ids?: string[] }[]
  steps?: string[]
  pending_checks?: string[]
}

const rows = ref<DiagSessionRow[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const PAGE_SIZE = 20
const overview = ref<DiagOverview | null>(null)

const filters = reactive({ q: '', severity: '', stage: '', status: '' })

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<DiagDetail | null>(null)
const detailTab = ref<'chat' | 'evidence' | 'map'>('chat')

const columns: TableColumn[] = [
  { key: 'updated', label: '更新', width: 130 },
  { key: 'title', label: '会话', minWidth: 200, primary: true },
  { key: 'vehicle', label: '车辆', minWidth: 160 },
  { key: 'stage', label: '阶段', width: 120 },
  { key: 'severity', label: '严重度', width: 112 },
  { key: 'counts', label: '消息 / 证据', width: 108 },
]

const tableRows = computed<Record<string, unknown>[]>(() =>
  rows.value.map((row) => ({
    id: row.id,
    updated: fmtIso(row.updated_at),
    title: row.title,
    owner: row.owner.username,
    vehicle: vehicleLabel(row),
    stage: row.stage,
    stage_inferred: row.stage_inferred,
    severity: row.severity,
    counts: `${row.message_count} / ${row.evidence_count}`,
    raw: row,
  })),
)

const percent = (value: number): string => `${Math.round(value * 100)}%`

const stageTrail = computed(() => {
  const info = detail.value?.session
  if (!info) return []
  if (info.stage_history.length) return info.stage_history
  return [{ stage: info.stage, at: '' }]
})

function asDiag(value: Record<string, unknown> | null): DiagPayload {
  return (value ?? {}) as DiagPayload
}

function vehicleLabel(row: DiagSessionRow): string {
  if (!row.vehicle) return '未关联车辆'
  return [row.vehicle.brand, row.vehicle.model_name, row.vehicle.plate_no].filter(Boolean).join(' ') || `车辆 #${row.vehicle.id}`
}

function stageTone(stage: string): ChipTone {
  if (stage === 'conclusion') return 'ok'
  if (stage === 'verification') return 'accent'
  if (stage === 'hypothesis') return 'warn'
  return 'neutral'
}

function traceTitle(trace: DiagTrace): string {
  return trace.title || trace.domain || (trace.kind === 'kb' ? '知识库' : '网页结果')
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const body = await listDiagSessions({
      q: filters.q.trim() || undefined,
      severity: filters.severity || undefined,
      stage: filters.stage || undefined,
      status: filters.status || undefined,
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    rows.value = body.items
    total.value = body.total
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

async function loadOverview(): Promise<void> {
  try {
    overview.value = await fetchDiagOverview()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

function search(): void {
  page.value = 1
  void load()
}

function reset(): void {
  Object.assign(filters, { q: '', severity: '', stage: '', status: '' })
  search()
}

function onPage(value: number): void {
  page.value = value
  void load()
}

async function openDetail(row: Record<string, unknown>): Promise<void> {
  const source = row.raw as DiagSessionRow | undefined
  if (!source) return
  drawerVisible.value = true
  detailLoading.value = true
  detailTab.value = 'chat'
  detail.value = null
  try {
    detail.value = await fetchDiagDetail(source.id)
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    detailLoading.value = false
  }
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}

onMounted(() => {
  void load()
  void loadOverview()
})
</script>

<template>
  <div class="page">
    <PageHeader title="诊断质控" subtitle="阶段时间线 · 假设↔证据映射 · 车主授权后才展示原文">
      <template #actions>
        <el-button :icon="Refresh" @click="load()">刷新</el-button>
      </template>
    </PageHeader>

    <div v-if="overview" class="hmi-grid hmi-grid--stats diag-kpis">
      <StatCard label="今日会话" :value="overview.today_sessions" tone="accent" hint="今日新建诊断" />
      <StatCard label="进行中" :value="overview.active_sessions" tone="info" hint="未结束会话" />
      <StatCard label="已出结论" :value="overview.conclusion_sessions" tone="ok" hint="结构化诊断" />
      <StatCard label="结论覆盖率" :value="percent(overview.conclusion_rate)" tone="ok" hint="已出结论 / 总会话" />
      <StatCard label="假设关联证据" :value="percent(overview.evidence_link_rate)" tone="warn" hint="带证据编号的假设" />
      <StatCard label="证据条目" :value="overview.evidence_total" tone="default" hint="知识库 + 网页命中" />
    </div>

    <section class="filters hmi-card">
      <el-input v-model="filters.q" placeholder="车牌 / VIN / 车主 / 会话标题" clearable class="q" aria-label="搜索诊断会话" @keyup.enter="search" />
      <el-select v-model="filters.severity" placeholder="严重度" clearable class="sel" aria-label="按严重度筛选">
        <el-option label="红色" value="red" />
        <el-option label="黄色" value="yellow" />
        <el-option label="绿色" value="green" />
      </el-select>
      <el-select v-model="filters.stage" placeholder="阶段" clearable class="sel" aria-label="按阶段筛选">
        <el-option v-for="(label, value) in DIAG_STAGE_LABEL" :key="value" :label="label" :value="value" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable class="sel" aria-label="按会话状态筛选">
        <el-option label="进行中" value="active" />
        <el-option label="已结束" value="closed" />
      </el-select>
      <el-button type="primary" @click="search">筛选</el-button>
      <el-button @click="reset">重置</el-button>
    </section>

    <DataTable
      :rows="tableRows"
      :columns="columns"
      :loading="loading"
      empty-text="没有符合条件的诊断会话"
      mobile-title-key="title"
      @row-click="openDetail"
    >
      <template #cell-updated="{ row }">
        <span class="hmi-mono small">{{ row.updated }}</span>
      </template>
      <template #cell-title="{ row }">
        <div class="session-cell">
          <strong>{{ row.title }}</strong>
          <span class="hmi-sub">{{ row.owner || '—' }}</span>
        </div>
      </template>
      <template #cell-stage="{ row }">
        <div class="stage-cell">
          <StatusChip :label="DIAG_STAGE_LABEL[String(row.stage)] ?? String(row.stage)" :tone="stageTone(String(row.stage))" />
          <span v-if="row.stage_inferred" class="inferred">推断</span>
        </div>
      </template>
      <template #cell-severity="{ row }">
        <SeverityBadge v-if="row.severity" :severity="String(row.severity)" />
        <span v-else class="muted">—</span>
      </template>
      <template #cell-counts="{ row }">
        <span class="hmi-mono">{{ row.counts }}</span>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text type="primary" @click.stop="openDetail(row)">质控</el-button>
      </template>
    </DataTable>

    <el-pagination
      v-if="total > PAGE_SIZE"
      class="pager"
      layout="total, prev, pager, next"
      :page-size="PAGE_SIZE"
      :total="total"
      :current-page="page"
      @current-change="onPage"
    />

    <el-drawer v-model="drawerVisible" title="诊断质控详情" size="min(96vw, 780px)">
      <div v-loading="detailLoading" class="detail">
        <template v-if="detail">
          <el-alert
            v-if="!detail.raw_included"
            type="warning"
            :closable="false"
            show-icon
            title="车主未授权查看原文"
            description="对话内容与检索词已脱敏；阶段、严重度摘要、知识库标题/章节与证据关联仍可用于质控。"
          />
          <el-alert
            v-else
            type="success"
            :closable="false"
            show-icon
            title="车主已授权查看原文"
            description="本次查看已记入审计日志。"
          />

          <section class="detail-head">
            <div>
              <h3>{{ detail.session.title }}</h3>
              <p class="hmi-sub">
                车主 {{ detail.owner.username || '—' }} · {{ detail.session.status === 'active' ? '进行中' : '已结束' }}
                · 创建 {{ fmtIso(detail.session.created_at) }} · 更新 {{ fmtIso(detail.session.updated_at) }}
              </p>
              <p v-if="detail.vehicle" class="hmi-sub">
                {{ [detail.vehicle.brand, detail.vehicle.model_name, detail.vehicle.model_year].filter(Boolean).join(' ') }}
                · {{ detail.vehicle.plate_no || '无车牌' }}
                · {{ detail.vehicle.mileage != null ? `${detail.vehicle.mileage.toLocaleString()} km` : '里程未记录' }}
              </p>
            </div>
            <div class="head-tags">
              <StatusChip v-if="detail.session.stage" :label="DIAG_STAGE_LABEL[detail.session.stage]" :tone="stageTone(detail.session.stage)" />
              <StatusChip :label="`证据 ${detail.traces.length}`" tone="info" />
              <StatusChip :label="`假设 ${detail.counts.linked_hypotheses}/${detail.counts.hypotheses}`" tone="neutral" />
            </div>
          </section>

          <StageTimeline :history="stageTrail" :inferred="detail.session.stage_inferred" />

          <el-tabs v-model="detailTab">
            <el-tab-pane label="对话" name="chat">
              <EmptyState v-if="detail.messages.length === 0" title="没有对话内容" compact />
              <div v-else class="chat-list">
                <article v-for="message in detail.messages" :key="message.id" class="chat-row">
                  <header class="chat-head">
                    <StatusChip :label="message.role === 'user' ? '车主' : 'AI 诊断'" :tone="message.role === 'user' ? 'neutral' : 'accent'" />
                    <span class="hmi-sub">{{ fmtIso(message.created_at) }}</span>
                  </header>
                  <p class="chat-text">{{ message.content }}</p>
                  <div v-if="message.diag" class="diag-box">
                    <div class="diag-line">
                      <SeverityBadge v-if="asDiag(message.diag).severity" :severity="asDiag(message.diag).severity ?? ''" />
                      <span>{{ asDiag(message.diag).summary }}</span>
                    </div>
                    <ul v-if="asDiag(message.diag).hypotheses?.length" class="diag-list">
                      <li v-for="(h, i) in asDiag(message.diag).hypotheses" :key="i">
                        {{ h.title }}
                        <span v-if="h.evidence_ids?.length" class="keys">
                          <span v-for="key in h.evidence_ids" :key="key" class="key hmi-mono">{{ key }}</span>
                        </span>
                        <span v-else class="unlinked">未关联证据</span>
                      </li>
                    </ul>
                    <p v-if="asDiag(message.diag).pending_checks?.length" class="pending">
                      待确认：{{ asDiag(message.diag).pending_checks?.join('；') }}
                    </p>
                  </div>
                </article>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="`证据链（${detail.traces.length}）`" name="evidence">
              <EmptyState v-if="detail.traces.length === 0" title="本轮没有检索证据" compact />
              <div v-else class="evidence-list">
                <article v-for="trace in detail.traces" :key="trace.id" class="evidence-row">
                  <div class="evidence-top">
                    <span class="key hmi-mono">{{ trace.evidence_key }}</span>
                    <StatusChip :label="trace.kind === 'kb' ? '知识库' : '网页'" :tone="trace.kind === 'kb' ? 'info' : 'neutral'" />
                    <span class="evidence-title">{{ traceTitle(trace) }}</span>
                    <span class="score hmi-mono">{{ trace.score.toFixed(3) }}</span>
                  </div>
                  <p v-if="trace.section_path" class="hmi-sub">{{ trace.section_path }}</p>
                  <p class="evidence-query">{{ trace.query }}</p>
                  <p v-if="trace.snippet" class="evidence-snippet">{{ trace.snippet }}</p>
                </article>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="`假设映射（${detail.counts.linked_hypotheses}/${detail.counts.hypotheses}）`" name="map">
              <EmptyState v-if="detail.evidence_map.length === 0" title="还没有结构化诊断假设" compact />
              <div v-for="(item, i) in detail.evidence_map" :key="i" class="map-row">
                <div class="map-title">
                  <StatusChip :label="item.linked ? '已关联' : '未关联'" :tone="item.linked ? 'ok' : 'neutral'" />
                  <span>{{ item.title || '（未命名假设）' }}</span>
                </div>
                <div class="map-evidence">
                  <span v-for="trace in item.evidence" :key="trace.id" class="map-chip">
                    <b class="hmi-mono">{{ trace.evidence_key }}</b> {{ traceTitle(trace) }}
                  </span>
                  <span v-if="!item.linked" class="muted">模型未给出证据编号（不回填猜测）</span>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.7rem 0.8rem;
}

.q {
  inline-size: min(100%, 280px);
}

.sel {
  inline-size: 118px;
}

.small {
  font-size: var(--hmi-fs-1);
}

.session-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.session-cell strong {
  font-weight: 600;
}

.stage-cell {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.inferred {
  color: var(--hmi-text-3);
  font-size: 0.62rem;
}

.muted {
  color: var(--hmi-text-3);
}

.pager {
  margin-block-start: 0.7rem;
  justify-content: flex-end;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  min-block-size: 200px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.7rem;
  flex-wrap: wrap;
}

.detail-head h3 {
  font-size: 1rem;
  font-weight: 650;
}

.head-tags {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.chat-list,
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.chat-row {
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  padding: 0.6rem 0.7rem;
  background: var(--hmi-surface);
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.chat-text {
  white-space: pre-wrap;
  margin-block: 0.4rem;
  font-size: var(--hmi-fs-2);
  line-height: 1.65;
  color: var(--hmi-text-2);
}

.diag-box {
  border-block-start: 1px dashed var(--hmi-line);
  padding-block-start: 0.45rem;
}

.diag-line {
  display: flex;
  gap: 0.4rem;
  align-items: center;
  font-size: var(--hmi-fs-2);
  flex-wrap: wrap;
}

.diag-list {
  margin: 0.35rem 0 0;
  padding-inline-start: 1.1rem;
  font-size: var(--hmi-fs-2);
  line-height: 1.6;
  color: var(--hmi-text-2);
}

.keys {
  display: inline-flex;
  gap: 0.2rem;
  margin-inline-start: 0.35rem;
}

.key {
  color: var(--hmi-accent);
  font-size: var(--hmi-fs-1);
}

.unlinked {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  margin-inline-start: 0.35rem;
}

.pending {
  margin-block-start: 0.3rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.evidence-row {
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  padding: 0.55rem 0.65rem;
  background: var(--hmi-surface);
}

.evidence-top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.evidence-title {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text);
}

.score {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.evidence-query {
  margin-block-start: 0.3rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.evidence-snippet {
  margin-block-start: 0.25rem;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-2);
  line-height: 1.55;
}

.map-row {
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  padding: 0.55rem 0.65rem;
  margin-block-end: 0.5rem;
}

.map-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--hmi-fs-3);
}

.map-evidence {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
  margin-block-start: 0.4rem;
}

.map-chip {
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-2);
}

@media (min-width: 641px) and (max-width: 900px) {
  .diag-kpis {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .filters {
    flex-direction: column;
  }

  .q,
  .sel {
    inline-size: 100%;
  }
}
</style>
