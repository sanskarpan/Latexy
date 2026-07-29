import { describe, it, expect, afterEach } from 'vitest'
import { $session, appUrl } from '../stores/session.js'

const initial = $session.get()

describe('session appUrl', () => {
  afterEach(() => {
    $session.set(initial)
  })

  it('defaults to the Next.js app origin, not the FastAPI backend', () => {
    const state = $session.get()
    expect(state.backendUrl).toBe('http://localhost:8030')
    expect(appUrl(state)).toBe('http://localhost:5180')
  })

  it('falls back to the default when app init omits appUrl', () => {
    const { appUrl: _omitted, ...rest } = $session.get()
    expect(appUrl(rest)).toBe('http://localhost:5180')
  })

  it('returns the appUrl held in the store — the no-arg form LoginOverlay uses', () => {
    $session.set({ ...$session.get(), appUrl: 'https://latexy.example.com' })
    expect(appUrl()).toBe('https://latexy.example.com')
    expect(appUrl($session.get()) + '/api/auth/sign-in/email')
      .toBe('https://latexy.example.com/api/auth/sign-in/email')
  })
})
