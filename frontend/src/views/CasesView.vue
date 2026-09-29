<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fmtIso, listCases, oneLine, type CaseInfo } from '../api/client'
import BackHome from '../components/BackHome.vue'

const cases = ref<CaseInfo[]>([])
const loading = ref(false)
/** 案例详情折叠状态：默认收起，列表只留一句话概括 */
const expanded = reactive<Record<number, boolean>>({})

/** 诊断结论首行「【yellow】/【建议到店检查】」严重度前缀 → 彩色标签（旧数据英文等级、新数据中文，均兼容） */
const SEVERITY_TAG: Record<string, { label: string; type: 'danger' | 'warning' | 'success' }> = {
  red: { label: '需尽快检修', type: 'danger' },
  yellow: { label: '建议到店检查', type: 'warning' },
  green: { label: '正常', type: 'success' },
  需尽快检修: { label: '需尽快检修', type: 'danger' },
  建议到店检查: { label: '建议到店检查', type: 'warning' },
  正常: { label: '正常', type: 'success' },
}

function sevTag(c: CaseInfo): { label: string; type: 'danger' | 'warning' | 'success' } | null {
  const m = /^【(.+?)】\s*/.exec(c.diagnosis)
  return (m && SEVERITY_TAG[m[1]]) || null
}

function diagBody(c: CaseInfo): string {
  const m = /^【.+?】\s*/.exec(c.diagnosis)
  return m ? c.diagnosis.slice(m[0].length) : c.diagnosis
}

function toggle(id: number): void {
  expanded[id] = !expanded[id]
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
    <header class="page-head"><BackHome /><h2>案例库</h2></header>
    <div v-loading="loading">
      <el-empty v-if="!loading && cases.length === 0" description="暂无沉淀案例——在预约工单完成后可一键沉淀" />
      <el-card v-for="c in cases" :key="c.id" class="case-card">
        <template #header>
          <button class="case-head" type="button" @click="toggle(c.id)">
            <span class="title">{{ c.title }}</span>
            <span class="head-right">
              <span class="time">{{ fmtIso(c.created_at) }}</span>
              <span class="chev">{{ expanded[c.id] ? '▾' : '▸' }}</span>
            </span>
          </button>
        </template>
        <p v-if="!expanded[c.id]" class="body brief">{{ oneLine(c.symptoms || diagBody(c)) }}</p>
        <template v-else>
          <p class="section">症状</p>
          <p class="body">{{ c.symptoms || '（未记录）' }}</p>
          <p class="section">诊断结论<el-tag v-if="sevTag(c)" class="sev" :type="sevTag(c)?.type" size="small" effect="plain">{{ sevTag(c)?.label }}</el-tag></p>
          <p class="body pre">{{ diagBody(c) || '（未记录）' }}</p>
          <p v-if="c.repair_result" class="section">维修验证</p>
          <p v-if="c.repair_result" class="body">{{ c.repair_result }}</p>
        </template>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
.page-head h2 { font-size: 1rem; margin: 0 0 1rem; }
.case-card { margin-bottom: 0.8rem; }
.case-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
  color: inherit;
  font-size: inherit;
}
.head-right { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.chev { color: var(--muted); font-size: 0.75rem; }
.title { font-weight: 600; }
.time { font-size: 0.72rem; color: var(--muted); }
.brief { color: var(--muted); }
.section { font-size: 0.72rem; color: var(--muted); margin: 0.5rem 0 0.15rem; }
.sev { margin-left: 0.4rem; vertical-align: 1px; }
.body { font-size: 0.82rem; margin: 0; }
.body.pre { white-space: pre-wrap; }
</style>
