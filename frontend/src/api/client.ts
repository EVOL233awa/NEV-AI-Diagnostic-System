/**
 * API 客户端：默认同源（FastAPI 托管 dist）。跨源部署时后端地址由部署者在
 * superadmin 后台「前端接入地址」按浏览器配置（localStorage）；留空即走相对路径。
 */
import axios from 'axios'

export const API_BASE_KEY = 'nev2_api_base'
export const TOKEN_KEY = 'nev2_token'
const USER_KEY = 'nev2_user'

/** 构建期注入的默认后端地址（.env.production）：留空 = 同源 */
const DEFAULT_API_BASE = (import.meta.env.VITE_API_BASE_DEFAULT as string | undefined) ?? ''

export function getApiBase(): string {
  const stored = localStorage.getItem(API_BASE_KEY)
  if (stored !== null) {
    return stored.trim().replace(/\/+$/, '')
  }
  return DEFAULT_API_BASE.trim().replace(/\/+$/, '')
}

export function setApiBase(base: string): void {
  // 空值也写入而非删除：显式「同源」要能压过构建默认值
  localStorage.setItem(API_BASE_KEY, base.trim().replace(/\/+$/, ''))
}

export const http = axios.create({ timeout: 15000 })

http.interceptors.request.use((config) => {
  config.baseURL = getApiBase()
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** 401 统一出口：清 token 并回登录页（axios 与原生 fetch 的 SSE 共用）。 */
export function handleAuthExpired(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  if (location.pathname !== '/login') location.href = '/login'
}

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status: number | undefined = error.response?.status
    if (status === 401) handleAuthExpired()
    return Promise.reject(error)
  },
)

export interface AuthUser {
  id: number
  username: string
  role: 'owner' | 'staff' | 'admin' | 'superadmin'
  display_name: string
  privacy_share_dialog: boolean
  privacy_share_admin: boolean
}

export interface LoginResp {
  token: string
  user: AuthUser
  version: string
}

export interface HealthResp {
  ok: boolean
  app: string
  version: string
  time: string
  providers: {
    main_model: string
    web_search: boolean
    search_provider?: 'deepseek' | 'tavily' | 'custom'
    asr_configured?: boolean
    asr_provider?: 'deepseek' | 'openai'
  }
}

