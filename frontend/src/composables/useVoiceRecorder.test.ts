import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVoiceRecorder } from './useVoiceRecorder'

class FakeMediaRecorder {
  static isTypeSupported = (type: string): boolean => type === 'audio/webm;codecs=opus'

  state = 'inactive'
  mimeType = 'audio/webm;codecs=opus'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(public stream: unknown, public options?: { mimeType?: string }) {
    if (options?.mimeType) this.mimeType = options.mimeType
  }

  start(): void {
    this.state = 'recording'
    this.ondataavailable?.({
      data: new Blob(['voice-bytes'], { type: this.mimeType }),
    })
  }

  stop(): void {
    this.state = 'inactive'
    queueMicrotask(() => this.onstop?.())
  }
}

let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(() => {
  getUserMedia = vi.fn().mockResolvedValue({
    getTracks: () => [{ stop: vi.fn() }],
  })
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  })
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useVoiceRecorder', () => {
  it('records and returns a blob on stop', async () => {
    const recorder = useVoiceRecorder({ maxSeconds: 30 })
    await recorder.start()
    expect(recorder.state.value).toBe('recording')
    expect(getUserMedia).toHaveBeenCalledTimes(1)

    const result = await recorder.stop()
    expect(recorder.state.value).toBe('idle')
    expect(result).not.toBeNull()
    expect(result?.mimeType).toBe('audio/webm;codecs=opus')
    expect(result?.blob.size).toBeGreaterThan(0)
  })

  it('reports permission denial', async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'))
    const recorder = useVoiceRecorder()
    await recorder.start()
    expect(recorder.state.value).toBe('error')
    expect(recorder.error.value).toContain('权限被拒绝')
  })

  it('reports missing device', async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException('missing', 'NotFoundError'))
    const recorder = useVoiceRecorder()
    await recorder.start()
    expect(recorder.state.value).toBe('error')
    expect(recorder.error.value).toContain('未检测到麦克风')
  })

  it('refuses to start without a secure context', async () => {
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false })
    const recorder = useVoiceRecorder()
    await recorder.start()
    expect(recorder.state.value).toBe('error')
    expect(recorder.error.value).toContain('HTTPS')
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('auto-stops at the max duration', async () => {
    vi.useFakeTimers()
    const recorder = useVoiceRecorder({ maxSeconds: 1 })
    await recorder.start()
    expect(recorder.state.value).toBe('recording')

    await vi.advanceTimersByTimeAsync(1100)
    expect(recorder.autoStopped.value).toBe(true)
    expect(recorder.state.value).toBe('idle')
  })

  it('cancel discards the recording', async () => {
    const recorder = useVoiceRecorder()
    await recorder.start()
    recorder.cancel()
    await Promise.resolve()
    await Promise.resolve()
    expect(recorder.state.value).toBe('idle')
    expect(recorder.seconds.value).toBe(0)
  })
})
