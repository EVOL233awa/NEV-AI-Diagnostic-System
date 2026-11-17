<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Menu, Operation, Promotion, Search } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import VoiceButton from '../components/VoiceButton.vue'
import SeverityBadge from '../components/SeverityBadge.vue'
import Sheet from '../components/Sheet.vue'
import StatusChip from '../components/StatusChip.vue'
import ContextPanel from '../components/chat/ContextPanel.vue'
import type { StageStep } from '../components/ui-types'
import { auth } from '../stores/auth'
import { createAppointment, fetchHealth, localIso } from '../api/client'
import {
  type DiagHypothesis,
  type DiagResult,
  type HistoryMessage,
  type PendingQuestion,
  type SessionInfo,
  type SseEvent,
  createSession,
  listMessages,
  listSessions,
  streamChat,
} from '../api/chat'

// 模型输出是 markdown（加粗/列表/引用标注）；html:false 防注入，breaks 让单换行成段。
// 禁用图片：网页检索结果可能被提示注入诱导输出外链图片，浏览器会自动请求造成数据外带。
const md = new MarkdownIt({ html: false, breaks: true, linkify: false }).disable('image')

/** diag_final 到达后把显示内容里的 ```json fence 剥掉，与后端落库口径一致 */
function stripFence(text: string): string {
  return text.replace(/```json[\s\S]*?```/g, '').trim()
}

/** 车主端不暴露检索来源：剥掉正文里的 [1] / [网2] 式引用标注（历史会话遗留也清理） */
function stripCitations(text: string): string {
  return text.replace(/\s*\[(?:网)?\d+\]/g, '')
}

function renderMd(text: string): string {
  return md.render(stripCitations(text))
}

/** 与后端约定的「无法判断」兜底作答值（前端自动附加该选项） */
const UNCLEAR_VALUE = '不知道/不清楚'
const UNCLEAR_LABEL = '不知道 / 不清楚'

/** 模型可能在选项里自带兜底项（记不清/不确定/没试过…），与固定兜底选项语义重复，渲染前剥离 */
const UNCLEAR_OPT_PAT = /不知道|不清楚|记不清|不确定|没试过|还没试|不了解/

function filterOptions(q: PendingQuestion): string[] {
  return (q.options ?? []).filter((o) => !UNCLEAR_OPT_PAT.test(o))
}

/** 历史行可能存着模型未守契约的原始形状（hypotheses 为字符串数组），渲染前兜底取标题 */
function hypTitle(h: DiagHypothesis | string): string {
  return typeof h === 'string' ? h : (h?.title ?? '')
}

interface ToolTrace {
  name: string
  args: string
  result: string | null
}

/** 一轮对话的渲染状态：气泡内容 + 工具过程 + 诊断卡片 + ask_user 卡片 */
interface Turn {
  role: 'user' | 'assistant'
  content: string
  tools: ToolTrace[]
  diag: DiagResult | null
  questions: PendingQuestion[] | null
  answers: Record<string, string>
  streaming: boolean
}

/** 工具 → 车主可懂的动作语义（时间线文案 = 状态前缀 + 动作 + 参数） */
const TOOL_ACTIONS: Record<string, string> = {
  kb_search: '检索维修知识库',
  dtc_lookup: '查询故障码定义',
  web_search: '联网核实资料',
  get_vehicle_profile: '读取车辆档案',
  update_case_notes: '记录诊断进展',
}

/** 顶栏角色标签：对话页三端共用，按登录角色显示所在端 */
const CHAT_TAG: Record<string, string> = {
  owner: '车主端',
  staff: '店员 · 诊断台',
  admin: '管理端',
  superadmin: '调试',
}

const SUGGESTIONS = [
  '仪表盘提示动力电池故障，还能继续开吗？',
  '冬天续航掉得特别快，是电池坏了吗？',
  '充电到 80% 就充不进去了，什么原因？',
]

const sessions = ref<SessionInfo[]>([])
const activeId = ref<number | null>(null)
const turns = ref<Turn[]>([])
const input = ref('')
const sending = ref(false)
const drawerOpen = ref(false)
const contextOpen = ref(false)
const sessionQuery = ref('')
const listEl = ref<HTMLElement | null>(null)
const inputRef = ref<{ focus: () => void } | null>(null)
// 语音 provider 决定解码失败时的兜底：OpenAI 兼容接口可直传原始格式
const asrProvider = ref<'deepseek' | 'openai'>('deepseek')