export function saveToken(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export async function fetchHealth(): Promise<HealthResp> {
  const base = getApiBase()
  const { data } = await axios.get<HealthResp>(`${base}/api/health`, { timeout: 6000 })
  return data
}

export async function login(username: string, password: string): Promise<LoginResp> {
  const { data } = await http.post<LoginResp>('/api/auth/login', { username, password })
  return data
}

export interface TranscribeResp {
  text: string
  duration_ms: number
  provider: string
  request_id: string | null
}

/** 语音转文字：上传录音 Blob（multipart），返回可编辑文本；不自动发送。 */
export async function transcribeAudio(
  blob: Blob,
  filename: string,
  durationMs: number,
): Promise<TranscribeResp> {
  const form = new FormData()
  form.append('file', blob, filename)
  form.append('duration_ms', String(Math.max(0, Math.round(durationMs))))
  const { data } = await http.post<TranscribeResp>('/api/asr/transcribe', form, { timeout: 90000 })
  return data
}

export interface KbDocumentInfo {
  id: number
  title: string
  filename: string
  category: string
  source_url: string
  source_note: string
  status: string
  chunk_count: number
}

export interface KbChunkInfo {
  id: number
  seq: number
  section_path: string
  page_no: number | null
  content: string
}

export interface KbSearchHit {
  chunk_id: number
  document: string
  category: string
  section: string
  page_no: number | null
  score: number
  legs: string[]
  content: string
}

export async function listKbDocuments(): Promise<KbDocumentInfo[]> {
  const { data } = await http.get<{ documents: KbDocumentInfo[] }>('/api/kb/documents')
  return data.documents
}

export async function uploadKbDocument(form: FormData): Promise<{ id: number; title: string; chunk_count: number }> {
  const { data } = await http.post('/api/kb/documents', form, { timeout: 120000 })
  return data
}

export async function listKbChunks(docId: number): Promise<KbChunkInfo[]> {
  const { data } = await http.get<{ chunks: KbChunkInfo[] }>(`/api/kb/documents/${docId}/chunks`)
  return data.chunks
}

export async function deleteKbDocument(docId: number): Promise<void> {
  await http.delete(`/api/kb/documents/${docId}`)
}

export async function kbSearch(query: string, category: string | null, topK: number): Promise<KbSearchHit[]> {
  const { data } = await http.post<{ results: KbSearchHit[] }>('/api/kb/search', {
    query,
    category: category || null,
    top_k: topK,
  })
  return data.results
}

/* ---------------- 预约闭环 / 车辆档案 / 成员管理 / 统计审计 ---------------- */

/** 本地时间 → 无时区 ISO 串（YYYY-MM-DDTHH:mm:ss）。
 * 不用 toISOString：那是 UTC，会偏移时区且让后端拿到 aware datetime。 */
export function localIso(d: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

/** 列表页摘要压缩成一句话：取第一句（到 。！？；为止），超长则在附近标点处截断加省略号。
 * 完整内容始终在详情（展开/抽屉）里可见，这里只管列表可读性。 */
export function oneLine(text: string | null | undefined, max = 40): string {
  const t = (text ?? '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  const end = t.search(/[。！？；]/)
  const first = end >= 0 ? t.slice(0, end + 1) : t
  if (first.length <= max) return first
  const cut = first.slice(0, max)
  const comma = Math.max(cut.lastIndexOf('，'), cut.lastIndexOf('、'), cut.lastIndexOf(' '))
  return (comma > max * 0.5 ? cut.slice(0, comma) : cut) + '…'
}

/** ISO 时间串转短格式（T → 空格），仅用于展示 */
export function fmtIso(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

export type AppointmentStatus = 'pending' | 'accepted' | 'completed' | 'cancelled'

export interface SummaryCard {
  severity: string
  summary: string
  hypotheses: string[]
  steps: string[]
  pending_checks: string[]
  generated_at: string
  note?: string
}

export interface AppointmentInfo {
  id: number
  status: AppointmentStatus
  appointment_time: string | null
  summary_card: SummaryCard | null
  shop_note: string
  repair_result: string
  accepted_by: number | null
  session_id: number | null
  created_at: string | null
  owner_name: string
  owner_privacy_share: boolean
  vehicle: string
}

export async function createAppointment(input: {
  session_id?: number
  appointment_time: string
  note?: string
}): Promise<{ id: number; status: AppointmentStatus }> {
  const { data } = await http.post('/api/appointments', input)
  return data
}

export async function listAppointments(status?: AppointmentStatus | null): Promise<AppointmentInfo[]> {
  const { data } = await http.get<{ appointments: AppointmentInfo[] }>('/api/appointments', {
    params: status ? { status_filter: status } : {},
  })
  return data.appointments
}

export async function fetchAppointmentDetail(id: number): Promise<AppointmentInfo> {
  const { data } = await http.get<AppointmentInfo>(`/api/appointments/${id}`)
  return data
}

export async function acceptAppointment(id: number, input: { appointment_time?: string; shop_note?: string }): Promise<void> {
  await http.post(`/api/appointments/${id}/accept`, input)
}

export async function completeAppointment(id: number, repairResult: string): Promise<void> {
  await http.post(`/api/appointments/${id}/complete`, { repair_result: repairResult })
}

export async function cancelAppointment(id: number, reason: string): Promise<void> {
  await http.post(`/api/appointments/${id}/cancel`, { reason })
}

export async function fetchAppointmentDialog(id: number): Promise<{ session_id: number; messages: { role: string; content: string }[] }> {
  const { data } = await http.get(`/api/appointments/${id}/dialog`)
  return data
}

/** 车主端严重度通俗文案：车主不理解红黄绿分级含义（2026-09-26 反馈），标签配色保留作视觉提示 */
export const SEVERITY_LABEL: Record<string, string> = {
  red: '需尽快检修',
  yellow: '建议到店检查',
  green: '正常',
}

export const DIAG_STAGE_LABEL: Record<string, string> = {
  intake: '问诊',
  hypothesis: '假设',
  verification: '查证',
  conclusion: '结论',
}

export interface DiagBrief {
  session_id: number
  severity: string
  summary: string
  session_title: string
  stage: 'intake' | 'hypothesis' | 'verification' | 'conclusion' | null
  has_case: boolean
  created_at: string | null
}

export interface VehicleInfo {
  id: number
  vin: string
  plate_no: string
  brand: string
  model_name: string
  model_year: string
  power_type: string
  notes: string
  mileage: number | null
  is_default: boolean
  history?: DiagBrief[]
}

export async function listMyVehicles(): Promise<VehicleInfo[]> {
  const { data } = await http.get<{ vehicles: VehicleInfo[] }>('/api/vehicles')
  return data.vehicles
}

export async function addVehicle(input: Partial<VehicleInfo>): Promise<{ id: number }> {
  const { data } = await http.post('/api/vehicles', input)
  return data
}

export async function patchVehicle(id: number, input: Partial<VehicleInfo> & { is_default?: boolean }): Promise<void> {
  await http.patch(`/api/vehicles/${id}`, input)
}

export async function deleteVehicle(id: number): Promise<{ ok: boolean }> {
  const { data } = await http.delete(`/api/vehicles/${id}`)
  return data
}

export async function searchVehicles(q: string): Promise<VehicleInfo[]> {
  const { data } = await http.get<{ vehicles: VehicleInfo[] }>('/api/vehicles/search', { params: { q } })
  return data.vehicles
}

export async function fetchVehicleHistory(
  id: number,
  limit = 20,
  offset = 0,
): Promise<{ vehicle_id: number; total: number; items: DiagBrief[] }> {
  const { data } = await http.get(`/api/vehicles/${id}/history`, { params: { limit, offset } })
  return data
}

export interface AdminUserInfo {
  id: number
  username: string
  role: AuthUser['role']
  display_name: string
  disabled: boolean
  privacy_share_dialog: boolean
  created_at: string | null
  last_login_at: string | null
  vehicle: string
}

export async function listAdminUsers(): Promise<AdminUserInfo[]> {
  const { data } = await http.get<{ users: AdminUserInfo[] }>('/api/admin/users')
  return data.users
}

export async function createAdminUser(input: {
  username: string
  display_name?: string
  role: AuthUser['role']
  vehicle_brand?: string
  vehicle_model?: string
  vehicle_year?: string
  vehicle_power_type?: string
  vehicle_vin?: string
  vehicle_plate?: string
  vehicle_notes?: string
}): Promise<{ id: number; username: string; role: string }> {
  const { data } = await http.post('/api/admin/users', input)
  return data
}

export async function updateAdminUser(id: number, input: { display_name?: string; role?: string; disabled?: boolean }): Promise<void> {
  await http.patch(`/api/admin/users/${id}`, input)
}

export async function resetAdminUserPassword(id: number): Promise<{ password: string }> {
  const { data } = await http.post(`/api/admin/users/${id}/reset-password`)
  return data
}

export async function setAdminUserPassword(id: number, newPassword: string): Promise<void> {
  await http.post(`/api/admin/users/${id}/password`, { new_password: newPassword })
}

export interface AdminStats {
  usage: { today: UsageWindow; week: UsageWindow; month: UsageWindow }
  appointments: Record<AppointmentStatus, number>
  cases: number
  users: number
  consumption?: ConsumptionStats
  usage_daily?: { date: string; calls: number; tokens_in: number; tokens_out: number; cost_usd: number }[]
  appointments_daily?: { date: string; count: number }[]
  severity?: { red: number; yellow: number; green: number; unknown: number }
  stage_funnel?: { stage: string; count: number }[]
  recent_activity?: { id: number; action: string; username: string; created_at: string | null }[]
}

export interface ConsumptionStats {
  asr_seconds_today: number
  search_calls_today: number
  cost_today_usd: number
  top_users: {
    user_id: number | null
    username: string
    asr_seconds: number
    search_calls: number
    cost_usd: number
  }[]
  limits: {
    asr_daily_seconds_per_user: number | null
    search_daily_calls_per_user: number | null
    global_daily_usd: number | null
  }
}

export interface UsageWindow {
  calls: number
  tokens_in: number
  tokens_out: number
  cost: number
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const { data } = await http.get<AdminStats>('/api/admin/stats')
  return data
}

export interface AuditLogInfo {
  id: number
  user_id: number | null
  username: string | null
  action: string
  detail: Record<string, unknown> | null
  ip: string
  created_at: string | null
}

export async function fetchAuditLogs(action: string | null, limit = 100, offset = 0): Promise<AuditLogInfo[]> {
  const { data } = await http.get<{ logs: AuditLogInfo[] }>('/api/admin/audit-logs', {
    params: { action: action || undefined, limit, offset },
  })
  return data.logs
}

export async function updatePrivacy(
  patch: { privacy_share_dialog?: boolean; privacy_share_admin?: boolean },
): Promise<void> {
  await http.patch('/api/auth/privacy', patch)
}

export interface CaseInfo {
  id: number
  session_id: number | null
  vehicle_id: number | null
  title: string
  symptoms: string
  diagnosis: string
  repair_result: string
  confirmed_by: number | null
  created_at: string | null
  vehicle?: string
  plate_no?: string
}

export async function listCases(): Promise<CaseInfo[]> {
  const { data } = await http.get<{ cases: CaseInfo[] }>('/api/cases')
  return data.cases
}

export async function createCase(sessionId: number, repairResult: string): Promise<{ id: number; kb_document_id: number; chunks: number }> {
  const { data } = await http.post('/api/cases', { session_id: sessionId, repair_result: repairResult })
  return data
}

/* ---------------- superadmin 调试后台：供应商与 Agent 运行参数在线配置 ---------------- */

/** 槽位视图：key 只回掩码，前端永远拿不到明文 */
export interface ProviderSlotView {
  base_url: string
  model: string
  has_key: boolean
  key_masked: string
}

export interface MainProviderView extends ProviderSlotView {
  aux_has_key: boolean
  aux_key_masked: string
  aux_effective: boolean
}

export interface AgentParams {
  max_tool_rounds: number
  max_ask_user: number
  force_first_round_search: boolean
  max_tokens: number
  temperature: number
  tool_result_max_chars: number
  compress_max_rounds: number
  compress_token_budget: number
  compress_min_keep_rounds: number
  summary_max_chars: number
  title_temperature: number
  title_max_tokens: number
  title_input_chars: number
  extract_temperature: number
  extract_max_tokens: number
  extract_input_chars: number
}

export interface RerankView {
  enabled: boolean
  url: string
  model: string
  score_threshold: number
  has_key: boolean
  key_masked: string
}

export type SearchProviderName = 'deepseek' | 'tavily' | 'custom'

export interface DeepSeekSearchView {
  base_url: string
  has_key: boolean
  key_masked: string
  need_content: boolean
  dynamic_language: boolean
  timeout: number
}

export interface TavilySearchView {
  has_key: boolean
  key_masked: string
  search_depth: 'basic' | 'advanced'
  max_results: number
  timeout: number
}

export interface CustomSearchView {
  base_url: string
  has_key: boolean
  key_masked: string
  timeout: number
}

export interface SearchConfigView {
  provider: SearchProviderName
  fallback_to_tavily: boolean
  fallback_on_empty: boolean
  count: number
  content_max_chars: number
  deepseek: DeepSeekSearchView
  tavily: TavilySearchView
  custom: CustomSearchView
}

export type AsrProviderName = 'deepseek' | 'openai'

export interface AsrDeepSeekView {
  base_url: string
  has_key: boolean
  key_masked: string
  timeout: number
}

export interface AsrOpenAIView extends AsrDeepSeekView {
  model: string
}

export interface AsrConfigView {
  provider: AsrProviderName
  max_seconds: number
  max_bytes: number
  deepseek: AsrDeepSeekView
  openai: AsrOpenAIView
}

/** null = 不限制（演示默认） */
export interface QuotaView {
  asr_daily_seconds_per_user: number | null
  search_daily_calls_per_user: number | null
  global_daily_usd: number | null
}

export type PasswordSource = 'env' | 'config' | 'generated'

export interface SuperadminConfig {
  providers: {
    main: MainProviderView
    embedding: ProviderSlotView
    rerank: RerankView
  }
  search: SearchConfigView
  asr: AsrConfigView
  quota: QuotaView
  agent: AgentParams
  superadmin: { password_source: PasswordSource; password_set: boolean }
  server: { host: string; port: number; version: string; restart_required_keys: string[] }
}

interface KeyPatch {
  api_key?: string
}

/** PUT 载荷：api_key 缺省/空串 = 保持原值，显式 '__clear__' = 清除 */
export interface SuperadminConfigPayload {
  providers?: {
    main?: { base_url?: string; model?: string; aux_key?: string } & KeyPatch
    embedding?: { base_url?: string; model?: string } & KeyPatch
    rerank?: {
      enabled?: boolean
      url?: string
      model?: string
      score_threshold?: number
    } & KeyPatch
  }
  search?: {
    provider?: SearchProviderName
    fallback_to_tavily?: boolean
    fallback_on_empty?: boolean
    count?: number
    content_max_chars?: number
    deepseek?: {
      base_url?: string
      need_content?: boolean
      dynamic_language?: boolean
      timeout?: number
    } & KeyPatch
    tavily?: {
      search_depth?: 'basic' | 'advanced'
      max_results?: number
      timeout?: number
    } & KeyPatch
    custom?: { base_url?: string; timeout?: number } & KeyPatch
  }
  asr?: {
    provider?: AsrProviderName
    max_seconds?: number
    max_bytes?: number
    deepseek?: { base_url?: string; timeout?: number } & KeyPatch
    openai?: { base_url?: string; model?: string; timeout?: number } & KeyPatch
  }
  quota?: Partial<QuotaView>
  agent?: Partial<AgentParams>
}

export interface SlotTestResult {
  ok: boolean
  slot: string
  provider?: string
  count?: number
  titles?: string[]
  model?: string
  reply?: string
  detail?: string
  error?: string
  latency_ms: number
}

export async function fetchSuperadminConfig(): Promise<SuperadminConfig> {
  const { data } = await http.get<SuperadminConfig>('/api/superadmin/config')
  return data
}

export async function saveSuperadminConfig(payload: SuperadminConfigPayload): Promise<{ updated: string[] }> {
  const { data } = await http.put<{ ok: boolean; updated: string[] }>('/api/superadmin/config', payload)
  return data
}

export async function testProviderSlot(
  slot: 'main' | 'aux' | 'embedding' | 'rerank' | 'search',
): Promise<SlotTestResult> {
  const { data } = await http.post<SlotTestResult>('/api/superadmin/config/test', { slot }, { timeout: 60000 })
  return data
}

export async function testSearchProvider(provider?: SearchProviderName): Promise<SlotTestResult> {
  const { data } = await http.post<SlotTestResult>(
    '/api/superadmin/test/search',
    { provider: provider ?? null },
    { timeout: 60000 },
  )
  return data
}

export async function changeSuperadminPassword(newPassword: string): Promise<{
  ok: boolean
  password_source: PasswordSource
  warning: string | null
}> {
  const { data } = await http.put<{ ok: boolean; password_source: PasswordSource; warning: string | null }>(
    '/api/superadmin/password',
    { new_password: newPassword },
  )
  return data
}

// ---------- 管理员诊断质控 ----------

export type DiagStage = 'intake' | 'hypothesis' | 'verification' | 'conclusion'

export interface DiagSessionRow {
  id: number
  title: string
  status: string
  channel: string
  owner: { id: number | null; username: string; privacy_share_admin: boolean }
  vehicle: {
    id: number
    brand: string
    model_name: string
    plate_no: string
    vin: string
    mileage: number | null
  } | null
  severity: string
  summary: string
  message_count: number
  evidence_count: number
  stage: DiagStage
  stage_inferred: boolean
  has_conclusion: boolean
  updated_at: string | null
  created_at: string | null
}

export interface DiagOverview {
  today_sessions: number
  active_sessions: number
  total_sessions: number
  conclusion_sessions: number
  conclusion_rate: number
  hypotheses_total: number
  hypotheses_linked: number
  evidence_link_rate: number
  evidence_total: number
}

export interface DiagTrace {
  id: number
  message_id: number | null
  evidence_key: string
  kind: 'kb' | 'web'
  provider: string
  rank: number
  domain: string
  doc_id: number | null
  chunk_id: number | null
  score: number
  created_at: string | null
  query?: string
  title?: string
  url?: string
  section_path?: string
  snippet?: string
}

export interface DiagMessageView {
  id: number
  role: string
  created_at: string | null
  content: string
  diag: Record<string, unknown> | null
  raw_included: boolean
}

export interface DiagDetail {
  session: {
    id: number
    title: string
    status: string
    channel: string
    vehicle_id: number | null
    case_notes: Record<string, unknown>
    created_at: string | null
    updated_at: string | null
    stage: DiagStage
    stage_history: { stage: DiagStage; at: string }[]
    stage_inferred: boolean
  }
  owner: { id: number | null; username: string; privacy_share_admin: boolean }
  vehicle: {
    id: number
    brand: string
    model_name: string
    model_year: string
    plate_no: string
    vin: string
    mileage: number | null
  } | null
  messages: DiagMessageView[]
  traces: DiagTrace[]
  evidence_map: { message_id: number; title: string; evidence: DiagTrace[]; linked: boolean }[]
  raw_included: boolean
  counts: { kb_hits: number; web_hits: number; hypotheses: number; linked_hypotheses: number }
}

export async function listDiagSessions(params: {
  q?: string
  severity?: string
  stage?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<{ total: number; items: DiagSessionRow[] }> {
  const { data } = await http.get('/api/admin/diagnosis/sessions', { params })
  return data
}

export async function fetchDiagOverview(): Promise<DiagOverview> {
  const { data } = await http.get<DiagOverview>('/api/admin/diagnosis/overview')
  return data
}

export async function fetchDiagDetail(id: number): Promise<DiagDetail> {
  const { data } = await http.get<DiagDetail>(`/api/admin/diagnosis/sessions/${id}`)
  return data
}

// ---------- DTC 故障码速查 ----------

export interface DtcEntry {
  code: string
  zh: string
  note: string
}

export interface DtcDetail {
  code: string
  zh: string
  note: string
  source_note: string
  doc_title: string
  chunks: { document: string; section_path: string; snippet: string; source_note: string }[]
  cases: {
    id: number
    title: string
    symptoms: string
    diagnosis: string
    repair_result: string
    created_at: string | null
  }[]
}

export async function searchDtc(q: string, limit = 20): Promise<DtcEntry[]> {
  const { data } = await http.get<{ results: DtcEntry[] }>('/api/dtc/search', { params: { q, limit } })
  return data.results
}

export async function fetchDtc(code: string): Promise<DtcDetail> {
  const { data } = await http.get<DtcDetail>(`/api/dtc/${encodeURIComponent(code)}`)
  return data
}
