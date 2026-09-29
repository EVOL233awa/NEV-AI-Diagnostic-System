<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { updatePrivacy } from '../api/client'
import { auth } from '../stores/auth'
import BackHome from '../components/BackHome.vue'

const isOwner = computed(() => auth.user?.role === 'owner')
const sharing = ref(auth.user?.privacy_share_dialog ?? true)

async function onPrivacyChange(value: boolean): Promise<void> {
  const prev = !value
  try {
    await updatePrivacy(value)
    sharing.value = value
    ElMessage.success(value ? '已开启：店员可查看对话记录' : '已关闭：店员仅能查看诊断摘要')
  } catch {
    sharing.value = prev
    ElMessage.error('保存失败，请重试')
  }
}

const pwd = reactive({ old: '', new1: '', new2: '' })
const pwdLoading = ref(false)

async function changePassword(): Promise<void> {
  if (pwd.new1.length < 8 || !(/[A-Za-z]/.test(pwd.new1) && /[0-9]/.test(pwd.new1))) {
    ElMessage.warning('新密码至少 8 位，须同时包含字母和数字，且不能包含账号名')
    return
  }
  if (pwd.new1 !== pwd.new2) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    const { http } = await import('../api/client')
    await http.post('/api/auth/change-password', { old_password: pwd.old, new_password: pwd.new1 })
    ElMessage.success('密码已修改')
    Object.assign(pwd, { old: '', new1: '', new2: '' })
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    pwdLoading.value = false
  }
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}
</script>

<template>
  <div class="page">
    <header class="page-head"><BackHome /><h2>设置</h2></header>

    <el-card v-if="isOwner" class="block">
      <template #header>隐私设置</template>
      <div class="privacy-row">
        <div>
          <p class="label">店员可见我的对话记录</p>
          <p class="desc">
            开启后，接待您的服务人员可以查看本次诊断的完整对话过程，便于提前准备配件、到店无需重复描述，维修更精准高效；
            关闭后，店员仅能看到 AI 生成的诊断摘要（不含您的原话）。您可随时更改，对之后的诊断立即生效。
          </p>
        </div>
        <el-switch v-model="sharing" @change="onPrivacyChange" />
      </div>
    </el-card>

    <el-card class="block">
      <template #header>修改密码</template>
      <el-form label-width="90px" class="pwd-form">
        <el-form-item label="原密码"><el-input v-model="pwd.old" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwd.new1" type="password" show-password placeholder="至少 8 位，含字母和数字" /></el-form-item>
        <el-form-item label="确认新密码"><el-input v-model="pwd.new2" type="password" show-password /></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="pwdLoading" @click="changePassword">保存新密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page { max-width: 720px; margin: 0 auto; padding: 1.5rem; display: flex; flex-direction: column; gap: 1rem; }
.page-head h2 { font-size: 1rem; margin: 0; }
.privacy-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.label { font-weight: 600; margin: 0 0 0.35rem; }
.desc { font-size: 0.78rem; color: var(--muted); margin: 0; line-height: 1.7; }
.pwd-form { max-width: 380px; }
</style>
