<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  setAdminUserPassword,
  updateAdminUser,
  type AdminUserInfo,
  type AuthUser,
} from '../api/client'
import DataTable from '../components/DataTable.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import StatusChip from '../components/StatusChip.vue'
import type { TableColumn } from '../components/ui-types'

const users = ref<AdminUserInfo[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const keyword = ref('')
const roleFilter = ref('')
const statusFilter = ref('')

const form = reactive({
  username: '',
  display_name: '',
  role: 'owner' as AuthUser['role'],
  v_brand: '',
  v_model: '',
  v_year: '',
  v_power: 'EV',
  v_vin: '',
  v_plate: '',
  v_notes: '',
})

const ROLE_LABEL: Record<'owner' | 'staff' | 'admin', string> = { owner: '车主', staff: '店员', admin: '管理员' }

const columns: TableColumn[] = [
  { key: 'username', label: '账号', width: 120, primary: true },
  { key: 'display_name', label: '姓名', width: 110 },
  { key: 'role', label: '角色', width: 176 },
  { key: 'vehicle', label: '车辆', minWidth: 150 },
  { key: 'status', label: '状态', width: 96 },
  { key: 'last_login_at', label: '最近登录', width: 140 },
]

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return users.value.filter((user) => {
    if (roleFilter.value && user.role !== roleFilter.value) return false
    if (statusFilter.value === 'active' && user.disabled) return false
    if (statusFilter.value === 'disabled' && !user.disabled) return false
    if (!q) return true
    return [user.username, user.display_name, user.vehicle].filter(Boolean).join(' ').toLowerCase().includes(q)
  })
})

const rows = computed<Record<string, unknown>[]>(() =>
  filtered.value.map((user) => ({
    id: user.id,
    username: user.username,
    display_name: user.display_name || '—',
    role: user.role,
    role_label: ROLE_LABEL[user.role as keyof typeof ROLE_LABEL] ?? user.role,
    vehicle: user.vehicle || '—',
    disabled: user.disabled,
    status: user.disabled ? '已停用' : '正常',
    last_login_at: user.last_login_at?.replace('T', ' ').slice(0, 16) ?? '—',
  })),
)

function userOf(row: Record<string, unknown>): AdminUserInfo | undefined {
  return users.value.find((item) => item.id === Number(row.id))
}

async function refresh(): Promise<void> {
  loading.value = true
  try {
    users.value = await listAdminUsers()
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  try {
    const res = await createAdminUser({
      username: form.username,
      display_name: form.display_name,
      role: form.role,
      vehicle_brand: form.v_brand,
      vehicle_model: form.v_model,
      vehicle_year: form.v_year,
      vehicle_power_type: form.v_power,
      vehicle_vin: form.v_vin,
      vehicle_plate: form.v_plate,
      vehicle_notes: form.v_notes,
    })
    ElMessage.success(`账号 ${res.username} 已创建，初始密码 = 账号名`)
    dialogVisible.value = false
    Object.assign(form, {
      username: '', display_name: '', role: 'owner',
      v_brand: '', v_model: '', v_year: '', v_power: 'EV', v_vin: '', v_plate: '', v_notes: '',
    })
    await refresh()
  } catch (e) {
    ElMessage.error(extractError(e))
  }
}

async function toggleDisabled(row: Record<string, unknown>): Promise<void> {
  const user = userOf(row)
  if (!user) return
  const action = user.disabled ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(`确认${action}账号 ${user.username}？`, '确认')
    await updateAdminUser(user.id, { disabled: !user.disabled })
    ElMessage.success(`已${action}`)
    await refresh()
  } catch {
    return
  }
}

async function resetPwd(row: Record<string, unknown>): Promise<void> {
  const user = userOf(row)
  if (!user) return
  try {
    await ElMessageBox.confirm(`把 ${user.username} 的密码重置为账号名？`, '重置密码')
    await resetAdminUserPassword(user.id)
    ElMessage.success('密码已重置为账号名')
  } catch {
    return
  }
}

async function changeRole(row: Record<string, unknown>, role: string): Promise<void> {
  const user = userOf(row)
  if (!user || role === user.role) return
  try {
    await ElMessageBox.confirm(`确认把 ${user.username} 的角色改为 ${ROLE_LABEL[role as keyof typeof ROLE_LABEL]}？`, '改角色')
    await updateAdminUser(user.id, { role })
    ElMessage.success('角色已更新')
    await refresh()
  } catch {
    await refresh()
  }
}

const pwdDialog = ref(false)
const pwdTarget = ref<AdminUserInfo | null>(null)
const pwdForm = reactive({ new1: '', new2: '' })
const pwdLoading = ref(false)

function openPwd(row: Record<string, unknown>): void {
  const user = userOf(row)
  if (!user) return
  pwdTarget.value = user
  Object.assign(pwdForm, { new1: '', new2: '' })
  pwdDialog.value = true
}

async function submitPwd(): Promise<void> {
  const target = pwdTarget.value
  if (!target) return
  if (pwdForm.new1.length < 8 || !(/[A-Za-z]/.test(pwdForm.new1) && /[0-9]/.test(pwdForm.new1))) {
    ElMessage.warning('新密码至少 8 位，须同时包含字母和数字，且不能包含账号名')
    return
  }
  if (pwdForm.new1 !== pwdForm.new2) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await setAdminUserPassword(target.id, pwdForm.new1)
    ElMessage.success(`已为 ${target.username} 设置新密码`)
    pwdDialog.value = false
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    pwdLoading.value = false
  }
}

const editDialog = ref(false)
const editTarget = ref<AdminUserInfo | null>(null)
const editName = ref('')

function openEdit(row: Record<string, unknown>): void {
  const user = userOf(row)
  if (!user) return
  editTarget.value = user
  editName.value = user.display_name
  editDialog.value = true
}