const activeSession = computed(() => sessions.value.find((s) => s.id === activeId.value) ?? null)
const filteredSessions = computed(() => {
  const q = sessionQuery.value.trim()
  return q ? sessions.value.filter((s) => s.title.includes(q)) : sessions.value
})
const hasPending = computed(() => turns.value.some((t) => t.questions && t.questions.length > 0))
const composerDisabled = computed(() => sending.value || hasPending.value)
const placeholder = computed(() =>
  hasPending.value ? '请先回答上方的补充信息问题' : '描述车辆问题，例如：低速行驶时提示电池故障',
)
const latestDiag = computed(() => {
  for (let i = turns.value.length - 1; i >= 0; i -= 1) {
    if (turns.value[i].diag) return turns.value[i].diag
  }
  return null
})
const stageSteps = computed<StageStep[]>(() => {
  const steps: StageStep[] = []
  if (turns.value.some((t) => t.role === 'user')) steps.push({ stage: 'intake' })
  if (turns.value.some((t) => t.tools.length)) steps.push({ stage: 'verification' })
  if (latestDiag.value) steps.push({ stage: 'conclusion' })
  return steps
})
const contextTools = computed(() =>
  turns.value
    .flatMap((turn) =>
      turn.tools.map((tool) => ({
        name: tool.name,
        brief: toolBrief(tool.name, tool.args),
        done: tool.result !== null,
      })),
    )
    .slice(-10),
)
const role = computed(() => auth.user?.role ?? 'owner')

function toolBrief(name: string, argsJson: string): string {
  const action = TOOL_ACTIONS[name] ?? name
  try {
    const args = JSON.parse(argsJson) as Record<string, unknown>
    for (const key of ['code', 'query', 'keyword']) {
      const v = args[key]
      if (typeof v === 'string' && v) return `${action}「${v}」`
    }
  } catch {
    // 参数不是 JSON 时只显示动作名
  }
  return action
}

/** 诊断卡置信信号：把本轮查证动作聚合为一行可读声明（不带来源细节，守住车主端边界） */
function evidenceLine(turn: Turn): string {
  const done = (name: string) => turn.tools.some((t) => t.name === name && t.result !== null)
  const kbCount = turn.tools.filter(
    (t) => (t.name === 'kb_search' || t.name === 'dtc_lookup') && t.result !== null,
  ).length
  const parts: string[] = []
  if (kbCount > 0) parts.push(`已查证知识库 ${kbCount} 项`)
  if (done('get_vehicle_profile')) parts.push('已结合车辆档案')
  if (done('web_search')) parts.push('已联网核实')
  return parts.join(' · ')
}

async function scrollBottom(): Promise<void> {
  await nextTick()
  listEl.value?.scrollTo({ top: listEl.value.scrollHeight })
}

function applyEvent(turn: Turn, ev: SseEvent): void {
  if (ev.event === 'delta') {
    turn.content += String(ev.data.content ?? '')
  } else if (ev.event === 'tool_start') {
    turn.tools.push({
      name: String(ev.data.name ?? ''),
      args: String(ev.data.arguments ?? ''),
      result: null,
    })
  } else if (ev.event === 'tool_result') {
    const last = turn.tools[turn.tools.length - 1]
    if (last) last.result = String(ev.data.result ?? '')
  } else if (ev.event === 'pending_question') {
    const qs = ev.data.questions
    if (Array.isArray(qs) && qs.length > 0) turn.questions = qs as PendingQuestion[]
  } else if (ev.event === 'diag_final') {
    turn.content = stripFence(turn.content)
    turn.diag = ev.data as unknown as DiagResult
  } else if (ev.event === 'error') {
    // 错误持久化到气泡（toast 会消失，导致看不到失败原因）
    turn.content = `${turn.content}\n\n⚠️ ${String(ev.data.message ?? '服务错误')}`.trim()
    ElMessage.error(String(ev.data.message ?? '服务错误'))
  }}

async function runStream(path: string, body: Record<string, unknown>): Promise<void> {
  const turn = reactive<Turn>({
    role: 'assistant',
    content: '',
    tools: [],
    diag: null,
    questions: null,
    answers: {},
    streaming: true,
  })
  turns.value.push(turn)
  sending.value = true
  try {
    await streamChat(path, body, (ev) => {
      applyEvent(turn, ev)
      // delta 不逐字显示（见 runStream 状态行方案），只在工具/结果事件时滚动
      if (ev.event === 'tool_start' || ev.event === 'tool_result' || ev.event === 'diag_final') {
        void scrollBottom()
      }
    })
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '网络错误，请稍后重试')
  } finally {
    turn.streaming = false
    sending.value = false
    void refreshSessions()
    void scrollBottom()
  }
}

