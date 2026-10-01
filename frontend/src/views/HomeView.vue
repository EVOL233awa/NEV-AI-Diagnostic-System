<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { SwitchButton } from '@element-plus/icons-vue'
import { ROLE_LABELS, auth, logout } from '../stores/auth'

const router = useRouter()

/** 三端功能路线：入口严格按角色隔离——只显示本端已上线的功能，
 * 未上线/跨端入口一律不显示（2026-09-26 用户裁定） */
interface NavItem {
  title: string
  to: string
}

const ENDPOINTS: Record<string, { label: string; desc: string; items: NavItem[] }> = {
  owner: {
    label: '车主端',
    desc: 'AI 助手 · 车辆档案 · 预约',
    items: [
      { title: 'AI 助手对话', to: '/chat' },
      { title: '我的车辆', to: '/my-vehicles' },
      { title: '我的预约', to: '/appointments' },
      { title: '设置', to: '/settings' },
    ],
  },
  staff: {
    label: '店员端',
    desc: '工单队列 · 诊断台 · 档案检索',
    items: [
      { title: '预约工单', to: '/staff/appointments' },
      { title: '诊断台', to: '/chat' },
      { title: '车辆档案检索', to: '/staff/vehicles' },
      { title: '案例库', to: '/cases' },
      { title: '设置', to: '/settings' },
    ],
  },
  admin: {
    label: '管理端',
    desc: '成员 · 统计 · 知识库 · 审计',
    items: [
      { title: '统计看板', to: '/admin/stats' },
      { title: '成员与角色管理', to: '/admin/users' },
      { title: '知识库管理', to: '/admin/kb' },
      { title: '审计日志', to: '/admin/audit' },
    ],
  },
  superadmin: {
    label: '调试后台',
    desc: '供应商配置 · Agent 参数（仅部署者）',
    items: [
      { title: '系统参数配置', to: '/superadmin' },
      { title: '诊断台（试跑）', to: '/chat' },
    ],
  },
}

const visibleEndpoints = computed(() => {
  const role = auth.user?.role
  if (!role || !ENDPOINTS[role]) return []
  return [ENDPOINTS[role]]
})

function onNav(item: NavItem): void {
  router.push(item.to)
}

function onLogout(): void {
  logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="home-page">
    <header class="topbar">
      <div class="brand">
        <h1>新能源汽车 AI 智能诊断系统 <span class="ver">2.0</span></h1>
        <p class="subtitle">阶段 4 · 商用层闭环已上线（预约工单 / 成员管理 / 统计审计）</p>
      </div>
      <div class="user-area">
        <el-tag
          :type="auth.user?.role === 'superadmin' ? 'danger' : auth.user?.role === 'admin' ? 'warning' : 'success'"
          effect="dark"
          size="small"
        >
          {{ auth.user ? ROLE_LABELS[auth.user.role] : '' }}
        </el-tag>
        <span class="username">{{ auth.user?.display_name }}</span>
        <el-button :icon="SwitchButton" text @click="onLogout">退出</el-button>
      </div>
    </header>

    <main class="content">
      <el-alert
        type="success"
        :closable="false"
        show-icon
        title="阶段 4 完成：预约闭环 + 成员与角色管理 + 车辆档案双通道 + 统计/审计"
        description="车主一键预约 → 店员接单改约 → 回填结果 → 沉淀案例 → 打印报告；诊断摘要卡始终对店员可见，对话原文按车主隐私开关过滤；管理端统计看板与审计日志上线。"
      />

      <section v-for="ep in visibleEndpoints" :key="ep.label" class="endpoint">
        <div class="endpoint-head">
          <h2>{{ ep.label }}</h2>
          <span class="endpoint-desc">{{ ep.desc }}</span>
        </div>
        <div class="nav-grid">
          <div
            v-for="item in ep.items"
            :key="item.title"
            class="nav-card ready"
            @click="onNav(item)"
          >
            <span class="nav-title">{{ item.title }}</span>
            <el-tag size="small" type="success" effect="dark">进入</el-tag>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.home-page {
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.brand h1 {
  font-size: 1.1rem;
  margin: 0;
}

.ver {
  color: var(--accent);
}

.subtitle {
  color: var(--muted);
  font-size: 0.72rem;
  margin: 0.25rem 0 0;
}

.user-area {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.username {
  font-size: 0.85rem;
}

.content {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.endpoint-head {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 0.6rem;
}

.endpoint-head h2 {
  font-size: 0.95rem;
  margin: 0;
}

.endpoint-desc {
  font-size: 0.72rem;
  color: var(--muted);
}

.nav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.6rem;
}

.nav-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.7rem 0.9rem;
  opacity: 0.75;
}

.nav-card.ready {
  opacity: 1;
  cursor: pointer;
  border-color: var(--accent-dim);
}

.nav-card.ready:hover {
  border-color: var(--accent);
}

.nav-title {
  font-size: 0.82rem;
}
</style>
