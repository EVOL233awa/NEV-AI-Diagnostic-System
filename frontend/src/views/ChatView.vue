<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, ChatDotRound, Promotion } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import BackHome from '../components/BackHome.vue'
import { auth } from '../stores/auth'
import { createAppointment, localIso } from '../api/client'
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

const router = useRouter()

// 模型输出是 markdown（加粗/列表/引用标注）；html:false 防注入，breaks 让单换行成段
const md = new MarkdownIt({ html: false, breaks: true, linkify: false })

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
}

const SEVERITY_META: Record<string, { icon: string; label: string; color: string }> = {
  green: { icon: '🟢', label: '正常 / 无需处理', color: 'var(--accent)' },
  yellow: { icon: '🟡', label: '功能性异常 · 需尽快检查', color: '#e6a23c' },
  red: { icon: '🔴', label: '安全风险 · 立即停止使用并进店', color: '#f56c6c' },
}

const SUGGESTIONS = [
  '仪表盘提示动力电池故障，还能继续开吗？',
  '冬天续航掉得特别快，是电池坏了吗？',
  '充电到 80% 就充不进去了，什么原因？',
]

function sevMeta(severity: string): { icon: string; label: string; color: string } {
  return SEVERITY_META[severity] ?? SEVERITY_META.yellow
}

const sessions = ref<SessionInfo[]>([])
const activeId = ref<number | null>(null)
const turns = ref<Turn[]>([])
const input = ref('')
const sending = ref(false)
const drawerOpen = ref(false)
const listEl = ref<HTMLElement | null>(null)

const activeSession = computed(() => sessions.value.find((s) => s.id === activeId.value) ?? null)
const hasPending = computed(() => turns.value.some((t) => t.questions && t.questions.length > 0))
const composerDisabled = computed(() => sending.value || hasPending.value)
const placeholder = computed(() =>
  hasPending.value ? '请先回答上方的补充信息问题' : '描述车辆问题，例如：低速行驶时提示电池故障',
)

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
  if (!content) return
  input.value = ''
  await sendContent(content)
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
  await refreshSessions()
  if (sessions.value.length > 0) {
    await openSession(sessions.value[0].id)
  }
})
</script>

