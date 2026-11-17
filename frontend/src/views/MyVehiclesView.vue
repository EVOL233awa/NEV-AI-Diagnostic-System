<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  DIAG_STAGE_LABEL,
  addVehicle,
  deleteVehicle,
  fetchVehicleHistory,
  fmtIso,
  listMyVehicles,
  oneLine,
  patchVehicle,
  type DiagBrief,
  type VehicleInfo,
} from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatusChip from '../components/StatusChip.vue'

const vehicles = ref<VehicleInfo[]>([])
const loading = ref(false)
const manageVisible = ref(false)
/** 历史诊断折叠状态：默认全部收起，点击展开 */
const expanded = reactive<Record<number, boolean>>({})

const historyVisible = ref(false)
const historyVehicle = ref<VehicleInfo | null>(null)
const historyItems = ref<DiagBrief[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historyLoading = ref(false)
const HISTORY_PAGE = 20

const mileageVisible = ref(false)
const mileageVehicle = ref<VehicleInfo | null>(null)
const mileageValue = ref<number | undefined>(undefined)
const mileageSaving = ref(false)

const form = reactive({
  brand: '',
  model_name: '',
  model_year: '',
  power_type: 'EV',
  vin: '',
  plate_no: '',
  notes: '',
  mileage: undefined as number | undefined,
})

const POWER_LABEL: Record<string, string> = { EV: '纯电', PHEV: '插混', REEV: '增程', ICE: '燃油' }

async function refresh(): Promise<void> {
  loading.value = true
  try {
    vehicles.value = await listMyVehicles()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载车辆失败')
  } finally {
    loading.value = false
  }
}

function toggleHistory(id: number): void {
  expanded[id] = !expanded[id]
}

async function openHistory(v: VehicleInfo): Promise<void> {
  historyVehicle.value = v
  historyVisible.value = true
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

function openMileage(v: VehicleInfo): void {
  mileageVehicle.value = v
  mileageValue.value = v.mileage ?? undefined
  mileageVisible.value = true
}

async function saveMileage(): Promise<void> {
  const vehicle = mileageVehicle.value
  if (!vehicle) return
  mileageSaving.value = true
  try {
    await patchVehicle(vehicle.id, { mileage: mileageValue.value ?? null })
    mileageVisible.value = false
    ElMessage.success('里程已更新')
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    mileageSaving.value = false
  }
}

async function submit(): Promise<void> {
  if (!(form.brand || form.model_name || form.vin || form.plate_no)) {
    ElMessage.warning('至少填写品牌/车型/VIN/车牌其一')
    return
  }
  try {
    await addVehicle({ ...form })
    ElMessage.success('车辆已添加')
    Object.assign(form, { brand: '', model_name: '', model_year: '', power_type: 'EV', vin: '', plate_no: '', notes: '', mileage: undefined })
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

async function removeVehicle(v: VehicleInfo): Promise<void> {
  const name = [v.brand, v.model_name, v.plate_no].filter(Boolean).join(' ') || `车辆 #${v.id}`
  try {
    await ElMessageBox.confirm(
      `确定删除「${name}」？删除后该车的档案及其历史诊断关联将一并移除。`,
      '删除车辆',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteVehicle(v.id)
    ElMessage.success('车辆已删除')
    delete expanded[v.id]
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

async function setDefault(v: VehicleInfo): Promise<void> {
  try {
    await patchVehicle(v.id, { is_default: true })
    ElMessage.success('已设为默认车辆')
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="我的车辆" subtitle="档案、里程与完整诊断历史；历史只展示诊断摘要，不含对话原文">
      <template #actions>
        <el-button type="primary" @click="manageVisible = true">管理车辆</el-button>
      </template>
    </PageHeader>

    <EmptyState
      v-if="!loading && vehicles.length === 0"
      title="还没有车辆档案"
      description="添加品牌/车型或车牌后，新诊断会自动归档到默认车辆。"
    >
      <el-button type="primary" size="small" @click="manageVisible = true">添加车辆</el-button>
    </EmptyState>

    <div v-loading="loading" class="vehicle-grid">
      <article v-for="v in vehicles" :key="v.id" class="vehicle-card hmi-card">
        <header class="card-head">
          <div class="name-block">
            <h2>{{ v.brand || '未命名' }} {{ v.model_name }}</h2>
            <span class="year">{{ v.model_year || '年款未填' }}</span>
          </div>
          <div class="tags">
            <StatusChip v-if="v.is_default" label="默认车辆" tone="accent" dot />
            <StatusChip v-if="v.power_type" :label="POWER_LABEL[v.power_type] ?? v.power_type" tone="neutral" />
          </div>
        </header>

        <dl class="facts">
          <div>
            <dt>车牌</dt>
            <dd class="hmi-mono">{{ v.plate_no || '—' }}</dd>
          </div>
          <div>
            <dt>VIN</dt>
            <dd class="hmi-mono">{{ v.vin || '—' }}</dd>
          </div>
          <div>
            <dt>里程</dt>
            <dd>
              <span class="hmi-mono">{{ v.mileage != null ? `${v.mileage.toLocaleString()} km` : '未记录' }}</span>
              <el-button text size="small" type="primary" @click="openMileage(v)">更新</el-button>
            </dd>
          </div>
        </dl>
        <p v-if="v.notes" class="notes">{{ v.notes }}</p>

        <section class="latest">
          <div class="latest-head">
            <h3>最近诊断</h3>
            <el-button v-if="v.history?.length" text size="small" @click="openHistory(v)">完整历史 →</el-button>
          </div>
          <template v-if="v.history?.length">
            <div class="latest-main">
              <SeverityBadge :severity="v.history[0].severity" />
              <span v-if="v.history[0].stage" class="stage">{{ DIAG_STAGE_LABEL[v.history[0].stage] }}</span>
              <span class="time hmi-mono">{{ fmtIso(v.history[0].created_at) }}</span>
            </div>
            <p class="latest-summary">{{ oneLine(v.history[0].summary, 64) }}</p>

            <button type="button" class="history-toggle" @click="toggleHistory(v.id)">
              历史记录（{{ v.history.length }}）<span class="chev" aria-hidden="true">{{ expanded[v.id] ? '▾' : '▸' }}</span>
            </button>
            <div v-show="expanded[v.id]" class="history-list">
              <div v-for="(h, i) in v.history" :key="i" class="history-row">
                <div class="history-top">
                  <div class="history-tags">
                    <SeverityBadge :severity="h.severity" />
                    <StatusChip v-if="h.stage" :label="DIAG_STAGE_LABEL[h.stage]" tone="neutral" />
                    <StatusChip v-if="h.has_case" label="已沉淀案例" tone="info" />
                  </div>
                  <span class="time hmi-mono">{{ fmtIso(h.created_at) }}</span>
                </div>
                <p class="history-text">{{ oneLine(h.summary) }}</p>
              </div>
            </div>
          </template>
          <p v-else class="muted">暂无历史诊断</p>
        </section>

        <footer class="card-foot">
          <el-button v-if="!v.is_default" size="small" text type="primary" @click="setDefault(v)">设为默认车辆</el-button>
          <el-button size="small" text type="danger" @click="removeVehicle(v)">删除</el-button>
        </footer>
      </article>
    </div>

    <el-dialog v-model="manageVisible" title="管理车辆" width="min(94vw, 540px)">
      <div class="manage-list">
        <p v-if="vehicles.length === 0" class="muted">暂无车辆，在下方添加。</p>
        <div v-for="v in vehicles" :key="v.id" class="manage-row">
          <span class="manage-name">
            {{ v.brand }} {{ v.model_name }}
            <span class="manage-plate">{{ v.plate_no || '未上车牌' }}</span>
            <StatusChip v-if="v.is_default" label="默认" tone="accent" />
          </span>
          <el-button size="small" text type="danger" @click="removeVehicle(v)">删除</el-button>
        </div>
      </div>

      <el-divider content-position="left">添加新车辆</el-divider>
      <el-form label-width="76px">
        <div class="form-grid">
          <el-form-item label="品牌"><el-input v-model="form.brand" placeholder="如 比亚迪" /></el-form-item>
          <el-form-item label="车型"><el-input v-model="form.model_name" placeholder="如 汉 EV" /></el-form-item>
          <el-form-item label="年款"><el-input v-model="form.model_year" placeholder="如 2023" /></el-form-item>
          <el-form-item label="能源类型">
            <el-select v-model="form.power_type">
              <el-option label="纯电" value="EV" />
              <el-option label="插混" value="PHEV" />
              <el-option label="增程" value="REEV" />
              <el-option label="燃油" value="ICE" />
            </el-select>
          </el-form-item>
          <el-form-item label="VIN"><el-input v-model="form.vin" placeholder="选填" /></el-form-item>
          <el-form-item label="车牌"><el-input v-model="form.plate_no" placeholder="如 桂A·12345" /></el-form-item>
        </div>
        <el-form-item label="里程">
          <el-input-number v-model="form.mileage" :min="0" :max="2000000" :step="1000" controls-position="right" placeholder="选填，单位 km" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" placeholder="充电习惯、使用场景等" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manageVisible = false">关闭</el-button>
        <el-button type="primary" @click="submit">添加车辆</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mileageVisible" title="更新里程" width="min(92vw, 360px)">
      <p class="mileage-vehicle">
        {{ mileageVehicle ? [mileageVehicle.brand, mileageVehicle.model_name, mileageVehicle.plate_no].filter(Boolean).join(' ') : '' }}
      </p>
      <el-input-number v-model="mileageValue" :min="0" :max="2000000" :step="1000" controls-position="right" class="mileage-input" />
      <p class="muted small">留空保存将清除里程记录。里程用于保养提示与诊断参考，不校验真实性。</p>
      <template #footer>
        <el-button @click="mileageVisible = false">取消</el-button>
        <el-button type="primary" :loading="mileageSaving" @click="saveMileage">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="完整诊断历史" width="min(94vw, 640px)">
      <p class="history-vehicle">
        {{ historyVehicle ? [historyVehicle.brand, historyVehicle.model_name, historyVehicle.plate_no].filter(Boolean).join(' ') : '' }}
        <span class="muted">共 {{ historyTotal }} 次</span>
      </p>
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
    </el-dialog>
  </div>
</template>

<style scoped>
.vehicle-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), 1fr));
  gap: 0.8rem;
}

.vehicle-card {
  display: flex;
  flex-direction: column;
  padding: 0.95rem 1rem 0.6rem;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
}

.name-block h2 {
  font-size: 1.05rem;
  font-weight: 650;
}

.year {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.tags {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.facts {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.35rem;
  margin: 0.7rem 0 0;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface-2);
}

.facts > div {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  font-size: var(--hmi-fs-2);
}

.facts dt {
  flex: 0 0 48px;
  color: var(--hmi-text-3);
}

.facts dd {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.2rem;
  min-inline-size: 0;
  color: var(--hmi-text-2);
  overflow-wrap: anywhere;
}

.notes {
  margin-block-start: 0.5rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.latest {
  margin-block-start: 0.7rem;
  padding-block-start: 0.6rem;
  border-block-start: 1px solid var(--hmi-line-soft);
  flex: 1 1 auto;
}

.latest-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}

.latest-head h3 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
}

.latest-main {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-block-start: 0.4rem;
}

.stage {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.latest-summary {
  margin-block-start: 0.25rem;
  font-size: var(--hmi-fs-3);
  color: var(--hmi-text-2);
}

.time {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  margin-inline-start: auto;
  white-space: nowrap;
}

.history-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: none;
  border: 0;
  padding: 0.35rem 0 0;
  color: var(--hmi-accent);
  font-size: var(--hmi-fs-2);
  cursor: pointer;
}

.chev {
  font-size: 0.7rem;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-block-start: 0.35rem;
}

.history-row {
  padding: 0.45rem 0.55rem;
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

.history-text {
  margin-block-start: 0.25rem;
  font-size: var(--hmi-fs-2);
  line-height: 1.5;
  color: var(--hmi-text-2);
}

.history-session {
  margin-block-start: 0.2rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.card-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.3rem;
  margin-block-start: 0.5rem;
  padding-block-start: 0.4rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.manage-list {
  max-block-size: 200px;
  overflow-y: auto;
}

.manage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.1rem;
  border-block-end: 1px solid var(--hmi-line-soft);
  font-size: var(--hmi-fs-3);
}

.manage-row:last-child {
  border-block-end: 0;
}

.manage-name {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.manage-plate {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 0.6rem;
}

.muted {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.small {
  font-size: var(--hmi-fs-1);
}

.mileage-vehicle {
  font-weight: 600;
  margin-block-end: 0.6rem;
}

.mileage-input {
  inline-size: 100%;
}

.history-vehicle {
  margin: 0 0 0.6rem;
  font-weight: 600;
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
}

.full-history {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-block-size: 80px;
  max-block-size: 55vh;
  overflow-y: auto;
}

.history-pager {
  margin-block-start: 0.7rem;
  justify-content: center;
}

@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
