import { describe, it, expect, afterEach } from 'vitest'
import { $session, appUrl } from '../stores/session.js'

const initial = $session.get()

describe('session appUrl', () => {
  afterEach(() => {
    $session.set(initial)
  })

  it('defaults to the Next.js app origin, not the FastAPI backend', () => {
    const state = $session.get()
    expect(state.backendUrl).toBe(
      'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run',
    )
    expect(state.wsUrl).toBe(
      'wss://sanskarpandey2004--latexy-backend-fastapi-app.modal.run/ws/jobs',
    )
    expect(appUrl(state)).toBe('https://latexy.xyz')
  })

  it('falls back to the default when app init omits appUrl', () => {
    const { appUrl: _omitted, ...rest } = $session.get()
    expect(appUrl(rest)).toBe('https://latexy.xyz')
  })

  it('returns the appUrl held in the store — the no-arg form LoginOverlay uses', () => {
    $session.set({ ...$session.get(), appUrl: 'https://latexy.example.com' })
    expect(appUrl()).toBe('https://latexy.example.com')
    expect(appUrl($session.get()) + '/api/auth/sign-in/email')
      .toBe('https://latexy.example.com/api/auth/sign-in/email')
  })
})