<template>
  <div class="chat-page">
    <aside class="sidebar">
      <div class="side-head">
        <el-button :icon="Back" text size="small" @click="router.push({ name: 'home' })">主页</el-button>
        <el-button type="primary" size="small" round @click="onNewSession">＋ 新话题</el-button>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === activeId }"
          @click="openSession(s.id)"
        >
          <span class="session-title">{{ s.title }}</span>
          <el-tag v-if="s.has_pending" size="small" type="warning" effect="plain">待补充</el-tag>
        </div>
        <p v-if="sessions.length === 0" class="empty-hint">还没有会话，点「新话题」开始</p>
      </div>
    </aside>

    <main class="chat-main">
      <header class="chat-header">
        <el-button class="mobile-only" :icon="ChatDotRound" text @click="drawerOpen = true" />
        <BackHome />
        <span class="chat-title">{{ activeSession?.title ?? 'AI 诊断助手' }}</span>
        <el-tag size="small" type="success" effect="dark">{{ CHAT_TAG[auth.user?.role ?? 'owner'] }}</el-tag>
      </header>

      <div ref="listEl" class="msg-list">
        <div v-if="turns.length === 0" class="hero">
          <h2>新能源汽车 AI 诊断助手</h2>
          <p>描述你的车辆问题，我会先查证据再下结论；信息不够时我会向你提问。</p>
          <div class="suggest-row">
            <button v-for="q in SUGGESTIONS" :key="q" class="suggest-chip" @click="quickAsk(q)">
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
                <span class="tl-dot">{{ t.result === null ? '' : '✓' }}</span>
                <span class="tl-text">
                  {{ t.result === null ? `正在${toolBrief(t.name, t.args)}…` : `已${toolBrief(t.name, t.args)}` }}
                </span>
              </div>
            </div>

            <!-- 流式正文不逐字显示：模型输出是 markdown，半截原文体验差；
                 结束后一次性渲染最终结果 -->
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
                    class="opt-chip"
                    :class="{ active: turn.answers[q.id] === opt }"
                    @click="toggleOpt(turn, q.id, opt)"
                  >
                    {{ opt }}
                  </button>
                  <!-- 兜底选项：车主无法判断现象时也能继续，避免问答阻塞主流程 -->
                  <button
                    class="opt-chip"
                    :class="{ active: turn.answers[q.id] === UNCLEAR_VALUE }"
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
              <el-button
                type="primary"
                size="small"
                round
                :disabled="sending"
                @click="submitAnswers(turn)"
              >
                提交并继续诊断
              </el-button>
            </div>

            <!-- 三段式诊断卡片：严重度 + 结论 + 假设 + 步骤 + 待确认 -->
            <div
              v-if="turn.diag"
              class="diag-card"
              :style="{ borderColor: sevMeta(turn.diag.severity).color }"
            >
              <div class="diag-head">
                <span class="diag-icon">{{ sevMeta(turn.diag.severity).icon }}</span>
                <span class="diag-label" :style="{ color: sevMeta(turn.diag.severity).color }">
                  {{ sevMeta(turn.diag.severity).label }}
                </span>
              </div>
              <p class="diag-summary">{{ turn.diag.summary }}</p>
              <div v-if="turn.diag.hypotheses?.length" class="diag-sec">
                <p class="sec-title">可能原因</p>
                <ul>
                  <!-- 车主端不显示来源详情：hypotheses.evidence（依据 [1] …）不再渲染 -->
                  <li v-for="(h, i) in turn.diag.hypotheses" :key="hypTitle(h) || i">
                    {{ hypTitle(h) }}
                  </li>
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
              <p
                v-if="evidenceLine(turn)"
                class="evidence-line"
              >
                ✓ {{ evidenceLine(turn) }}
              </p>
              <el-button
                v-if="turn.diag.severity !== 'green'"
                class="book-btn"
                type="warning"
                size="small"
                round
                @click="onBook"
              >
                📅 一键预约进店检修
              </el-button>
            </div>

            <!-- 首步等待（尚未调用任何工具）：给出拟人化状态而不是裸转圈 -->
            <span v-if="turn.streaming && !turn.diag && turn.tools.length === 0" class="typing">
              正在分析您的问题…
            </span>
          </div>
        </template>
      </div>

      <footer class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          :placeholder="placeholder"
          :disabled="composerDisabled"
          resize="none"
          @keydown.enter.exact.prevent="onSend"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="sending"
          :disabled="composerDisabled"
          @click="onSend"
        >
          发送
        </el-button>
      </footer>

      <!-- 一键预约弹窗（全局唯一实例，诊断卡按钮打开） -->
      <el-dialog v-model="bookDialogVisible" title="预约进店检修" width="400px">
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
    </main>

    <el-drawer v-model="drawerOpen" title="会话列表" size="75%" direction="ltr">
      <el-button type="primary" round style="width: 100%" @click="onNewSession">＋ 新话题</el-button>
      <div class="session-list drawer-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === activeId }"
          @click="openSession(s.id)"
        >
          <span class="session-title">{{ s.title }}</span>
          <el-tag v-if="s.has_pending" size="small" type="warning" effect="plain">待补充</el-tag>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: 100vh;
  /* 移动端动态视口：键盘弹起/地址栏收展时高度正确（不支持 dvh 的内核回落 100vh） */
  height: 100dvh;
  overflow: hidden;
}

.sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 0.7rem;
  border-bottom: 1px solid var(--border);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  padding: 0.5rem 0.6rem;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.78rem;
  color: var(--text);
}

.session-item:hover {
  background: rgba(45, 212, 168, 0.08);
}

