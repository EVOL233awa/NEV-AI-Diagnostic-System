<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ChatDotRound,
  DataAnalysis,
  Files,
  Search,
  Setting,
  Tickets,
  TrendCharts,
  User,
  Van,
} from '@element-plus/icons-vue'
import {
  DIAG_STAGE_LABEL,
  fetchAdminStats,
  fetchDiagOverview,
  fetchHealth,
  fetchSuperadminConfig,
  fmtIso,
  listAppointments,
  listMyVehicles,
  oneLine,
  type AdminStats,
  type AppointmentInfo,
  type AuthUser,
  type DiagOverview,
  type HealthResp,
  type SuperadminConfig,
  type VehicleInfo,
} from '../api/client'
import { ROLE_HOME_LABEL } from '../config/navigation'
import { auth } from '../stores/auth'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import StatCard from '../components/StatCard.vue'
import StatusChip from '../components/StatusChip.vue'

const router = useRouter()
const loading = ref(false)

const vehicles = ref<VehicleInfo[]>([])
const appointments = ref<AppointmentInfo[]>([])
const overview = ref<DiagOverview | null>(null)
const stats = ref<AdminStats | null>(null)
const health = ref<HealthResp | null>(null)
const superConfig = ref<SuperadminConfig | null>(null)

const role = computed<AuthUser['role']>(() => auth.user?.role ?? 'owner')
const title = computed(() => ROLE_HOME_LABEL[role.value])
const defaultVehicle = computed(() => vehicles.value.find((v) => v.is_default) ?? vehicles.value[0] ?? null)

const recentDiags = computed(() => {
  const rows = vehicles.value.flatMap((vehicle) =>
    (vehicle.history ?? []).map((item) => ({
      ...item,
      vehicle: [vehicle.brand, vehicle.model_name].filter(Boolean).join(' ') || vehicle.plate_no,
    })),
  )
  return rows
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    .slice(0, 4)
})

const appointmentCounts = computed(() => {
  const counts = { pending: 0, accepted: 0, completed: 0, cancelled: 0 }
  for (const item of appointments.value) counts[item.status] += 1
  return counts
})

const todayAppointments = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return appointments.value.filter((item) => (item.appointment_time ?? '').slice(0, 10) === today)
})

const nextAppointment = computed(() => {
  const now = new Date().toISOString()
  return appointments.value
    .filter((item) => item.status === 'accepted' && (item.appointment_time ?? '') >= now.slice(0, 16))
    .sort((a, b) => (a.appointment_time ?? '').localeCompare(b.appointment_time ?? ''))[0] ?? null
})

const recentAppointments = computed(() => appointments.value.slice(0, 5))

const quotaState = computed(() => {
  if (!superConfig.value) return '加载中'
  const quota = superConfig.value.quota
  const enabled = [quota.asr_daily_seconds_per_user, quota.search_daily_calls_per_user, quota.global_daily_cny]
    .some((value) => typeof value === 'number' && value > 0)
  return enabled ? '已启用限额' : '未启用限额'
})

const passwordSource = computed(() => {
  const source = superConfig.value?.superadmin.password_source
  if (source === 'env') return { label: '环境变量固定', tone: 'warn' as const }
  if (source === 'config') return { label: '配置文件固定', tone: 'ok' as const }
  if (source === 'generated') return { label: '一次性随机生成', tone: 'danger' as const }
  return { label: '未知', tone: 'neutral' as const }
})

function statusTone(status: string): 'warn' | 'accent' | 'ok' | 'neutral' {
  if (status === 'pending') return 'warn'
  if (status === 'accepted') return 'accent'
  if (status === 'completed') return 'ok'
  return 'neutral'
}

function statusLabel(status: string): string {
  return { pending: '待接单', accepted: '进行中', completed: '已完成', cancelled: '已取消' }[status] ?? status
}

