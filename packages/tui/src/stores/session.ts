import { atom } from 'nanostores'

export interface SessionState {
  token: string | null
  userId: string | null
  email: string | null
  plan: 'free' | 'basic' | 'pro' | 'byok' | 'team' | null
  backendUrl: string
  wsUrl: string
  isAuthenticated: boolean
}

const defaultBackendUrl = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'

export const $session = atom<SessionState>({
  token: null,
  userId: null,
  email: null,
  plan: null,
  backendUrl: defaultBackendUrl,
  wsUrl: defaultBackendUrl.replace(/^http/, 'ws') + '/ws/jobs',
  isAuthenticated: false,
})
