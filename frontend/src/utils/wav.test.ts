import { describe, expect, it } from 'vitest'
import { audioBufferToWav, encodeWav, mixToMono, resampleLinear, TARGET_SAMPLE_RATE } from './wav'

/** jsdom 的 Blob 没有 arrayBuffer()，用 FileReader 读取（浏览器与测试环境通用）。 */
function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(reader.error)
    reader.readAsArrayBuffer(blob)
  })
}

function readAscii(view: DataView, offset: number, length: number): string {
  let text = ''
  for (let i = 0; i < length; i += 1) text += String.fromCharCode(view.getUint8(offset + i))
  return text
}

/** 只实现 wav.ts 用到的 AudioBuffer 接口，避免测试依赖真实 WebAudio。 */
function fakeAudioBuffer(channels: Float32Array[], sampleRate: number): AudioBuffer {
  return {
    numberOfChannels: channels.length,
    length: channels[0].length,
    sampleRate,
    getChannelData: (index: number) => channels[index],
  } as unknown as AudioBuffer
}

describe('wav utils', () => {
  it('encodes a valid mono PCM16 WAV header', async () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
    const blob = encodeWav(samples, 16000)
    expect(blob.type).toBe('audio/wav')
    const view = new DataView(await blobToArrayBuffer(blob))
    expect(readAscii(view, 0, 4)).toBe('RIFF')
    expect(readAscii(view, 8, 4)).toBe('WAVE')
    expect(readAscii(view, 12, 4)).toBe('fmt ')
    expect(view.getUint16(20, true)).toBe(1) // PCM
    expect(view.getUint16(22, true)).toBe(1) // mono
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(readAscii(view, 36, 4)).toBe('data')
    expect(view.getUint32(40, true)).toBe(samples.length * 2)
    expect(blob.size).toBe(44 + samples.length * 2)
    // 末尾样本 -1 应映射为 -32768
    expect(view.getInt16(44 + (samples.length - 1) * 2, true)).toBe(-32768)
  })

  it('mixes multiple channels to mono by averaging', () => {
    const buffer = fakeAudioBuffer([
      new Float32Array([1, 0, -1]),
      new Float32Array([0, 1, 1]),
    ], 48000)
    expect(Array.from(mixToMono(buffer))).toEqual([0.5, 0.5, 0])
  })

  it('downsamples length and interpolates linearly', () => {
    const input = new Float32Array([0, 1, 0, 1])
    const out = resampleLinear(input, 32000, 16000)
    expect(out.length).toBe(2)
    expect(out[0]).toBeCloseTo(0)
    expect(out[1]).toBeCloseTo(0)
  })

  it('keeps sample rate unchanged when target matches', () => {
    const input = new Float32Array([0.1, 0.2])
    const out = resampleLinear(input, 16000, 16000)
    expect(out.length).toBe(2)
    expect(out[0]).toBeCloseTo(0.1)
    expect(out[1]).toBeCloseTo(0.2)
  })

  it('produces a 16kHz WAV from an AudioBuffer', async () => {
    const buffer = fakeAudioBuffer([new Float32Array(4800).fill(0.25)], 48000)
    const blob = audioBufferToWav(buffer)
    const view = new DataView(await blobToArrayBuffer(blob))
    expect(view.getUint32(24, true)).toBe(TARGET_SAMPLE_RATE)
    expect(view.getUint16(22, true)).toBe(1)
    // 4800 samples @48k → 1600 samples @16k
    expect(view.getUint32(40, true)).toBe(1600 * 2)
  })
})