async function load(): Promise<void> {
  loading.value = true
  try {
    if (role.value === 'owner') {
      const [vehicleRows, appointmentRows, healthResp] = await Promise.all([
        listMyVehicles(),
        listAppointments(),
        fetchHealth(),
      ])
      vehicles.value = vehicleRows
      appointments.value = appointmentRows
      health.value = healthResp
    } else if (role.value === 'staff') {
      const [appointmentRows, healthResp] = await Promise.all([listAppointments(), fetchHealth()])
      appointments.value = appointmentRows
      health.value = healthResp
    } else if (role.value === 'admin') {
      const [overviewResp, statsResp, healthResp] = await Promise.all([
        fetchDiagOverview(),
        fetchAdminStats(),
        fetchHealth(),
      ])
      overview.value = overviewResp
      stats.value = statsResp
      health.value = healthResp
    } else if (role.value === 'superadmin') {
      const [configResp, healthResp] = await Promise.all([fetchSuperadminConfig(), fetchHealth()])
      superConfig.value = configResp
      health.value = healthResp
    }
  } catch {
    // 各卡片自行呈现空态；首页不因单个接口失败整体中断
  } finally {
    loading.value = false
  }
}

function go(path: string): void {
  router.push(path)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="title" :subtitle="`${auth.user?.display_name || auth.user?.username}，欢迎回来`">
      <template #actions>
        <el-button v-if="role === 'owner'" type="primary" :icon="ChatDotRound" @click="go('/chat')">
          开始诊断
        </el-button>
        <el-button v-else-if="role === 'staff'" type="primary" :icon="ChatDotRound" @click="go('/chat')">
          打开诊断台
        </el-button>
        <el-button v-else-if="role === 'admin'" type="primary" :icon="DataAnalysis" @click="go('/admin/diagnosis')">
          诊断质控
        </el-button>
        <el-button v-else type="primary" :icon="Setting" @click="go('/superadmin')">
          系统配置
        </el-button>
      </template>
    </PageHeader>

    <!-- 车主 -->
    <template v-if="role === 'owner'">
      <section v-if="defaultVehicle" class="vehicle-hero hmi-card">
        <div class="hero-main">
          <span class="eyebrow">当前车辆</span>
          <h2>{{ defaultVehicle.brand }} {{ defaultVehicle.model_name }}</h2>
          <p class="hero-meta">
            <span>{{ defaultVehicle.plate_no || '未上车牌' }}</span>
            <span>里程 {{ defaultVehicle.mileage != null ? `${defaultVehicle.mileage.toLocaleString()} km` : '未记录' }}</span>
            <span v-if="defaultVehicle.model_year">{{ defaultVehicle.model_year }} 年款</span>
          </p>
        </div>
        <div class="hero-side">
          <template v-if="recentDiags.length">
            <span class="eyebrow">最近诊断</span>
            <div class="hero-diag">
              <SeverityBadge :severity="recentDiags[0].severity" />
              <span class="diag-text">{{ oneLine(recentDiags[0].summary, 42) }}</span>
            </div>
            <span class="hero-time">{{ fmtIso(recentDiags[0].created_at) }}</span>
          </template>
          <template v-else>
            <span class="eyebrow">最近诊断</span>
            <span class="hero-time">还没有诊断记录</span>
          </template>
        </div>
      </section>
      <EmptyState
        v-else-if="!loading"
        title="还没有车辆档案"
        description="添加车辆后可获得更贴合车型的诊断与历史记录。"
        compact
      >
        <el-button type="primary" size="small" @click="go('/my-vehicles')">添加车辆</el-button>
      </EmptyState>

      <section class="quick-grid">
        <button type="button" class="quick" @click="go('/chat')">
          <el-icon aria-hidden="true"><ChatDotRound /></el-icon>
          <strong>AI 诊断</strong><span>描述症状，多轮问诊</span>
        </button>
        <button type="button" class="quick" @click="go('/my-vehicles')">
          <el-icon aria-hidden="true"><Van /></el-icon>
          <strong>车辆档案</strong><span>里程与诊断历史</span>
        </button>
        <button type="button" class="quick" @click="go('/appointments')">
          <el-icon aria-hidden="true"><Tickets /></el-icon>
          <strong>我的预约</strong><span>{{ appointmentCounts.pending + appointmentCounts.accepted }} 个进行中</span>
        </button>
        <button type="button" class="quick" @click="go('/settings')">
          <el-icon aria-hidden="true"><Setting /></el-icon>
          <strong>隐私设置</strong><span>{{ auth.user?.privacy_share_dialog ? '工作人员可见对话' : '仅诊断摘要' }}</span>
        </button>
      </section>

      <div class="two-col">
        <section class="panel hmi-card">
          <div class="panel-head">
            <h3>最近诊断</h3>
            <el-button text size="small" @click="go('/my-vehicles')">全部</el-button>
          </div>
          <EmptyState v-if="!recentDiags.length && !loading" title="暂无诊断记录" compact />
          <ul v-else class="diag-list">
            <li v-for="(item, index) in recentDiags" :key="`${item.session_id}-${index}`">
              <div class="diag-head">
                <SeverityBadge :severity="item.severity" />
                <span v-if="item.stage" class="stage">{{ DIAG_STAGE_LABEL[item.stage] }}</span>
                <span class="time">{{ fmtIso(item.created_at) }}</span>
              </div>
              <p class="diag-summary">{{ oneLine(item.summary, 60) }}</p>
              <span class="diag-vehicle">{{ item.vehicle }}</span>
            </li>
          </ul>
        </section>

        <section class="panel hmi-card">
          <div class="panel-head"><h3>预约与隐私</h3></div>
          <div class="appointment-brief">
            <span class="brief-label">下一个预约</span>
            <template v-if="nextAppointment">
              <strong>{{ fmtIso(nextAppointment.appointment_time) }}</strong>
              <span class="hmi-sub">{{ nextAppointment.vehicle || '未关联车辆' }}</span>
            </template>
            <span v-else class="hmi-sub">暂无已确认的预约</span>
          </div>
          <hr class="hmi-divider" />
          <ul class="privacy-list">
            <li>
              <StatusChip :label="auth.user?.privacy_share_dialog ? '工作人员可见对话' : '工作人员仅看摘要'" :tone="auth.user?.privacy_share_dialog ? 'accent' : 'neutral'" />
              <span>到店与质控时可查看的对话范围</span>
            </li>
          </ul>
          <el-button text type="primary" size="small" @click="go('/settings')">调整隐私设置</el-button>
        </section>
      </div>
    </template>

    <!-- 店员 -->
    <template v-else-if="role === 'staff'">
      <div class="hmi-grid hmi-grid--stats">
        <StatCard label="待接单" :value="appointmentCounts.pending" tone="warn" hint="需要尽快确认" />
        <StatCard label="进行中" :value="appointmentCounts.accepted" tone="accent" hint="已接单待到店" />
        <StatCard label="今日预约" :value="todayAppointments.length" tone="info" hint="按预约时间统计" />
        <StatCard label="已完成" :value="appointmentCounts.completed" tone="ok" hint="累计完成工单" />
      </div>

      <section class="quick-grid">
        <button type="button" class="quick" @click="go('/chat')">
          <el-icon aria-hidden="true"><ChatDotRound /></el-icon>
          <strong>诊断台</strong><span>与车主同屏问诊</span>
        </button>
        <button type="button" class="quick" @click="go('/staff/dtc')">
          <el-icon aria-hidden="true"><Search /></el-icon>
          <strong>故障码速查</strong><span>码表 + 知识库 + 案例</span>
        </button>
        <button type="button" class="quick" @click="go('/staff/vehicles')">
          <el-icon aria-hidden="true"><Van /></el-icon>
          <strong>车辆档案</strong><span>车牌 / VIN 检索</span>
        </button>
        <button type="button" class="quick" @click="go('/staff/appointments')">
          <el-icon aria-hidden="true"><Tickets /></el-icon>
          <strong>预约工单</strong><span>筛选、接单、打印</span>
        </button>
      </section>

      <section class="panel hmi-card">
        <div class="panel-head">
          <h3>最近工单</h3>
          <el-button text size="small" @click="go('/staff/appointments')">查看全部</el-button>
        </div>
        <EmptyState v-if="!recentAppointments.length && !loading" title="暂无预约工单" compact />
        <ul v-else class="order-list">
          <li v-for="item in recentAppointments" :key="item.id" class="order-row">
            <div class="order-main">
              <span class="order-owner">{{ item.owner_name || '车主' }}</span>
              <span class="order-vehicle">{{ item.vehicle || '未关联车辆' }}</span>
            </div>
            <span class="order-time hmi-mono">{{ fmtIso(item.appointment_time) }}</span>
            <StatusChip :label="statusLabel(item.status)" :tone="statusTone(item.status)" dot />
            <el-button size="small" text type="primary" @click="go('/staff/appointments')">处理</el-button>
          </li>
        </ul>
      </section>
    </template>

    <!-- 管理员 -->
    <template v-else-if="role === 'admin'">
      <div class="hmi-grid hmi-grid--stats">
        <StatCard label="今日会话" :value="overview?.today_sessions ?? 0" tone="accent" hint="今日新建诊断" />
        <StatCard label="结论覆盖率" :value="overview ? Math.round(overview.conclusion_rate * 100) : 0" suffix="%" tone="ok" hint="已出结构化结论" />
        <StatCard label="假设关联率" :value="overview ? Math.round(overview.evidence_link_rate * 100) : 0" suffix="%" tone="info" hint="假设带证据编号" />
        <StatCard label="今日模型调用" :value="stats?.usage.today.calls ?? 0" tone="warn" hint="含压缩/标题/抽取" />
      </div>

      <section class="quick-grid">
        <button type="button" class="quick" @click="go('/admin/diagnosis')">
          <el-icon aria-hidden="true"><DataAnalysis /></el-icon>
          <strong>诊断质控</strong><span>阶段、证据链、受控原文</span>
        </button>
        <button type="button" class="quick" @click="go('/admin/kb')">
          <el-icon aria-hidden="true"><Files /></el-icon>
          <strong>知识库</strong><span>上传、预览、检索测试</span>
        </button>
        <button type="button" class="quick" @click="go('/admin/users')">
          <el-icon aria-hidden="true"><User /></el-icon>
          <strong>成员管理</strong><span>角色、停用、重置密码</span>
        </button>
        <button type="button" class="quick" @click="go('/admin/stats')">
          <el-icon aria-hidden="true"><TrendCharts /></el-icon>
          <strong>统计看板</strong><span>趋势、分布、消耗</span>
        </button>
      </section>

      <div class="two-col">
        <section class="panel hmi-card">
          <div class="panel-head"><h3>系统状态</h3><StatusChip :label="health?.ok ? '运行正常' : '异常'" :tone="health?.ok ? 'ok' : 'danger'" dot /></div>
          <ul class="status-list">
            <li><span>网页搜索</span><strong>{{ health?.providers.web_search ? '已启用' : '未启用' }}</strong></li>
            <li><span>语音识别</span><strong>{{ health?.providers.asr_configured ? '已配置' : '未配置' }}</strong></li>
            <li><span>今日 Token</span><strong class="hmi-mono">{{ (stats?.usage.today.tokens_in ?? 0) + (stats?.usage.today.tokens_out ?? 0) }}</strong></li>
          </ul>
        </section>
        <section class="panel hmi-card">
          <div class="panel-head"><h3>质控概况</h3><el-button text size="small" @click="go('/admin/diagnosis')">进入质控</el-button></div>
          <ul class="status-list">
            <li><span>进行中会话</span><strong>{{ overview?.active_sessions ?? 0 }}</strong></li>
            <li><span>已出结论</span><strong>{{ overview?.conclusion_sessions ?? 0 }}</strong></li>
            <li><span>证据条目</span><strong>{{ overview?.evidence_total ?? 0 }}</strong></li>
            <li><span>假设总数</span><strong>{{ overview?.hypotheses_total ?? 0 }}</strong></li>
          </ul>
        </section>
      </div>
    </template>

    <!-- 超级管理员 -->
    <template v-else>
      <el-alert
        v-if="passwordSource.tone === 'danger' || passwordSource.tone === 'warn'"
        :type="passwordSource.tone === 'danger' ? 'error' : 'warning'"
        :closable="false"
        show-icon
        :title="`超级管理员密码来源：${passwordSource.label}`"
        :description="passwordSource.tone === 'danger'
          ? '当前为首次启动生成的一次性密码，重启后不会保留。请在系统参数页修改为固定密码，或部署时用环境变量固定。'
          : '环境变量优先级最高，面板内修改在重启后会被环境变量覆盖。'"
      />

      <div class="hmi-grid hmi-grid--stats">
        <StatCard label="主模型" :value="superConfig?.providers.main.model || '未配置'" tone="accent" :hint="superConfig?.providers.main.base_url || ''" />
        <StatCard label="嵌入模型" :value="superConfig?.providers.embedding.model || '未配置'" tone="info" hint="知识库检索向量" />
        <StatCard label="重排" :value="superConfig?.providers.rerank.enabled ? '已启用' : '未启用'" :tone="superConfig?.providers.rerank.enabled ? 'ok' : 'default'" :hint="superConfig?.providers.rerank.model || ''" />
        <StatCard label="搜索 / ASR" :value="`${superConfig?.search.provider ?? '—'} / ${superConfig?.asr.provider ?? '—'}`" tone="warn" :hint="quotaState" />
      </div>

      <section class="quick-grid">
        <button type="button" class="quick" @click="go('/superadmin')">
          <el-icon aria-hidden="true"><Setting /></el-icon>
          <strong>三模型与密钥</strong><span>主模型 / 嵌入 / 重排</span>
        </button>
        <button type="button" class="quick" @click="go('/superadmin')">
          <el-icon aria-hidden="true"><Search /></el-icon>
          <strong>搜索与语音</strong><span>provider、降级与连通性</span>
        </button>
        <button type="button" class="quick" @click="go('/superadmin')">
          <el-icon aria-hidden="true"><TrendCharts /></el-icon>
          <strong>限额与预算</strong><span>{{ quotaState }}</span>
        </button>
        <button type="button" class="quick" @click="go('/superadmin')">
          <el-icon aria-hidden="true"><User /></el-icon>
          <strong>安全</strong><span>{{ passwordSource.label }}</span>
        </button>
      </section>

      <section class="panel hmi-card">
        <div class="panel-head"><h3>运行摘要</h3><StatusChip :label="health?.ok ? '服务正常' : '服务异常'" :tone="health?.ok ? 'ok' : 'danger'" dot /></div>
        <ul class="status-list">
          <li><span>版本</span><strong class="hmi-mono">{{ health?.version || superConfig?.server.version || '—' }}</strong></li>
          <li><span>监听地址</span><strong class="hmi-mono">{{ superConfig ? `${superConfig.server.host}:${superConfig.server.port}` : '—' }}</strong></li>
          <li><span>管理员密码</span><strong>{{ passwordSource.label }}</strong></li>
          <li><span>重启后生效项</span><strong>{{ superConfig?.server.restart_required_keys.length ? superConfig.server.restart_required_keys.join('、') : '无' }}</strong></li>
        </ul>
        <el-button type="primary" size="small" @click="go('/superadmin')">打开系统参数</el-button>
      </section>
    </template>
  </div>
</template>

<style scoped>
.vehicle-hero {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 1.1rem 1.2rem;
  background:
    radial-gradient(ellipse 50% 120% at 8% 0%, rgba(53, 214, 194, 0.12), transparent 60%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.025), transparent 42%),
    var(--hmi-surface);
}

