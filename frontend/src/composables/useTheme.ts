import { computed, ref } from 'vue'
import { updatePreferences } from '../api/client'
import { auth, patchStoredUser } from '../stores/auth'

export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'nev2_theme'
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null
const systemDark = ref(media?.matches ?? false)

function normalize(value: string | null | undefined): ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

function storedTheme(): ThemeMode {
  return normalize(localStorage.getItem(STORAGE_KEY) ?? auth.user?.theme)
}

const theme = ref<ThemeMode>(storedTheme())
const resolved = computed<'light' | 'dark'>(() =>
  theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value,
)

function apply(): void {
  const root = document.documentElement
  root.classList.toggle('dark', resolved.value === 'dark')
  root.classList.toggle('light', resolved.value === 'light')
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', resolved.value === 'dark' ? '#080d10' : '#f4f7f8')
}

/** 启动时应用本地偏好；跟随系统时监听系统外观变化。 */
export function initTheme(): void {
  apply()
  media?.addEventListener('change', (event) => {
    systemDark.value = event.matches
    if (theme.value === 'system') apply()
  })
}

/** 登录成功、拿到服务端用户偏好后同步视觉（不回写接口）。 */
export function applyUserTheme(preference: string | null | undefined): void {
  theme.value = normalize(preference)
  localStorage.setItem(STORAGE_KEY, theme.value)
  apply()
}

/** 用户主动切换：先本地生效，再写服务端偏好；接口失败不回滚视觉状态。 */
export async function setTheme(mode: ThemeMode): Promise<void> {
  applyUserTheme(mode)
  if (!auth.token) return
  try {
    await updatePreferences(mode)
    patchStoredUser({ theme: mode })
  } catch {
    // 偏好同步失败不阻塞使用；下次登录会以服务端旧值为准
  }
}

export function useTheme() {
  return {
    theme,
    resolved,
    isSystem: computed(() => theme.value === 'system'),
    setTheme,
  }
}
