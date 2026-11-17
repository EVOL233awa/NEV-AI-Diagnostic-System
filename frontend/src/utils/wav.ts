/**
 * 浏览器录音 → 16kHz 单声道 PCM16 WAV。
 *
 * DeepSeek ASR 只接受 16-bit PCM WAV 或 Ogg Opus；Chrome/Edge/Firefox 录出的
 * webm/ogg 需要转码，Safari 的 audio/mp4 同样走解码 + 重采样。纯函数便于单测。
 */

export const TARGET_SAMPLE_RATE = 16000

/** 多声道降为单声道（取各声道平均；人声场景比只取左声道更稳）。 */
export function mixToMono(buffer: AudioBuffer): Float32Array {
  const channels = buffer.numberOfChannels
  if (channels === 1) {
    return new Float32Array(buffer.getChannelData(0))
  }
  const length = buffer.length
  const mixed = new Float32Array(length)
  for (let ch = 0; ch < channels; ch += 1) {
    const data = buffer.getChannelData(ch)
    for (let i = 0; i < length; i += 1) mixed[i] += data[i]
  }
  for (let i = 0; i < length; i += 1) mixed[i] /= channels
  return mixed
}

/** 线性插值重采样（语音 16kHz 足够；不做抗混叠滤波，避免引入额外依赖）。 */
export function resampleLinear(
  samples: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (sourceRate === targetRate || samples.length === 0) {
    return new Float32Array(samples)
  }
  const ratio = sourceRate / targetRate
  const length = Math.max(1, Math.round(samples.length / ratio))
  const out = new Float32Array(length)
  const last = samples.length - 1
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio
    const low = Math.floor(position)
    const high = Math.min(low + 1, last)
    const fraction = position - low
    out[i] = samples[low] * (1 - fraction) + samples[high] * fraction
  }
  return out
}

/** Float32 [-1,1] → 44 字节头 + PCM16 的 WAV Blob。 */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const bytesPerSample = 2
  const dataSize = samples.length * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)

  const writeAscii = (offset: number, value: string): void => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i))
  }

  writeAscii(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeAscii(8, 'WAVE')
  writeAscii(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 块长度
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * bytesPerSample, true) // byte rate
  view.setUint16(32, bytesPerSample, true) // block align
  view.setUint16(34, 16, true) // 位深
  writeAscii(36, 'data')
  view.setUint32(40, dataSize, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += bytesPerSample
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

/** AudioBuffer → 16kHz 单声道 WAV（先混单声道，再重采样）。 */
export function audioBufferToWav(buffer: AudioBuffer, targetRate = TARGET_SAMPLE_RATE): Blob {
  const mono = mixToMono(buffer)
  const resampled = resampleLinear(mono, buffer.sampleRate, targetRate)
  return encodeWav(resampled, targetRate)
}