.eyebrow {
  display: block;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-block-end: 0.3rem;
}

.hero-main h2 {
  font-size: clamp(1.2rem, 2.2vw, 1.55rem);
  font-weight: 650;
}

.hero-meta {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  margin-block-start: 0.45rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.hero-side {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-inline-size: 190px;
  padding-inline-start: 1rem;
  border-inline-start: 1px solid var(--hmi-line-soft);
}

.hero-diag {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}

.diag-text {
  font-size: var(--hmi-fs-3);
  color: var(--hmi-text-2);
}

.hero-time {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.6rem;
}

.quick {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  padding: 0.8rem 0.9rem;
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius-lg);
  background: var(--hmi-surface);
  color: var(--hmi-text-2);
  text-align: start;
  cursor: pointer;
  transition: border-color var(--hmi-dur-1) var(--hmi-ease), background var(--hmi-dur-1) var(--hmi-ease);
}

.quick:hover {
  border-color: var(--hmi-accent-line);
  background: var(--hmi-surface-2);
}

.quick .el-icon {
  color: var(--hmi-accent);
  font-size: 18px;
  margin-block-end: 0.25rem;
}

.quick strong {
  font-size: var(--hmi-fs-4);
  color: var(--hmi-text);
}

.quick span {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 0.75rem;
}

