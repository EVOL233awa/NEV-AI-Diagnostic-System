<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchAuditLogs, fmtIso, type AuditLogInfo } from '../api/client'
import DataTable from '../components/DataTable.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import StatusChip from '../components/StatusChip.vue'
import type { TableColumn } from '../components/ui-types'

const logs = ref<AuditLogInfo[]>([])
const loading = ref(false)
const actionFilter = ref('')
const userFilter = ref('')
const range = ref<[Date, Date] | null>(null)
const detailOpen = ref(false)
const selected = ref<AuditLogInfo | null>(null)

const ACTIONS = [
  '', 'login', 'login_failed', 'login_locked', 'user_create', 'user_update', 'password_reset',
  'appointment_create', 'appointment_accept', 'appointment_complete', 'appointment_cancel',
  'case_create', 'vehicle_add', 'vehicle_update', 'vehicle_delete',
  'privacy_update', 'change_password', 'admin_view_diagnosis',
  'superadmin_config_update', 'superadmin_password_change', 'superadmin_password_reset',
]

const SENSITIVE = new Set([
  'login_failed', 'login_locked', 'password_reset', 'change_password', 'user_update',
  'vehicle_delete', 'admin_view_diagnosis', 'superadmin_config_update',
  'superadmin_password_change', 'superadmin_password_reset',
])

const columns: TableColumn[] = [
  { key: 'created_at', label: '时间', width: 150, primary: true },
  { key: 'username', label: '操作人', width: 110 },
  { key: 'action', label: '动作', minWidth: 170 },
  { key: 'brief', label: '详情', minWidth: 240 },
  { key: 'ip', label: 'IP', width: 120 },
]

const filtered = computed(() => {
  const user = userFilter.value.trim().toLowerCase()
  const [from, to] = range.value ?? []
  return logs.value.filter((log) => {
    if (user) {
      const name = (log.username ?? '（未登录）').toLowerCase()
      if (!name.includes(user)) return false
    }
    if (from && to && log.created_at) {
      const time = new Date(log.created_at).getTime()
      const start = new Date(from).setHours(0, 0, 0, 0)
      const end = new Date(to).setHours(23, 59, 59, 999)
      if (time < start || time > end) return false
    }
    return true
  })
})

const rows = computed<Record<string, unknown>[]>(() =>
  filtered.value.map((log) => ({
    id: log.id,
    created_at: fmtIso(log.created_at),
    username: log.username ?? '（未登录）',
    action: log.action,
    brief: log.detail ? JSON.stringify(log.detail).slice(0, 110) : '—',
    ip: log.ip || '—',
    sensitive: SENSITIVE.has(log.action),
    raw: log,
  })),
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    logs.value = await fetchAuditLogs(actionFilter.value || null, 300)
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

function openDetail(row: Record<string, unknown>): void {
  const source = row.raw as AuditLogInfo | undefined
  if (!source) return
  selected.value = source
  detailOpen.value = true
}

function prettyDetail(value: Record<string, unknown> | null): string {
  return value ? JSON.stringify(value, null, 2) : '—'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="审计日志" subtitle="登录、权限、隐私授权与配置变更留痕；敏感操作高亮">
      <template #actions>
        <StatusChip :label="`${filtered.length} 条`" tone="neutral" />
      </template>
    </PageHeader>

    <section class="filters hmi-card">
      <el-select v-model="actionFilter" placeholder="全部动作" clearable class="action-sel" aria-label="按动作筛选" @change="refresh">
        <el-option v-for="a in ACTIONS" :key="a" :label="a || '全部动作'" :value="a" />
      </el-select>
      <el-input v-model="userFilter" placeholder="操作人" clearable class="user-input" aria-label="按操作人筛选" />
      <el-date-picker
        v-model="range"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        class="range"
        aria-label="按日期范围筛选"
      />
    </section>

    <DataTable
      :rows="rows"
      :columns="columns"
      :loading="loading"
      empty-text="没有符合条件的审计日志"
      mobile-title-key="action"
      @row-click="openDetail"
    >
      <template #cell-created_at="{ row }">
        <span class="hmi-mono small">{{ row.created_at }}</span>
      </template>
      <template #cell-action="{ row }">
        <div class="action-cell">
          <code>{{ row.action }}</code>
          <StatusChip v-if="row.sensitive" label="敏感" tone="warn" />
        </div>
      </template>
      <template #cell-brief="{ row }">
        <span class="brief" :class="{ sensitive: row.sensitive }">{{ row.brief }}</span>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text type="primary" @click.stop="openDetail(row)">详情</el-button>
      </template>
    </DataTable>

    <el-drawer v-model="detailOpen" title="审计详情" size="min(94vw, 520px)">
      <template v-if="selected">
        <dl class="detail-grid">
          <div><dt>时间</dt><dd class="hmi-mono">{{ fmtIso(selected.created_at) }}</dd></div>
          <div><dt>操作人</dt><dd>{{ selected.username ?? '（未登录）' }}</dd></div>
          <div><dt>动作</dt><dd><code>{{ selected.action }}</code></dd></div>
          <div><dt>IP</dt><dd class="hmi-mono">{{ selected.ip || '—' }}</dd></div>
        </dl>
        <StatusChip v-if="SENSITIVE.has(selected.action)" label="敏感操作" tone="warn" dot />
        <h3 class="detail-title">详情 JSON</h3>
        <pre class="detail-json">{{ prettyDetail(selected.detail) }}</pre>
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

.action-sel {
  inline-size: 190px;
}

.user-input {
  inline-size: 150px;
}

.range {
  max-inline-size: 100%;
}

.small {
  font-size: var(--hmi-fs-1);
}

.action-cell {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.action-cell code,
.detail-grid code {
  font-family: var(--hmi-font-mono);
  font-size: var(--hmi-fs-2);
  color: var(--hmi-accent);
}

.brief {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  overflow-wrap: anywhere;
}

.brief.sensitive {
  color: var(--hmi-warn);
}

.detail-grid {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0 0 0.7rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface);
}

.detail-grid > div {
  display: flex;
  justify-content: space-between;
  gap: 0.7rem;
  font-size: var(--hmi-fs-2);
}

.detail-grid dt {
  color: var(--hmi-text-3);
}

.detail-grid dd {
  margin: 0;
  color: var(--hmi-text-2);
  text-align: end;
  overflow-wrap: anywhere;
}

.detail-title {
  margin-block: 0.8rem 0.35rem;
  font-size: var(--hmi-fs-3);
  font-weight: 650;
}

.detail-json {
  margin: 0;
  padding: 0.65rem 0.7rem;
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  background: var(--hmi-bg-deep);
  color: var(--hmi-text-2);
  font-family: var(--hmi-font-mono);
  font-size: var(--hmi-fs-1);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .filters {
    flex-direction: column;
    align-items: stretch;
    --el-date-editor-daterange-width: 100%;
  }

  .action-sel,
  .user-input,
  .range {
    inline-size: 100%;
    min-inline-size: 0;
  }

  .filters :deep(.range) {
    inline-size: 100%;
    min-inline-size: 0;
    --el-date-editor-daterange-width: 100%;
  }
}
</style>