async function refreshSessions(): Promise<void> {
  try {
    sessions.value = await listSessions()
  } catch {
    // 列表刷新失败不打断对话
  }
}

async function sendContent(content: string): Promise<void> {
  if (activeId.value === null || composerDisabled.value) return
  turns.value.push(
    reactive<Turn>({
      role: 'user',
      content,
      tools: [],
      diag: null,
      questions: null,
      answers: {},
      streaming: false,
    }),
  )
  void scrollBottom()
  await runStream(`/api/chat/sessions/${activeId.value}/send`, { content })
}

async function onSend(): Promise<void> {
  const content = input.value.trim()
  if (!content || composerDisabled.value) return
  // 新账号/会话列表为空时输入框仍可用：自动建会话后再发，不能清空输入后静默 return
  if (activeId.value === null) {
    sending.value = true
    try {
      const s = await createSession(content.slice(0, 24))
      await refreshSessions()
      activeId.value = s.id
      turns.value = []
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '创建会话失败')
      return
    } finally {
      sending.value = false
    }
  }
  input.value = ''
  await sendContent(content)
}

/** 语音转写结果追加到输入框（保留已有文字），聚焦但不自动发送。 */
function onVoiceText(text: string): void {
  const existing = input.value.trimEnd()
  input.value = existing ? `${existing} ${text}` : text
  void nextTick(() => inputRef.value?.focus())
}

function onVoiceError(message: string): void {
  ElMessage.error(message)
}

async function quickAsk(question: string): Promise<void> {
  if (sending.value) return
  try {
    const s = await createSession(question.slice(0, 24))
    await refreshSessions()
    activeId.value = s.id
    turns.value = []
    await sendContent(question)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '创建会话失败')
  }
}

async function onNewSession(): Promise<void> {
  if (sending.value) return
  try {
    const s = await createSession('新诊断会话')
    await refreshSessions()
    activeId.value = s.id
    turns.value = []
    drawerOpen.value = false
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '创建会话失败')
  }
}

