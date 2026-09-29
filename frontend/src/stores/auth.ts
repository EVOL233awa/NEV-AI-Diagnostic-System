import { reactive } from 'vue'
import { clearToken, saveToken, type AuthUser } from '../api/client'

const USER_KEY = 'nev2_user'

function loadUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export const auth = reactive({
  token: localStorage.getItem('nev2_token') ?? '',
  user: loadUser(),
})

export const ROLE_LABELS: Record<AuthUser['role'], string> = {
  owner: '车主',
  staff: '店员',
  admin: '管理员',
  superadmin: '超级管理员',
}

export function setAuth(token: string, user: AuthUser): void {
  auth.token = token
  auth.user = user
  saveToken(token, user)
}

export function logout(): void {
  auth.token = ''
  auth.user = null
  clearToken()
}
