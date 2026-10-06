import { afterEach, describe, expect, test, vi } from 'vitest'

import { shouldBypassPortfolioResolution } from '../middleware'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('custom-domain middleware routing', () => {
  test('never resolves API or public portfolio paths as custom domains', () => {
    expect(shouldBypassPortfolioResolution('portfolio.example', '/api/auth/get-session')).toBe(true)
    expect(shouldBypassPortfolioResolution('portfolio.example', '/api')).toBe(true)
    expect(shouldBypassPortfolioResolution('portfolio.example', '/u/alice')).toBe(true)
  })

  test('recognizes configured app hosts without a source-code allowlist edit', () => {
    vi.stubEnv('NEXT_PUBLIC_APP_URL', 'https://preview.internal.example')

    expect(shouldBypassPortfolioResolution('preview.internal.example', '/workspace')).toBe(true)
  })

  test('retains custom portfolio host resolution for ordinary pages', () => {
    expect(shouldBypassPortfolioResolution('cv.alice.example', '/')).toBe(false)
  })
})