async function openSession(id: number): Promise<void> {
  if (sending.value) return
  activeId.value = id
  drawerOpen.value = false
  turns.value = []
  try {
    const { messages, pending_questions } = await listMessages(id)
    for (const m of messages as HistoryMessage[]) {
      turns.value.push(
        reactive<Turn>({
          role: m.role,
          content: m.content,
          // 历史工具轨迹由后端 tool_calls+tool 结果行拼装回传，重开会话查证时间线不丢
          tools: (m.tools ?? []).map((t) => ({ name: t.name, args: t.arguments, result: t.result })),
          diag: m.diag,
          questions: null,
          answers: {},
          streaming: false,
        }),
      )
    }
    if (Array.isArray(pending_questions) && pending_questions.length > 0) {
      // 离线续答：挂起的 ask_user 卡片随会话恢复
      turns.value.push(
        reactive<Turn>({
          role: 'assistant',
          content: '',
          tools: [],
          diag: null,
          questions: pending_questions,
          answers: {},
          streaming: false,
        }),
      )
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载会话失败')
  }
  void scrollBottom()
}

function toggleOpt(turn: Turn, qid: string, opt: string): void {
  if (turn.answers[qid] === opt) {
    delete turn.answers[qid]
  } else {
    turn.answers[qid] = opt
  }
}

async function submitAnswers(turn: Turn): Promise<void> {
  const questions = turn.questions
  if (!questions || activeId.value === null) return
  const pairs = questions
    .map((q) => ({ id: q.id, value: (turn.answers[q.id] ?? '').trim() }))
    .filter((p) => p.value !== '')
  if (pairs.length === 0) {
    ElMessage.warning('请先点选或填写至少一项回答')
    return
  }
  turn.questions = null
  const echo = questions
    .filter((q) => pairs.some((p) => p.id === q.id))
    .map((q) => {
      const p = pairs.find((x) => x.id === q.id)
      return `【补充】${q.question}：${p ? p.value : ''}`
    })
    .join('\n')
  turns.value.push(
    reactive<Turn>({
      role: 'user',
      content: echo,
      tools: [],
      diag: null,
      questions: null,
      answers: {},
      streaming: false,
    }),
  )
  void scrollBottom()
  await runStream(`/api/chat/sessions/${activeId.value}/answers`, { answers: pairs })
}

/** 一键预约：诊断结论出现后，携带当前会话生成预约工单（摘要卡后端自动快照） */
const bookDialogVisible = ref(false)
const bookTime = ref<Date | null>(null)
const bookNote = ref('')
const booking = ref(false)

function onBook(): void {
  if (activeId.value === null) {
    ElMessage.warning('请先保存诊断会话')
    return
  }
  bookTime.value = null
  bookNote.value = ''
  bookDialogVisible.value = true
}

async function submitBooking(): Promise<void> {
  if (!bookTime.value) {
    ElMessage.warning('请选择期望到店时间')
    return
  }
  booking.value = true
  try {
    await createAppointment({
      session_id: activeId.value ?? undefined,
      appointment_time: localIso(bookTime.value),
      note: bookNote.value,
    })
    bookDialogVisible.value = false
    ElMessage.success('预约已提交，可在「我的预约」查看进度')
  } catch (e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response
    ElMessage.error(resp?.data?.detail ?? '预约失败，请重试')
  } finally {
    booking.value = false
  }
}

onMounted(async () => {
  void fetchHealth()
    .then((health) => {
      if (health.providers.asr_provider === 'openai') asrProvider.value = 'openai'
    })
    .catch(() => undefined)
  await refreshSessions()
  if (sessions.value.length > 0) {
    await openSession(sessions.value[0].id)
  }
})
</script>

<template>
  <div class="chat-page">
    <aside class="session-pane">
      <div class="pane-head">
        <div>
          <h2>诊断会话</h2>
          <span class="hmi-sub">{{ sessions.length }} 个</span>
        </div>
        <el-button type="primary" size="small" @click="onNewSession">＋ 新话题</el-button>
      </div>
      <el-input v-model="sessionQuery" class="session-search" placeholder="搜索会话" clearable :prefix-icon="Search" size="small" aria-label="搜索诊断会话" />
      <div class="session-list">
        <button
          v-for="s in filteredSessions"
          :key="s.id"
          type="button"
          class="session-item"
          :class="{ active: s.id === activeId }"
          :aria-current="s.id === activeId ? 'true' : undefined"
          @click="openSession(s.id)"
        >
          <span class="session-dot" :class="{ pending: s.has_pending }" aria-hidden="true"></span>
          <span class="session-title">{{ s.title }}</span>
          <span v-if="s.has_pending" class="pending-tag">待补充</span>
        </button>
        <p v-if="filteredSessions.length === 0" class="empty-hint">
          {{ sessionQuery ? '没有匹配的会话' : '还没有会话，点「新话题」开始' }}
        </p>
      </div>
      <div class="pane-foot">
        <span class="hmi-sub">会话自动按默认车辆归档</span>
      </div>
    </aside>

    <main class="chat-main">
      <header class="chat-head">
        <el-button class="mobile-only" :icon="Menu" text aria-label="打开会话列表" @click="drawerOpen = true" />
        <div class="title-block">
          <strong>{{ activeSession?.title ?? 'AI 诊断助手' }}</strong>
          <span class="hmi-sub">{{ CHAT_TAG[role] }}</span>
        </div>
        <div class="head-meta">
          <StatusChip
            v-if="activeSession?.vehicle"
            :label="activeSession.vehicle.plate_no || activeSession.vehicle.model_name || '已关联车辆'"
            tone="info"
          />
          <StatusChip v-if="hasPending" label="待补充信息" tone="warn" dot />
          <StatusChip v-if="role === 'admin' && latestDiag" label="已出结论" tone="ok" dot />
        </div>
        <el-button class="mobile-only" :icon="Operation" text aria-label="打开上下文" @click="contextOpen = true" />
      </header>

      <div ref="listEl" class="msg-list">
        <div v-if="turns.length === 0" class="hero">
          <span class="hero-mark" aria-hidden="true"><el-icon :size="26"><ChatDotRound /></el-icon></span>
          <h2>先说症状，再一起查证</h2>
          <p>我会先检索知识库、故障码与车辆档案，证据不足时向你提问；结论会标注严重度与到店确认项。</p>
          <div class="capability-row">
            <StatusChip label="知识库取证" tone="info" />
            <StatusChip label="故障码定位" tone="accent" />
            <StatusChip label="网页核实" tone="neutral" />
          </div>
          <div class="suggest-row">
            <button v-for="q in SUGGESTIONS" :key="q" type="button" class="suggest-chip" @click="quickAsk(q)">
              {{ q }}
            </button>
          </div>
        </div>

        <template v-for="(turn, i) in turns" :key="i">
          <div v-if="turn.role === 'user'" class="bubble-row user">{{ turn.content }}</div>

          <div v-else class="assistant-block">
            <!-- 工具时间线：查证过程语义化呈现（正在 X… / 已 X），让"先查证据再下结论"看得见 -->
            <div v-if="turn.tools.length" class="tool-timeline">
              <div
                v-for="(t, ti) in turn.tools"
                :key="ti"
                class="tl-step"
                :class="{ done: t.result !== null }"
              >
                <span class="tl-dot" aria-hidden="true">{{ t.result === null ? '' : '✓' }}</span>
                <span class="tl-text">
                  {{ t.result === null ? `正在${toolBrief(t.name, t.args)}…` : `已${toolBrief(t.name, t.args)}` }}
                </span>
              </div>
            </div>

            <!-- 流式正文不逐字显示：模型输出是 markdown，半截原文体验差；结束后一次性渲染 -->
            <div
              v-if="turn.content && !turn.streaming"
              class="bubble assistant md-body"
              v-html="renderMd(turn.content)"
            ></div>

            <!-- ask_user 卡片：选项点选 + 自由输入；挂起期间可离线，回答后自动继续诊断 -->
            <div v-if="turn.questions" class="ask-card">
              <p class="ask-title">为了判断更准确，请补充：</p>
              <p class="ask-hint">判断不了就选「{{ UNCLEAR_LABEL }}」，不会卡住诊断。</p>
              <div v-for="q in turn.questions" :key="q.id" class="ask-item">
                <p class="ask-q">{{ q.question }}</p>
                <div class="opt-row">
                  <button
                    v-for="opt in filterOptions(q)"
                    :key="opt"
                    type="button"
                    class="opt-chip"
                    :class="{ active: turn.answers[q.id] === opt }"
                    :aria-pressed="turn.answers[q.id] === opt"
                    @click="toggleOpt(turn, q.id, opt)"
                  >
                    {{ opt }}
                  </button>
                  <button
                    type="button"
                    class="opt-chip"
                    :class="{ active: turn.answers[q.id] === UNCLEAR_VALUE }"
                    :aria-pressed="turn.answers[q.id] === UNCLEAR_VALUE"
                    @click="toggleOpt(turn, q.id, UNCLEAR_VALUE)"
                  >
                    {{ UNCLEAR_LABEL }}
                  </button>
                </div>
                <el-input
                  v-if="q.allow_free !== false"
                  v-model="turn.answers[q.id]"
                  size="small"
                  placeholder="或手动输入…"
                  clearable
                />
              </div>
              <el-button type="primary" size="small" :disabled="sending" @click="submitAnswers(turn)">
                提交并继续诊断
              </el-button>
            </div>

            <!-- 三段式诊断卡片：严重度 + 结论 + 假设 + 步骤 + 待确认 -->
            <div v-if="turn.diag" class="diag-card" :data-severity="turn.diag.severity">
              <div class="diag-head">
                <SeverityBadge :severity="turn.diag.severity" />
                <span class="diag-title">AI 诊断结论</span>
              </div>
              <p class="diag-summary">{{ turn.diag.summary }}</p>
              <div v-if="turn.diag.hypotheses?.length" class="diag-sec">
                <p class="sec-title">可能原因</p>
                <ul>
                  <!-- 车主端不显示来源详情：hypotheses.evidence（依据 [1] …）不再渲染 -->
                  <li v-for="(h, hi) in turn.diag.hypotheses" :key="hypTitle(h) || hi">{{ hypTitle(h) }}</li>
                </ul>
              </div>
              <div v-if="turn.diag.steps?.length" class="diag-sec">
                <p class="sec-title">建议检修步骤</p>
                <ol>
                  <li v-for="s in turn.diag.steps" :key="s">{{ s }}</li>
                </ol>
              </div>
              <div v-if="turn.diag.pending_checks?.length" class="diag-sec">
                <p class="sec-title">仍需到店确认</p>
                <ul>
                  <li v-for="c in turn.diag.pending_checks" :key="c">{{ c }}</li>
                </ul>
              </div>
              <p v-if="evidenceLine(turn)" class="evidence-line">✓ {{ evidenceLine(turn) }}</p>
              <el-button
                v-if="turn.diag.severity !== 'green'"
                class="book-btn"
                type="warning"
                size="small"
                @click="onBook"
              >
                预约进店检修
              </el-button>
            </div>

            <span v-if="turn.streaming && !turn.diag && turn.tools.length === 0" class="typing">
              正在分析您的问题…
            </span>
          </div>
        </template>
      </div>

      <footer class="composer">
        <VoiceButton
          v-if="auth.user && auth.user.role !== 'superadmin'"
          :disabled="composerDisabled"
          :provider="asrProvider"
          @transcribed="onVoiceText"
          @error="onVoiceError"
        />
        <div class="composer-input">
          <el-input
            ref="inputRef"
            v-model="input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            :placeholder="placeholder"
            :disabled="composerDisabled"
            resize="none"
            aria-label="输入车辆问题"
            @keydown.enter.exact.prevent="onSend"
          />
          <span class="composer-hint">Enter 发送 · Shift + Enter 换行 · 语音文本需确认后发送</span>
        </div>
        <el-button
          class="send-btn"
          type="primary"
          :icon="Promotion"
          :loading="sending"
          :disabled="composerDisabled"
          aria-label="发送消息"
          @click="onSend"
        >
          发送
        </el-button>
      </footer>
    </main>

    <aside class="context-pane">
      <ContextPanel
        :role="role"
        :vehicle="activeSession?.vehicle ?? null"
        :diag="latestDiag"
        :stages="stageSteps"
        :tools="contextTools"
        :privacy-dialog="auth.user?.privacy_share_dialog ?? false"
        :privacy-admin="auth.user?.privacy_share_admin ?? false"
      />
    </aside>

    <el-drawer v-model="drawerOpen" title="诊断会话" size="78%" direction="ltr">
      <el-button type="primary" style="width: 100%" @click="onNewSession">＋ 新话题</el-button>
      <div class="session-list drawer-list">
        <button
          v-for="s in sessions"
          :key="s.id"
          type="button"
          class="session-item"
          :class="{ active: s.id === activeId }"
          @click="openSession(s.id)"
        >
          <span class="session-dot" :class="{ pending: s.has_pending }" aria-hidden="true"></span>
          <span class="session-title">{{ s.title }}</span>
          <span v-if="s.has_pending" class="pending-tag">待补充</span>
        </button>
      </div>
    </el-drawer>

    <Sheet v-model="contextOpen" title="诊断上下文">
      <ContextPanel
        :role="role"
        :vehicle="activeSession?.vehicle ?? null"
        :diag="latestDiag"
        :stages="stageSteps"
        :tools="contextTools"
        :privacy-dialog="auth.user?.privacy_share_dialog ?? false"
        :privacy-admin="auth.user?.privacy_share_admin ?? false"
      />
    </Sheet>

    <!-- 一键预约弹窗（全局唯一实例，诊断卡按钮打开） -->
    <el-dialog v-model="bookDialogVisible" title="预约进店检修" width="min(92vw, 420px)">
      <el-form label-width="90px">
        <el-form-item label="到店时间">
          <el-date-picker
            v-model="bookTime"
            type="datetime"
            placeholder="选择日期和时间"
            format="YYYY-MM-DD HH:mm"
          />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input v-model="bookNote" type="textarea" :rows="2" maxlength="300" placeholder="选填" />
        </el-form-item>
      </el-form>
      <p class="book-tip">提交后将自动携带车辆档案与本轮 AI 诊断摘要，门店无需复述问题。</p>
      <template #footer>
        <el-button @click="bookDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="booking" @click="submitBooking">提交预约</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  block-size: calc(100vh - var(--hmi-topbar-h));
  block-size: calc(100dvh - var(--hmi-topbar-h));
  overflow: hidden;
  background: var(--hmi-bg);
}

