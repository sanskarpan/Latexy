import { atom } from 'nanostores'

export interface SessionState {
  token: string | null
  userId: string | null
  email: string | null
  plan: 'free' | 'basic' | 'pro' | 'byok' | 'team' | null
  backendUrl: string
  /** Next.js app origin (Better Auth). Optional: falls back to appUrl() when app init omits it. */
  appUrl?: string
  wsUrl: string
  isAuthenticated: boolean
}

const defaultBackendUrl = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const defaultAppUrl = process.env['LATEXY_APP_URL'] ?? 'http://localhost:5180'

/** Better Auth is mounted on the Next.js app, never on the FastAPI backend, so it needs its own origin. */
export function appUrl(state: SessionState = $session.get()): string {
  return state.appUrl ?? defaultAppUrl
}

export const $session = atom<SessionState>({
  token: null,
  userId: null,
  email: null,
  plan: null,
  backendUrl: defaultBackendUrl,
  appUrl: defaultAppUrl,
  wsUrl: defaultBackendUrl.replace(/^http/, 'ws') + '/ws/jobs',
  isAuthenticated: false,
})
