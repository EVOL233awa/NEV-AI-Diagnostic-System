/**
 * 录音状态机：idle → requesting → recording → processing → idle / error。
 *
 * 只负责采音与停止后交付 Blob；转码与上传由 VoiceButton 负责。
 * 约束：非 HTTPS（localhost 除外）与不支持 MediaRecorder 的环境直接置 error；
 * 录音到上限自动停止；组件卸载时释放麦克风轨道。
 */
import { onBeforeUnmount, ref } from 'vue'

export type RecorderState = 'idle' | 'requesting' | 'recording' | 'processing' | 'error'

export interface RecordingResult {
  blob: Blob
  mimeType: string
  durationMs: number
}

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/ogg;codecs=opus',
  'audio/mp4',
  'audio/webm',
]

export function isRecordingSupported(): boolean {
  if (typeof window === 'undefined') return false
  const secure = window.isSecureContext
  const hasMedia = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  return secure && hasMedia && typeof MediaRecorder !== 'undefined'
}

function permissionMessage(error: unknown): string {
  const name = (error as DOMException | undefined)?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '麦克风权限被拒绝，请在浏览器设置中允许后重试'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return '未检测到麦克风设备'
  }
  if (name === 'NotReadableError') {
    return '麦克风被其他程序占用，请关闭后重试'
  }
  return '无法启动录音，请检查麦克风与浏览器权限'
}

export function useVoiceRecorder(options: { maxSeconds?: number } = {}) {
  const state = ref<RecorderState>('idle')
  const seconds = ref(0)
  const error = ref('')
  const autoStopped = ref(false)

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let chunks: Blob[] = []
  let startedAt = 0
  let timer: number | null = null
  let stopResolve: ((result: RecordingResult | null) => void) | null = null
  let cancelled = false

  function clearTimer(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function releaseStream(): void {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  function finishWithError(message: string): void {
    error.value = message
    state.value = 'error'
    clearTimer()
    releaseStream()
    stopResolve?.(null)
    stopResolve = null
  }

  async function start(): Promise<void> {
    if (state.value === 'recording' || state.value === 'requesting') return
    error.value = ''
    autoStopped.value = false
    if (!isRecordingSupported()) {
      finishWithError('当前环境不支持录音（需 HTTPS 且浏览器支持 MediaRecorder）')
      return
    }
    state.value = 'requesting'
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch (err) {
      finishWithError(permissionMessage(err))
      return
    }
    const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    } catch {
      finishWithError('当前浏览器不支持可用的录音格式')
      return
    }

    chunks = []
    cancelled = false
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = () => {
      clearTimer()
      releaseStream()
      const durationMs = Math.max(0, Date.now() - startedAt)
      const resolve = stopResolve
      stopResolve = null
      if (cancelled || chunks.length === 0) {
        cancelled = false
        state.value = 'idle'
        resolve?.(null)
        return
      }
      const blob = new Blob(chunks, { type: recorder?.mimeType || mimeType || 'audio/webm' })
      chunks = []
      state.value = 'idle'
      resolve?.({ blob, mimeType: blob.type, durationMs })
    }
    recorder.onerror = () => finishWithError('录音失败，请重试')

    startedAt = Date.now()
    seconds.value = 0
    recorder.start(250)
    state.value = 'recording'
    const limit = Math.max(1, options.maxSeconds ?? 120)
    timer = window.setInterval(() => {
      seconds.value = Math.min(limit, Math.floor((Date.now() - startedAt) / 1000))
      if (seconds.value >= limit) {
        autoStopped.value = true
        void stop()
      }
    }, 250)
  }

  function stop(): Promise<RecordingResult | null> {
    if (!recorder || state.value !== 'recording') return Promise.resolve(null)
    state.value = 'processing'
    return new Promise((resolve) => {
      stopResolve = resolve
      recorder?.stop()
    })
  }

  function cancel(): void {
    cancelled = true
    if (recorder && (state.value === 'recording' || state.value === 'processing')) {
      state.value = 'processing'
      recorder.stop()
      return
    }
    clearTimer()
    releaseStream()
    seconds.value = 0
    state.value = 'idle'
  }

  function reset(): void {
    if (state.value === 'error') {
      state.value = 'idle'
      error.value = ''
    }
    seconds.value = 0
    autoStopped.value = false
  }

  onBeforeUnmount(() => {
    cancel()
    clearTimer()
    releaseStream()
  })

  return {
    state,
    seconds,
    error,
    autoStopped,
    supported: isRecordingSupported(),
    start,
    stop,
    cancel,
    reset,
  }
}
