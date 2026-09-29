<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { SEVERITY_LABEL, addVehicle, deleteVehicle, fmtIso, listMyVehicles, oneLine, patchVehicle, type VehicleInfo } from '../api/client'
import BackHome from '../components/BackHome.vue'

const vehicles = ref<VehicleInfo[]>([])
const loading = ref(false)
const manageVisible = ref(false)
/** 历史诊断折叠状态：默认全部收起，点击展开 */
const expanded = reactive<Record<number, boolean>>({})

const form = reactive({
  brand: '',
  model_name: '',
  model_year: '',
  power_type: 'EV',
  vin: '',
  plate_no: '',
  notes: '',
})

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

async function submit(): Promise<void> {
  if (!(form.brand || form.model_name || form.vin || form.plate_no)) {
    ElMessage.warning('至少填写品牌/车型/VIN/车牌其一')
    return
  }
  try {
    await addVehicle({ ...form })
    ElMessage.success('车辆已添加')
    Object.assign(form, { brand: '', model_name: '', model_year: '', power_type: 'EV', vin: '', plate_no: '', notes: '' })
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

const POWER_LABEL: Record<string, string> = { EV: '纯电', PHEV: '插混', REEV: '增程', ICE: '燃油' }

onMounted(refresh)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <BackHome />
      <h2>我的车辆</h2>
      <el-button type="primary" @click="manageVisible = true">管理车辆</el-button>
    </header>

    <div v-loading="loading" class="cards">
      <el-empty v-if="!loading && vehicles.length === 0" description="还没有车辆档案，点右上角管理车辆添加" />
      <el-card v-for="v in vehicles" :key="v.id" class="vehicle-card">
        <template #header>
          <div class="card-head">
            <span class="title">{{ v.brand }} {{ v.model_name }} <span class="year">{{ v.model_year }}</span></span>
            <div class="tags">
              <el-tag v-if="v.is_default" size="small" type="success" effect="dark">默认</el-tag>
              <el-tag v-if="v.power_type" size="small">{{ POWER_LABEL[v.power_type] ?? v.power_type }}</el-tag>
            </div>
          </div>
        </template>
        <p class="meta">车牌：{{ v.plate_no || '—' }}　VIN：{{ v.vin || '—' }}</p>
        <p v-if="v.notes" class="notes">{{ v.notes }}</p>
        <template v-if="v.history && v.history.length">
          <button class="history-toggle" type="button" @click="toggleHistory(v.id)">
            历史诊断（{{ v.history.length }}）<span class="chev">{{ expanded[v.id] ? '▾' : '▸' }}</span>
          </button>
          <div v-show="expanded[v.id]" class="history-list">
            <div v-for="(h, i) in v.history" :key="i" class="history-row">
              <div class="history-top">
                <el-tag :type="h.severity === 'red' ? 'danger' : h.severity === 'yellow' ? 'warning' : 'success'" size="small">
                  {{ SEVERITY_LABEL[h.severity] ?? '正常' }}
                </el-tag>
                <span class="history-time">{{ fmtIso(h.created_at) }}</span>
              </div>
              <p class="history-text">{{ oneLine(h.summary) }}</p>
            </div>
          </div>
        </template>
        <p v-else class="muted">暂无历史诊断</p>
        <template #footer>
          <el-button v-if="!v.is_default" size="small" text type="primary" @click="setDefault(v)">设为默认车辆</el-button>
        </template>
      </el-card>
    </div>

    <el-dialog v-model="manageVisible" title="管理车辆" width="520px">
      <div class="manage-list">
        <p v-if="vehicles.length === 0" class="muted">暂无车辆，在下方添加。</p>
        <div v-for="v in vehicles" :key="v.id" class="manage-row">
          <span class="manage-name">
            {{ v.brand }} {{ v.model_name }}
            <span class="manage-plate">{{ v.plate_no || '未上车牌' }}</span>
            <el-tag v-if="v.is_default" size="small" type="success" effect="dark">默认</el-tag>
          </span>
          <el-button size="small" text type="danger" @click="removeVehicle(v)">删除</el-button>
        </div>
      </div>

      <el-divider content-position="left">添加新车辆</el-divider>
      <el-form label-width="72px">
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
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" placeholder="充电习惯、使用场景等" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manageVisible = false">关闭</el-button>
        <el-button type="primary" @click="submit">添加车辆</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.page-head h2 { font-size: 1rem; margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 0.9rem; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.title { font-weight: 600; }
.year { color: var(--muted); font-weight: 400; font-size: 0.8rem; }
.tags { display: flex; gap: 0.3rem; }
.meta { font-size: 0.78rem; color: var(--muted); margin: 0 0 0.4rem; }
.notes { font-size: 0.8rem; margin: 0 0 0.4rem; }
.history-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: none;
  border: none;
  padding: 0;
  margin: 0.4rem 0 0.2rem;
  color: var(--accent, #409eff);
  font-size: 0.8rem;
  cursor: pointer;
}
.chev { font-size: 0.75rem; }
.history-list { margin-top: 0.2rem; display: flex; flex-direction: column; gap: 0.45rem; }
.history-row {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
}
.history-top { display: flex; align-items: center; justify-content: space-between; gap: 0.45rem; }
.history-text { margin: 0.25rem 0 0; font-size: 0.78rem; line-height: 1.45; }
.history-time { color: var(--muted); font-size: 0.7rem; white-space: nowrap; }
.manage-list { max-height: 200px; overflow-y: auto; }
.manage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.2rem;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  font-size: 0.85rem;
}
.manage-row:last-child { border-bottom: none; }
.manage-name { display: flex; align-items: center; gap: 0.4rem; }
.manage-plate { color: var(--muted); font-size: 0.75rem; }
.muted { color: var(--muted); font-size: 0.78rem; }
</style>
