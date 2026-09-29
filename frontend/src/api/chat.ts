/**
 * 诊断会话 API + SSE 流式解析。
 * send/answers 走 fetch POST + ReadableStream（axios 不便处理流），其余走 http 实例。
 */
import { TOKEN_KEY, getApiBase, http } from './client'

export interface SessionInfo {
  id: number
  title: string
  status: string
  has_pending: boolean
}

export interface DiagHypothesis {
  title: string
}

export interface DiagResult {
  severity: 'green' | 'yellow' | 'red'
  summary: string
  hypotheses: DiagHypothesis[]
  steps: string[]
  pending_checks: string[]
}

export interface PendingQuestion {
  id: string
  question: string
  options: string[]
  allow_free?: boolean
}

/** 历史回放里的工具轨迹（后端由 tool_calls + tool 结果行拼装） */
export interface HistoryToolTrace {
  name: string
  arguments: string
  result: string | null
}

export interface HistoryMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  diag: DiagResult | null
  tools?: HistoryToolTrace[]
}

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

export async function listSessions(): Promise<SessionInfo[]> {
  const { data } = await http.get<{ sessions: SessionInfo[] }>('/api/chat/sessions')
  return data.sessions
}

export async function createSession(title: string): Promise<{ id: number; title: string }> {
  const { data } = await http.post<{ id: number; title: string }>('/api/chat/sessions', { title })
  return data
}

export async function listMessages(
  sessionId: number,
): Promise<{ messages: HistoryMessage[]; pending_questions: PendingQuestion[] | null }> {
  const { data } = await http.get<{
    messages: HistoryMessage[]
    pending_questions: PendingQuestion[] | null
  }>(`/api/chat/sessions/${sessionId}/messages`)
  return data
}

/** POST 并逐块解析 SSE（event/data 按 \n\n 分帧），逐事件回调。
 * 空闲超时：超过 idleTimeoutMs 没有任何字节（网络断流/服务卡死）主动中断并抛错。 */
export async function streamChat(
  path: string,
  body: Record<string, unknown>,
  onEvent: (ev: SseEvent) => void,
  idleTimeoutMs = 120000,
): Promise<void> {
  const controller = new AbortController()
  let idleTimer = setTimeout(() => controller.abort(), idleTimeoutMs)
  const resetIdle = () => {
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => controller.abort(), idleTimeoutMs)
  }

  let resp: Response
  try {
    resp = await fetch(`${getApiBase()}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ''}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(idleTimer)
    throw err instanceof DOMException && err.name === 'AbortError'
      ? new Error('连接超时，请重试')
      : err
  }
  if (!resp.ok || !resp.body) {
    clearTimeout(idleTimer)
    let detail = `HTTP ${resp.status}`
    try {
      const err = (await resp.json()) as { detail?: string }
      if (err.detail) detail = String(err.detail)
    } catch {
      // 保留默认错误信息
    }
    throw new Error(detail)
  }

  try {
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      resetIdle()
      buf += decoder.decode(value, { stream: true })
      let idx = buf.indexOf('\n\n')
      while (idx >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        let event = 'message'
        let data = ''
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5)
        }
        if (data) {
          try {
            onEvent({ event, data: JSON.parse(data) as Record<string, unknown> })
          } catch {
            // 单帧坏数据跳过，不中断整流
          }
        }
        idx = buf.indexOf('\n\n')
      }
    }
  } catch (err) {
    throw err instanceof DOMException && err.name === 'AbortError'
      ? new Error('连接超时（长时间无响应），请重试')
      : err
  } finally {
    clearTimeout(idleTimer)
  }
}