.session-pane {
  inline-size: 246px;
  flex: none;
  display: flex;
  flex-direction: column;
  border-inline-end: 1px solid var(--hmi-line);
  background: rgba(11, 18, 23, 0.7);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.8rem 0.8rem 0.55rem;
}

.pane-head h2 {
  font-size: var(--hmi-fs-4);
  font-weight: 650;
}

.session-search {
  padding-inline: 0.7rem;
  margin-block-end: 0.4rem;
}

.session-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 0.25rem 0.55rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  inline-size: 100%;
  min-block-size: 38px;
  padding: 0.45rem 0.55rem;
  border: 1px solid transparent;
  border-radius: var(--hmi-radius-sm);
  background: transparent;
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-2);
  text-align: start;
  cursor: pointer;
}

.session-item:hover {
  background: var(--hmi-surface-2);
  color: var(--hmi-text);
}

.session-item.active {
  background: var(--hmi-accent-soft);
  border-color: var(--hmi-accent-line);
  color: var(--hmi-accent);
}

.session-dot {
  inline-size: 6px;
  block-size: 6px;
  border-radius: 50%;
  background: var(--hmi-line-strong);
  flex: none;
}

.session-dot.pending {
  background: var(--hmi-warn);
}

.session-title {
  flex: 1 1 auto;
  min-inline-size: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pending-tag {
  flex: none;
  color: var(--hmi-warn);
  font-size: 0.62rem;
}

.empty-hint {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  text-align: center;
  padding: 1.4rem 0.5rem;
}

.pane-foot {
  padding: 0.55rem 0.8rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.chat-main {
  flex: 1 1 auto;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-block-size: 52px;
  padding: 0.45rem 0.9rem;
  border-block-end: 1px solid var(--hmi-line);
  background: rgba(11, 18, 23, 0.55);
}

.title-block {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
}

.title-block strong {
  font-size: var(--hmi-fs-3);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.head-meta {
  margin-inline-start: auto;
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.msg-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 1rem clamp(0.7rem, 2vw, 1.3rem);
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.hero {
  margin: auto;
  text-align: center;
  max-inline-size: 520px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
}

.hero-mark {
  display: grid;
  place-items: center;
  inline-size: 54px;
  block-size: 54px;
  border-radius: 16px;
  color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
  border: 1px solid var(--hmi-accent-line);
}

.hero h2 {
  font-size: clamp(1.1rem, 2vw, 1.35rem);
  font-weight: 650;
}

.hero p {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  line-height: 1.7;
}

.capability-row {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
  justify-content: center;
}

.suggest-row {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  inline-size: 100%;
  margin-block-start: 0.5rem;
}

.suggest-chip {
  background: var(--hmi-surface);
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-2);
  padding: 0.6rem 0.8rem;
  cursor: pointer;
  text-align: start;
}

.suggest-chip:hover {
  border-color: var(--hmi-accent-line);
  color: var(--hmi-text);
}

.bubble-row.user {
  align-self: flex-end;
  max-inline-size: 78%;
  background: var(--user-bg);
  border: 1px solid var(--hmi-accent-line);
  border-radius: 12px 12px 2px 12px;
  padding: 0.55rem 0.8rem;
  font-size: var(--hmi-fs-3);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.assistant-block {
  align-self: flex-start;
  max-inline-size: 88%;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.tool-timeline {
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  background: var(--hmi-surface);
  border: 1px solid var(--hmi-line-soft);
  border-radius: var(--hmi-radius);
  padding: 0.4rem 0.65rem;
}

.tl-step {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.18rem 0;
}

.tl-dot {
  flex: none;
  inline-size: 14px;
  block-size: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--hmi-line-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.58rem;
  color: var(--hmi-accent);
}

.tl-step.done .tl-dot {
  border-color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
}

.tl-step:not(.done) .tl-dot {
  border-color: var(--hmi-accent);
  animation: tl-pulse 1.2s ease-in-out infinite;
}

@keyframes tl-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(53, 214, 194, 0.3);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(53, 214, 194, 0.05);
  }
}

.tl-text {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.tl-step.done .tl-text {
  color: var(--hmi-text-2);
}

.typing {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  animation: tl-pulse 1.2s ease-in-out infinite;
}

.evidence-line {
  margin: 0;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-accent);
}

.bubble.assistant {
  background: var(--hmi-surface);
  border: 1px solid var(--hmi-line);
  border-radius: 12px 12px 12px 2px;
  padding: 0.6rem 0.85rem;
  font-size: var(--hmi-fs-3);
  overflow-wrap: anywhere;
}

.bubble.assistant.md-body {
  white-space: normal;
}

.md-body :deep(p) {
  margin: 0 0 0.5em;
}

.md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 0.25em 0;
  padding-inline-start: 1.3em;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  font-size: 0.95rem;
  margin: 0.4em 0 0.3em;
}

.md-body :deep(code) {
  font-family: var(--hmi-font-mono);
  font-size: 0.85em;
  padding: 0.05em 0.3em;
  border-radius: 4px;
  background: var(--hmi-bg-deep);
}

.ask-card {
  background: var(--hmi-surface);
  border: 1px solid var(--hmi-accent-line);
  border-radius: var(--hmi-radius);
  padding: 0.75rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.ask-title {
  font-size: var(--hmi-fs-3);
  font-weight: 600;
  color: var(--hmi-accent);
}

.ask-hint {
  margin-block-start: -0.35rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.ask-item {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.ask-q {
  font-size: var(--hmi-fs-3);
}

.opt-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.opt-chip {
  background: transparent;
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  color: var(--hmi-text-2);
  font-size: var(--hmi-fs-2);
  padding: 0.3rem 0.7rem;
  min-block-size: 32px;
  cursor: pointer;
}

.opt-chip.active {
  border-color: var(--hmi-accent);
  background: var(--hmi-accent-soft);
  color: var(--hmi-accent);
}

.diag-card {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.022), transparent 50%), var(--hmi-surface);
  border: 1px solid var(--hmi-line);
  border-inline-start: 3px solid var(--hmi-warn);
  border-radius: var(--hmi-radius);
  padding: 0.8rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.diag-card[data-severity='red'] {
  border-inline-start-color: var(--hmi-danger);
}

.diag-card[data-severity='green'] {
  border-inline-start-color: var(--hmi-ok);
}

.diag-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.diag-title {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
  letter-spacing: 0.04em;
}

.diag-summary {
  font-size: var(--hmi-fs-4);
  font-weight: 600;
}

.diag-sec {
  font-size: var(--hmi-fs-2);
}

.diag-sec ul,
.diag-sec ol {
  margin: 0.25rem 0 0;
  padding-inline-start: 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  color: var(--hmi-text-2);
}

.sec-title {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  font-weight: 600;
}

.book-btn {
  align-self: flex-start;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  padding: 0.65rem clamp(0.7rem, 2vw, 1.2rem);
  padding-block-end: calc(0.65rem + env(safe-area-inset-bottom, 0px));
  border-block-start: 1px solid var(--hmi-line);
  background: rgba(11, 18, 23, 0.82);
}

.composer-input {
  flex: 1 1 auto;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.composer-hint {
  color: var(--hmi-text-3);
  font-size: 0.62rem;
  padding-inline-start: 2px;
}

.context-pane {
  inline-size: 274px;
  flex: none;
  overflow-y: auto;
  padding: 0.8rem 0.7rem 0.8rem 0;
}

.mobile-only {
  display: none;
}

.drawer-list {
  margin-block-start: 0.7rem;
}

.book-tip {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  margin: 0.4rem 0 0;
}

@media (max-width: 1180px) {
  .context-pane {
    display: none;
  }

  .chat-head .mobile-only:last-child {
    display: inline-flex;
    margin-inline-start: auto;
  }
}

@media (max-width: 900px) {
  .session-pane {
    display: none;
  }

  .chat-page {
    block-size: calc(100vh - var(--hmi-topbar-h) - var(--hmi-tabbar-h));
    block-size: calc(100dvh - var(--hmi-topbar-h) - var(--hmi-tabbar-h));
  }

  .mobile-only {
    display: inline-flex;
  }

  .head-meta {
    margin-inline-start: auto;
  }

  .bubble-row.user,
  .assistant-block {
    max-inline-size: 94%;
  }

  .composer-hint {
    display: none;
  }

  .send-btn {
    padding-inline: 0.85rem;
  }

  .msg-list {
    padding-block-end: 0.6rem;
  }
}

@media (max-width: 520px) {
  .send-btn :deep(span) {
    display: none;
  }

  .send-btn {
    padding-inline: 0.7rem;
  }

  .chat-head {
    padding-inline: 0.6rem;
  }

  .head-meta {
    display: none;
  }
}
</style>

<!-- 非 scoped：移动端输入控件统一 16px，防 iOS 聚焦自动放大页面；
     覆盖含 teleport 弹层（预约日期面板等）在内的所有 Element Plus 输入 -->
<style>
@media (max-width: 768px) {
  .el-textarea__inner,
  .el-input__inner {
    font-size: 16px !important;
  }
}
</style>