.session-item.active {
  background: rgba(45, 212, 168, 0.14);
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-hint {
  color: var(--muted);
  font-size: 0.72rem;
  text-align: center;
  margin-top: 1rem;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.chat-title {
  flex: 1;
  font-size: 0.9rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 1.1rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.hero {
  margin: auto;
  text-align: center;
  max-width: 480px;
}

.hero h2 {
  font-size: 1.2rem;
  margin: 0 0 0.5rem;
}

.hero p {
  color: var(--muted);
  font-size: 0.82rem;
  margin: 0 0 1.2rem;
}

.suggest-row {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.suggest-chip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  font-size: 0.8rem;
  padding: 0.55rem 0.8rem;
  cursor: pointer;
  text-align: left;
}

.suggest-chip:hover {
  border-color: var(--accent);
}

.bubble-row.user {
  align-self: flex-end;
  max-width: 78%;
  background: var(--user-bg);
  border-radius: 12px 12px 2px 12px;
  padding: 0.6rem 0.85rem;
  font-size: 0.85rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-block {
  align-self: flex-start;
  max-width: 88%;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

/* 查证时间线：左侧圆点+竖线串联，进行中呼吸闪烁，完成变实心对勾 */
.tool-timeline {
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  background: var(--assistant-bg);
  border: 1px dashed var(--border);
  border-radius: 10px;
  padding: 0.5rem 0.75rem;
}

.tl-step {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.22rem 0;
}

/* 竖线：连接相邻步骤的圆点 */
.tl-step:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 7px;
  top: calc(50% + 6px);
  bottom: -10px;
  width: 1px;
  background: var(--border);
}

.tl-dot {
  flex-shrink: 0;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  border: 1.5px solid var(--border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  color: var(--accent);
}

.tl-step.done .tl-dot {
  border-color: var(--accent);
  background: rgba(45, 212, 168, 0.16);
}

.tl-step:not(.done) .tl-dot {
  border-color: var(--accent);
  animation: tl-pulse 1.2s ease-in-out infinite;
}

@keyframes tl-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(45, 212, 168, 0.35);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(45, 212, 168, 0.06);
  }
}

.tl-text {
  font-size: 0.74rem;
  color: var(--muted);
}

.tl-step.done .tl-text {
  color: var(--text);
}

.typing {
  color: var(--muted);
  font-size: 0.78rem;
  animation: tl-pulse 1.2s ease-in-out infinite;
}

/* 诊断卡置信信号：聚合查证声明（不带来源细节） */
.evidence-line {
  margin: 0;
  font-size: 0.72rem;
  color: var(--accent);
  opacity: 0.85;
}

.bubble.assistant {
  background: var(--assistant-bg);
  border: 1px solid var(--border);
  border-radius: 12px 12px 12px 2px;
  padding: 0.6rem 0.85rem;
  font-size: 0.85rem;
  white-space: pre-wrap;
  word-break: break-word;
}

/* markdown 渲染后的气泡：结构化标签自带换行，关掉 pre-wrap 并收紧行距 */
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
  padding-left: 1.3em;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  font-size: 0.9rem;
  margin: 0.4em 0 0.3em;
}

.book-tip {
  color: var(--muted);
  font-size: 0.75rem;
  margin: 0.4rem 0 0;
}

.ask-card {
  background: var(--assistant-bg);
  border: 1px solid var(--accent-dim);
  border-radius: 10px;
  padding: 0.75rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.ask-title {
  margin: 0;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--accent);
}

.ask-hint {
  margin: -0.35rem 0 0;
  font-size: 0.7rem;
  color: var(--muted);
}

.ask-item {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.ask-q {
  margin: 0;
  font-size: 0.8rem;
}

.opt-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.opt-chip {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text);
  font-size: 0.75rem;
  padding: 0.3rem 0.75rem;
  cursor: pointer;
}

.opt-chip.active {
  border-color: var(--accent);
  background: rgba(45, 212, 168, 0.16);
  color: var(--accent);
}

.diag-card {
  background: var(--surface);
  border: 1px solid;
  border-radius: 10px;
  padding: 0.8rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.diag-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.diag-icon {
  font-size: 1rem;
}

.diag-label {
  font-size: 0.85rem;
  font-weight: 700;
}

.diag-summary {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
}

.diag-sec {
  font-size: 0.78rem;
}

.diag-sec ul,
.diag-sec ol {
  margin: 0.25rem 0 0;
  padding-left: 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.sec-title {
  margin: 0;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 600;
}

.book-btn {
  align-self: flex-start;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  /* iPhone 底部横条不压住输入栏（viewport-fit=cover 生效前提） */
  padding-bottom: calc(0.75rem + env(safe-area-inset-bottom));
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.mobile-only {
  display: none;
}

@media (max-width: 768px) {
  .sidebar {
    display: none;
  }

  .mobile-only {
    display: inline-flex;
  }

  .desktop-only {
    display: none;
  }

  .bubble-row.user,
  .assistant-block {
    max-width: 94%;
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
