<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { updatePrivacy } from '../api/client'
import PageHeader from '../components/layout/PageHeader.vue'
import StatusChip from '../components/StatusChip.vue'
import { ROLE_LABELS, auth, patchStoredUser } from '../stores/auth'

const isOwner = computed(() => auth.user?.role === 'owner')
const sharing = ref(auth.user?.privacy_share_dialog ?? true)
const adminSharing = ref(auth.user?.privacy_share_admin ?? false)

async function onDialogPrivacyChange(value: boolean): Promise<void> {
  const prev = !value
  try {
    await updatePrivacy({ privacy_share_dialog: value })
    sharing.value = value
    patchStoredUser({ privacy_share_dialog: value })
    ElMessage.success(value ? '已开启：店员可查看对话记录' : '已关闭：店员仅能查看诊断摘要')
  } catch {
    sharing.value = prev
    ElMessage.error('保存失败，请重试')
  }
}

async function onAdminPrivacyChange(value: boolean): Promise<void> {
  const prev = !value
  try {
    await updatePrivacy({ privacy_share_admin: value })
    adminSharing.value = value
    patchStoredUser({ privacy_share_admin: value })
    ElMessage.success(value ? '已授权：管理员可查看对话原文' : '已关闭：管理员仅看阶段、摘要与证据链')
  } catch {
    adminSharing.value = prev
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
  <div class="page settings-page">
    <PageHeader title="设置" subtitle="账户、隐私授权与安全；隐私开关对之后的诊断立即生效" />

    <section class="panel hmi-card">
      <div class="panel-head">
        <h3>账户信息</h3>
        <StatusChip :label="auth.user ? ROLE_LABELS[auth.user.role] : ''" tone="accent" />
      </div>
      <dl class="info-grid">
        <div><dt>账号</dt><dd class="hmi-mono">{{ auth.user?.username }}</dd></div>
        <div><dt>显示名称</dt><dd>{{ auth.user?.display_name || '—' }}</dd></div>
      </dl>
      <p class="hmi-sub">账号与角色由门店管理员维护；如需调整请联系管理员。</p>
    </section>

    <section v-if="isOwner" class="panel hmi-card">
      <div class="panel-head"><h3>隐私授权</h3></div>

      <div class="privacy-row">
        <div class="privacy-copy">
          <p class="label">店员可见我的对话记录</p>
          <p class="desc">
            开启后，接待您的服务人员可以查看本次诊断的完整对话过程，便于提前准备配件、到店无需重复描述；
            关闭后，店员仅能看到 AI 生成的诊断摘要（不含您的原话）。
          </p>
        </div>
        <el-switch v-model="sharing" aria-label="店员可见我的对话记录" @change="onDialogPrivacyChange" />
      </div>

      <hr class="hmi-divider" />

      <div class="privacy-row">
        <div class="privacy-copy">
          <p class="label">管理员可查看我的对话原文</p>
          <p class="desc">
            仅用于服务质控与诊断质量复核，默认关闭。关闭时管理员只能看到诊断阶段、严重度摘要、
            证据来源与假设映射（不含原话、车牌、VIN 与网页检索词）；开启后可查看完整对话与检索片段。
          </p>
        </div>
        <el-switch v-model="adminSharing" aria-label="管理员可查看我的对话原文" @change="onAdminPrivacyChange" />
      </div>

      <div class="privacy-summary">
        <StatusChip :label="sharing ? '店员：完整对话' : '店员：仅摘要'" :tone="sharing ? 'accent' : 'neutral'" dot />
        <StatusChip :label="adminSharing ? '管理员：可看原文' : '管理员：仅脱敏'" :tone="adminSharing ? 'warn' : 'ok'" dot />
      </div>
    </section>

    <section class="panel hmi-card">
      <div class="panel-head"><h3>修改密码</h3></div>
      <el-form label-position="top" class="pwd-form">
        <el-form-item label="原密码">
          <el-input v-model="pwd.old" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwd.new1" type="password" show-password autocomplete="new-password" placeholder="至少 8 位，含字母和数字" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwd.new2" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button type="primary" :loading="pwdLoading" @click="changePassword">保存新密码</el-button>
      </el-form>
    </section>

    <section class="panel hmi-card">
      <div class="panel-head"><h3>外观与可访问性</h3></div>
      <ul class="appearance-list">
        <li><span>界面主题</span><strong>C HMI 深色座舱（固定）</strong></li>
        <li><span>键盘操作</span><strong>Tab 可到达主要操作，焦点高亮</strong></li>
        <li><span>动效</span><strong>跟随系统「减少动态效果」设置</strong></li>
        <li><span>触控</span><strong>粗指针设备自动放大到 44px 目标</strong></li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.settings-page {
  max-inline-size: 860px;
}

.panel {
  padding: 0.95rem 1rem;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-block-end: 0.65rem;
}

.panel-head h3 {
  font-size: var(--hmi-fs-4);
  font-weight: 650;
}

.info-grid {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  margin: 0 0 0.4rem;
}

.info-grid > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-grid dt {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.info-grid dd {
  margin: 0;
  font-size: var(--hmi-fs-3);
  color: var(--hmi-text);
}

.privacy-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1.5rem;
  padding-block: 0.35rem;
}

.privacy-copy {
  max-inline-size: 62ch;
}

.label {
  font-weight: 600;
  margin-block-end: 0.3rem;
}

.desc {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  line-height: 1.7;
}

.privacy-summary {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-block-start: 0.7rem;
  padding-block-start: 0.6rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.hmi-divider {
  margin-block: 0.7rem;
}

.pwd-form {
  max-inline-size: 380px;
}

.appearance-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.appearance-list li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.7rem;
  font-size: var(--hmi-fs-2);
  padding-block-end: 0.4rem;
  border-block-end: 1px solid var(--hmi-line-soft);
}

.appearance-list span {
  color: var(--hmi-text-3);
}

.appearance-list strong {
  color: var(--hmi-text-2);
  font-weight: 500;
  text-align: end;
}

@media (max-width: 560px) {
  .privacy-row {
    gap: 0.8rem;
  }
}
</style>
