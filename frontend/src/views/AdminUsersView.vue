<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
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
import BackHome from '../components/BackHome.vue'

const users = ref<AdminUserInfo[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

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

// superadmin 不进本表：调试账号对成员管理不可见、也不可通过下拉赋予
const ROLE_LABEL: Record<'owner' | 'staff' | 'admin', string> = { owner: '车主', staff: '店员', admin: '管理员' }

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

async function toggleDisabled(u: AdminUserInfo): Promise<void> {
  const action = u.disabled ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(`确认${action}账号 ${u.username}？`, '确认')
    await updateAdminUser(u.id, { disabled: !u.disabled })
    ElMessage.success(`已${action}`)
    await refresh()
  } catch {
    return
  }
}

async function resetPwd(u: AdminUserInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(`把 ${u.username} 的密码重置为账号名？`, '重置密码')
    await resetAdminUserPassword(u.id)
    ElMessage.success('密码已重置为账号名')
  } catch {
    return
  }
}

const pwdDialog = ref(false)
const pwdTarget = ref<AdminUserInfo | null>(null)
const pwdForm = reactive({ new1: '', new2: '' })
const pwdLoading = ref(false)

function openPwd(u: AdminUserInfo): void {
  pwdTarget.value = u
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

async function changeRole(u: AdminUserInfo, role: string): Promise<void> {
  if (role === u.role) return
  try {
    await ElMessageBox.confirm(`确认把 ${u.username} 的角色改为 ${ROLE_LABEL[role as keyof typeof ROLE_LABEL]}？`, '改角色')
    await updateAdminUser(u.id, { role })
    ElMessage.success('角色已更新')
    await refresh()
  } catch {
    await refresh()
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
    <header class="page-head">
      <BackHome />
      <h2>成员与角色管理</h2>
      <el-button type="primary" @click="dialogVisible = true">新建账号</el-button>
    </header>

    <el-table v-loading="loading" :data="users" size="small">
      <el-table-column prop="username" label="账号" width="120" />
      <el-table-column prop="display_name" label="姓名" width="110" />
      <el-table-column label="角色" width="140">
        <template #default="{ row }">
          <el-select v-if="row.role !== 'admin' || row.username === 'admin'" :model-value="row.role" size="small" @change="(r: string) => changeRole(row, r)">
            <el-option v-for="(label, r) in ROLE_LABEL" :key="r" :label="label" :value="r" />
          </el-select>
          <el-tag v-else type="warning" size="small">{{ ROLE_LABEL[row.role as keyof typeof ROLE_LABEL] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="vehicle" label="车辆" min-width="140" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '已停用' : '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近登录" width="150">
        <template #default="{ row }">{{ row.last_login_at?.replace('T', ' ').slice(0, 16) ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" text :type="row.disabled ? 'success' : 'danger'" @click="toggleDisabled(row)">
            {{ row.disabled ? '启用' : '停用' }}
          </el-button>
          <el-button size="small" text type="primary" @click="openPwd(row)">改密码</el-button>
          <el-button size="small" text type="warning" @click="resetPwd(row)">重置</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建账号（初始密码 = 账号名）" width="480px">
      <el-form label-width="86px">
        <el-form-item label="账号"><el-input v-model="form.username" placeholder="3~32 位字母/数字/下划线，如 user002" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.display_name" placeholder="显示名称，留空则同账号" /></el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio-button value="owner">车主</el-radio-button>
            <el-radio-button value="staff">店员</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-divider content-position="left">代填车辆（可选，仅车主角色有意义）</el-divider>
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
        <el-form-item label="备注"><el-input v-model="form.v_notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="pwdDialog" :title="`修改密码 — ${pwdTarget?.username ?? ''}`" width="420px">
      <el-form label-width="90px">
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
  </div>
</template>

<style scoped>
.page { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.page-head h2 { font-size: 1rem; margin: 0; }
</style>