.panel {
  padding: 0.9rem 1rem;
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

.diag-list,
.order-list,
.status-list,
.privacy-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.diag-list li {
  padding: 0.55rem 0;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.diag-list li:first-child {
  border-block-start: 0;
  padding-block-start: 0;
}

.diag-head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.stage {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.time {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  font-family: var(--hmi-font-mono);
}

.diag-summary {
  margin-block-start: 0.25rem;
  font-size: var(--hmi-fs-3);
  color: var(--hmi-text-2);
}

.diag-vehicle {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.appointment-brief {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin-block-end: 0.6rem;
}

.brief-label {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.appointment-brief strong {
  font-family: var(--hmi-font-mono);
  font-size: var(--hmi-fs-4);
}

.privacy-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-block: 0.6rem;
}

.privacy-list li {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-3);
}

.order-row {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.5rem 0;
  border-block-start: 1px solid var(--hmi-line-soft);
  flex-wrap: wrap;
}

.order-row:first-child {
  border-block-start: 0;
}

.order-main {
  display: flex;
  flex-direction: column;
  min-inline-size: 140px;
}

.order-owner {
  font-size: var(--hmi-fs-3);
  font-weight: 600;
}

.order-vehicle {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.order-time {
  margin-inline-start: auto;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin-block-end: 0.6rem;
}

.status-list li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.7rem;
  font-size: var(--hmi-fs-2);
  padding-block-end: 0.4rem;
  border-block-end: 1px solid var(--hmi-line-soft);
}

.status-list span {
  color: var(--hmi-text-3);
}

.status-list strong {
  color: var(--hmi-text-2);
  font-weight: 550;
  text-align: end;
  overflow-wrap: anywhere;
}

@media (max-width: 860px) {
  .two-col {
    grid-template-columns: 1fr;
  }

  .hero-side {
    inline-size: 100%;
    border-inline-start: 0;
    border-block-start: 1px solid var(--hmi-line-soft);
    padding-inline-start: 0;
    padding-block-start: 0.7rem;
  }
}

@media (max-width: 520px) {
  .quick-grid {
    grid-template-columns: 1fr 1fr;
  }

  .hero-meta {
    gap: 0.5rem 0.8rem;
  }
}
</style>
