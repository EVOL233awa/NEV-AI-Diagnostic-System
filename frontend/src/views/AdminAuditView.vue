<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchAuditLogs, type AuditLogInfo } from '../api/client'
import BackHome from '../components/BackHome.vue'

const logs = ref<AuditLogInfo[]>([])
const loading = ref(false)
const actionFilter = ref('')
const ACTIONS = [
  '', 'login', 'login_failed', 'login_locked', 'user_create', 'user_update', 'password_reset',
  'appointment_create', 'appointment_accept', 'appointment_complete', 'appointment_cancel',
  'case_create', 'vehicle_add', 'vehicle_update', 'privacy_update', 'change_password',
]

async function refresh(): Promise<void> {
  loading.value = true
  try {
    logs.value = await fetchAuditLogs(actionFilter.value || null, 200)
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <BackHome />
      <h2>审计日志</h2>
      <el-select v-model="actionFilter" placeholder="全部动作" clearable class="head-filter" @change="refresh">
        <el-option v-for="a in ACTIONS" :key="a" :label="a || '全部动作'" :value="a" />
      </el-select>
    </header>

    <el-table v-loading="loading" :data="logs" size="small">
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ row.created_at?.replace('T', ' ') ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作人" width="110">
        <template #default="{ row }">{{ row.username ?? '（未登录）' }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" width="180" />
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <code class="detail">{{ row.detail ? JSON.stringify(row.detail) : '—' }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="IP" width="120" />
    </el-table>
  </div>
</template>

<style scoped>
.page { max-width: 1020px; margin: 0 auto; padding: 1.5rem; }
.page-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; row-gap: 0.5rem; margin-bottom: 1rem; }
.page-head h2 { font-size: 1rem; margin: 0; }
/* 窄屏可收缩换行，避免与标题重叠；宽屏保持 220px 上限 */
.head-filter { flex: 1 1 160px; max-width: 220px; }
.detail { font-size: 0.7rem; word-break: break-all; }
</style>
