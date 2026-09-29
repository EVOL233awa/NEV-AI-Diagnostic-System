<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fmtIso, oneLine, searchVehicles, type VehicleInfo } from '../api/client'
import BackHome from '../components/BackHome.vue'

const keyword = ref('')
const results = ref<VehicleInfo[]>([])
const searched = ref(false)
const loading = ref(false)

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

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '检索失败'
}

function severityTag(sev: string): 'danger' | 'warning' | 'success' {
  return sev === 'red' ? 'danger' : sev === 'yellow' ? 'warning' : 'success'
}

function severityLabel(sev: string): string {
  return sev === 'red' ? '红色' : sev === 'yellow' ? '黄色' : '绿色'
}
</script>

<template>
  <div class="page">
    <header class="page-head"><BackHome /><h2>车辆档案检索</h2></header>

    <div class="search-bar">
      <el-input
        v-model="keyword"
        placeholder="输入车牌 / VIN / 品牌车型，如：桂A·8D001"
        clearable
        @keyup.enter="search"
      />
      <el-button type="primary" :loading="loading" @click="search">检索</el-button>
    </div>

    <el-empty v-if="searched && results.length === 0 && !loading" description="未找到匹配的车辆档案" />
    <el-card v-for="v in results" :key="v.id" class="result-card">
      <template #header>
        <span class="title">{{ v.brand }} {{ v.model_name }} {{ v.model_year }}</span>
        <el-tag size="small" class="plate">{{ v.plate_no || v.vin || '无牌号' }}</el-tag>
      </template>
      <p class="meta">VIN：{{ v.vin || '—' }}　车牌：{{ v.plate_no || '—' }}</p>
      <p v-if="v.notes" class="meta">{{ v.notes }}</p>
      <template v-if="v.history && v.history.length">
        <p class="section">历史诊断摘要（对话原文仅随预约工单可见）</p>
        <div v-for="(h, i) in v.history" :key="i" class="history-row">
          <div class="history-top">
            <el-tag :type="severityTag(h.severity)" size="small">{{ severityLabel(h.severity) }}</el-tag>
            <span class="time">{{ fmtIso(h.created_at) }}</span>
          </div>
          <p class="text">{{ oneLine(h.summary) }}</p>
        </div>
      </template>
      <p v-else class="muted">暂无历史诊断</p>
    </el-card>
  </div>
</template>

<style scoped>
.page { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
.page-head h2 { font-size: 1rem; margin: 0 0 1rem; }
.search-bar { display: flex; gap: 0.6rem; margin-bottom: 1.2rem; }
.result-card { margin-bottom: 0.8rem; }
.title { font-weight: 600; }
.plate { margin-left: 0.5rem; }
.meta { font-size: 0.78rem; color: var(--muted); margin: 0 0 0.35rem; }
.section { font-size: 0.78rem; color: var(--muted); margin: 0.6rem 0 0.3rem; }
.history-row {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  margin-bottom: 0.4rem;
}
.history-top { display: flex; align-items: center; justify-content: space-between; gap: 0.45rem; }
.text { margin: 0.25rem 0 0; font-size: 0.78rem; line-height: 1.45; flex: none; }
.time { color: var(--muted); font-size: 0.7rem; white-space: nowrap; }
.muted { color: var(--muted); font-size: 0.78rem; }
</style>
