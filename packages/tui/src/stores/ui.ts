import { atom } from 'nanostores'

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'

export interface UIState {
  theme: 'dark' | 'light'
  healthStatus: HealthStatus
  wsConnected: boolean
  notifications: Array<{ id: string; message: string; level: 'info' | 'error' }>
}

export const $ui = atom<UIState>({
  theme: 'dark',
  healthStatus: 'unknown',
  wsConnected: false,
  notifications: [],
})
