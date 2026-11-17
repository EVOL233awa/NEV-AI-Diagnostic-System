<script setup lang="ts">
/**
 * 语音输入按钮：点击开始 / 再点结束 → 转写并回填输入框（不自动发送）。
 *
 * - 首次使用前展示一次隐私告知（localStorage 记住），符合“请求强权限前先解释”的隐私原则。
 * - Ogg Opus 直传；其余格式在浏览器侧解码为 16kHz 单声道 WAV；解码失败时
 *   OpenAI 兼容 provider 可直传原始格式，DeepSeek 则提示改用文字输入。
 * - 原生 <button> + aria-pressed + aria-live 计时，44px 触摸目标，尊重 reduced-motion。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { transcribeAudio } from '../api/client'
import { audioBufferToWav } from '../utils/wav'
import { useVoiceRecorder, type RecordingResult } from '../composables/useVoiceRecorder'

const props = withDefaults(defineProps<{
  disabled?: boolean
  maxSeconds?: number
  provider?: 'deepseek' | 'openai'
}>(), {
  disabled: false,
  maxSeconds: 120,
  provider: 'deepseek',
})

const emit = defineEmits<{
  (e: 'transcribed', text: string): void
  (e: 'error', message: string): void
}>()

const PRIVACY_KEY = 'nev2_voice_privacy_ack'

const recorder = useVoiceRecorder({ maxSeconds: props.maxSeconds })
const { state, seconds, error, autoStopped, supported } = recorder

const privacyAck = ref(localStorage.getItem(PRIVACY_KEY) === '1')
const privacyOpen = ref(false)
const uploading = ref(false)

const busy = computed(() => uploading.value || state.value === 'requesting' || state.value === 'processing')
const buttonDisabled = computed(() => props.disabled || busy.value)
const recording = computed(() => state.value === 'recording')

const timeText = computed(() => {
  const total = seconds.value
  const minutes = Math.floor(total / 60).toString().padStart(2, '0')
  const rest = (total % 60).toString().padStart(2, '0')
  return `${minutes}:${rest}`
})

const buttonLabel = computed(() => {
  if (uploading.value) return '正在识别语音'
  if (state.value === 'requesting') return '正在请求麦克风权限'
  if (state.value === 'processing') return '正在结束录音'
  if (recording.value) return `结束录音（已录 ${timeText.value}）`
  return '语音转文字'
})

function report(message: string): void {
  emit('error', message)
}

async function startRecording(): Promise<void> {
  // 移动端先收起键盘，避免录音条被软键盘顶起
  const active = document.activeElement
  if (active instanceof HTMLElement) active.blur()
  await recorder.start()
  if (state.value === 'error') report(error.value)
}

function confirmPrivacy(): void {
  localStorage.setItem(PRIVACY_KEY, '1')
  privacyAck.value = true
  privacyOpen.value = false
  void startRecording()
}

function extensionFor(mimeType: string): string {
  if (mimeType.includes('mp4')) return 'm4a'
  if (mimeType.includes('ogg')) return 'ogg'
  return 'webm'
}

async function prepareUpload(result: RecordingResult): Promise<{ blob: Blob; filename: string }> {
  if (result.mimeType.includes('ogg')) {
    return { blob: result.blob, filename: 'voice.ogg' }
  }
  try {
    const arrayBuffer = await result.blob.arrayBuffer()
    const context = new AudioContext()
    try {
      await context.resume().catch(() => undefined)
      const decoded = await context.decodeAudioData(arrayBuffer.slice(0))
      return { blob: audioBufferToWav(decoded), filename: 'voice.wav' }
    } finally {
      void context.close().catch(() => undefined)
    }
  } catch {
    if (props.provider === 'openai') {
      return { blob: result.blob, filename: `voice.${extensionFor(result.mimeType)}` }
    }
    throw new Error('当前浏览器录音格式不支持，请换 Chrome/Edge 或改用文字输入')
  }
}

function uploadErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
  if (detail) return detail
  if (err instanceof Error && err.message) return err.message
  return '语音识别失败，请重试或改用文字输入'
}

async function finishRecording(): Promise<void> {
  const result = await recorder.stop()
  if (!result) return
  if (autoStopped.value) ElMessage.info('已达单次录音上限，可再录一段继续补充')
  if (result.blob.size === 0) {
    report('没有录到声音，请重试')
    recorder.reset()
    return
  }
  uploading.value = true
  try {
    const upload = await prepareUpload(result)
    const response = await transcribeAudio(upload.blob, upload.filename, result.durationMs)
    const text = response.text.trim()
    if (!text) {
      report('未识别到语音内容，请重试或改用文字输入')
    } else {
      emit('transcribed', text)
    }
  } catch (err) {
    report(uploadErrorMessage(err))
  } finally {
    uploading.value = false
    recorder.reset()
  }
}

async function onClick(): Promise<void> {
  if (buttonDisabled.value) return
  if (recording.value) {
    await finishRecording()
    return
  }
  if (!supported) {
    report('语音需要 HTTPS 且浏览器支持录音（Chrome/Edge/Safari 15+）')
    return
  }
  if (!privacyAck.value) {
    privacyOpen.value = true
    return
  }
  await startRecording()
}
</script>

<template>
  <div class="voice-wrap">
    <button
      type="button"
      class="voice-btn"
      :class="{ recording, processing: uploading || state === 'processing' }"
      :disabled="buttonDisabled"
      :aria-pressed="recording"
      :aria-label="buttonLabel"
      @click="onClick"
    >
      <svg v-if="!recording && !uploading" aria-hidden="true" viewBox="0 0 24 24" class="icon">
        <path
          d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z"
          fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"
        />
        <path
          d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"
          fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
        />
      </svg>
      <svg v-else-if="recording" aria-hidden="true" viewBox="0 0 24 24" class="icon">
        <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
      </svg>
      <span v-else class="spinner" aria-hidden="true" />
    </button>
    <span v-if="recording" class="voice-timer" aria-live="polite">{{ timeText }}</span>
    <span v-else-if="uploading" class="voice-hint" aria-live="polite">识别中…</span>

    <el-dialog
      v-model="privacyOpen"
      title="语音输入隐私说明"
      width="min(92vw, 420px)"
      append-to-body
    >
      <p class="privacy-text">
        录音只在点击开始到结束期间进行；音频会发送到语音识别服务用于转写，系统不保存音频与转写文本；车内有乘客时请注意。
      </p>
      <template #footer>
        <el-button @click="privacyOpen = false">取消</el-button>
        <el-button type="primary" @click="confirmPrivacy">同意并开始录音</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.voice-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.voice-btn {
  min-width: 44px;
  min-height: 44px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--line, #2a3a3a);
  background: var(--panel, #0f1a18);
  color: var(--text, #e6f2ee);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.voice-btn:hover:not(:disabled) {
  border-color: var(--accent, #2dd4a8);
}

.voice-btn:focus-visible {
  outline: 2px solid var(--accent, #2dd4a8);
  outline-offset: 2px;
}

.voice-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.voice-btn.recording {
  background: #d94a5b;
  border-color: #ff7a88;
  color: #fff;
  animation: voice-pulse 1.2s ease-in-out infinite;
}

.voice-btn.processing {
  border-color: var(--accent, #2dd4a8);
}

.icon {
  width: 20px;
  height: 20px;
}

.spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid currentColor;
  border-top-color: transparent;
  animation: voice-spin 0.8s linear infinite;
}

.voice-timer {
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  color: var(--muted, #8aa3a0);
}

.voice-hint {
  font-size: 0.72rem;
  color: var(--muted, #8aa3a0);
}

.privacy-text {
  margin: 0;
  line-height: 1.7;
  font-size: 0.86rem;
}

@keyframes voice-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(217, 74, 91, 0.55); }
  50% { box-shadow: 0 0 0 8px rgba(217, 74, 91, 0); }
}

@keyframes voice-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .voice-btn.recording { animation: none; }
  .spinner { animation-duration: 1.6s; }
}
</style>