async function saveEdit(): Promise<void> {
  const target = editTarget.value
  if (!target) return
  try {
    await updateAdminUser(target.id, { display_name: editName.value.trim() })
    ElMessage.success('已保存')
    editDialog.value = false
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
    <PageHeader title="成员与角色" subtitle="账号、角色与车辆代填；停用、重置密码与改角色均写入审计日志">
      <template #actions>
        <el-button type="primary" @click="dialogVisible = true">新建账号</el-button>
      </template>
    </PageHeader>

    <section class="filters hmi-card">
      <el-input v-model="keyword" placeholder="搜索账号 / 姓名 / 车辆" clearable class="q" aria-label="搜索成员" />
      <el-select v-model="roleFilter" placeholder="全部角色" clearable class="sel" aria-label="按角色筛选">
        <el-option label="车主" value="owner" />
        <el-option label="店员" value="staff" />
        <el-option label="管理员" value="admin" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="全部状态" clearable class="sel" aria-label="按状态筛选">
        <el-option label="正常" value="active" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <span class="hmi-sub count">{{ filtered.length }} 人</span>
    </section>

    <DataTable
      :rows="rows"
      :columns="columns"
      :loading="loading"
      empty-text="暂无匹配成员"
      mobile-title-key="username"
      :action-width="232"
      @row-click="openEdit"
    >
      <template #cell-username="{ row }">
        <div class="user-cell">
          <strong>{{ row.username }}</strong>
          <span v-if="row.username === 'admin'" class="hmi-sub">内置管理员</span>
        </div>
      </template>
      <template #cell-role="{ row }">
        <div class="role-cell">
          <StatusChip :label="String(row.role_label)" :tone="row.role === 'admin' ? 'warn' : row.role === 'staff' ? 'accent' : 'info'" />
          <el-select
            v-if="row.username !== 'admin'"
            :model-value="row.role"
            size="small"
            class="role-select"
            aria-label="修改角色"
            @change="(value: string) => changeRole(row, value)"
          >
            <el-option v-for="(label, value) in ROLE_LABEL" :key="value" :label="label" :value="value" />
          </el-select>
        </div>
      </template>
      <template #cell-status="{ row }">
        <StatusChip :label="String(row.status)" :tone="row.disabled ? 'danger' : 'ok'" dot />
      </template>
      <template #cell-last_login_at="{ row }">
        <span class="hmi-mono small">{{ row.last_login_at }}</span>
      </template>
      <template #actions="{ row }">
        <el-button size="small" text @click.stop="openEdit(row)">编辑</el-button>
        <el-button size="small" text type="primary" @click.stop="openPwd(row)">改密码</el-button>
        <el-button size="small" text type="warning" @click.stop="resetPwd(row)">重置</el-button>
        <el-button size="small" text :type="row.disabled ? 'success' : 'danger'" @click.stop="toggleDisabled(row)">
          {{ row.disabled ? '启用' : '停用' }}
        </el-button>
      </template>
    </DataTable>

    <el-alert
      class="audit-hint"
      type="info"
      :closable="false"
      show-icon
      title="敏感操作留痕"
      description="停用、改角色、重置密码与设置新密码都会写入审计日志；超级管理员账号不在此表，也不可被赋予。"
    />

    <el-dialog v-model="dialogVisible" title="新建账号（初始密码 = 账号名）" width="min(94vw, 520px)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="账号"><el-input v-model="form.username" placeholder="3~32 位字母/数字/下划线" /></el-form-item>
          <el-form-item label="姓名"><el-input v-model="form.display_name" placeholder="留空则同账号" /></el-form-item>
        </div>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio-button value="owner">车主</el-radio-button>
            <el-radio-button value="staff">店员</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-divider content-position="left">代填车辆（可选，仅车主角色有意义）</el-divider>
        <div class="form-grid">
          <el-form-item label="品牌"><el-input v-model="form.v_brand" placeholder="如 比亚迪" /></el-form-item>
          <el-form-item label="车型"><el-input v-model="form.v_model" placeholder="如 汉 EV" /></el-form-item>
          <el-form-item label="年款"><el-input v-model="form.v_year" /></el-form-item>
          <el-form-item label="能源类型">
            <el-select v-model="form.v_power">
              <el-option label="纯电" value="EV" /><el-option label="插混" value="PHEV" />
              <el-option label="增程" value="REEV" /><el-option label="燃油" value="ICE" />
            </el-select>
          </el-form-item>
          <el-form-item label="VIN"><el-input v-model="form.v_vin" /></el-form-item>
          <el-form-item label="车牌"><el-input v-model="form.v_plate" /></el-form-item>
        </div>
        <el-form-item label="备注"><el-input v-model="form.v_notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdDialog" :title="`修改密码 — ${pwdTarget?.username ?? ''}`" width="min(92vw, 420px)">
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new1" type="password" show-password placeholder="至少 8 位，含字母和数字" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.new2" type="password" show-password @keyup.enter="submitPwd" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitPwd">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialog" :title="`编辑成员 — ${editTarget?.username ?? ''}`" width="min(92vw, 400px)">
      <el-form label-position="top">
        <el-form-item label="显示名称">
          <el-input v-model="editName" maxlength="64" placeholder="车主/店员在系统中显示的名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
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
  inline-size: min(100%, 280px);
}

.sel {
  inline-size: 124px;
}

.count {
  margin-inline-start: auto;
}

.user-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.user-cell strong {
  font-weight: 600;
}

.role-cell {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.role-select {
  inline-size: 96px;
}

.small {
  font-size: var(--hmi-fs-1);
}

.audit-hint {
  margin-block-start: 0.2rem;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 0.6rem;
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

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
