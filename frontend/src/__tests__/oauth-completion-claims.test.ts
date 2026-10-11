import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { claimOAuthCompletion } from '../lib/oauth-completion-claims'

beforeEach(() => {
  vi.stubGlobal('window', {})
  vi.stubGlobal('document', {})
})

afterEach(() => vi.unstubAllGlobals())

describe('document-lifetime OAuth completion claims', () => {
  it('admits a provider ticket exactly once and allows a genuinely new ticket', () => {
    expect(claimOAuthCompletion('github', 'first-ticket')).toBe('claimed')
    expect(claimOAuthCompletion('github', 'first-ticket')).toBe('duplicate')
    expect(claimOAuthCompletion('github', 'new-ticket')).toBe('claimed')
    expect(claimOAuthCompletion('github', 'first-ticket')).toBe('duplicate')
  })

  it('keeps different providers independent', () => {
    for (const provider of ['github', 'zotero', 'mendeley', 'dropbox', 'google_drive'] as const) {
      expect(claimOAuthCompletion(provider, 'provider-ticket')).toBe('claimed')
      expect(claimOAuthCompletion(provider, 'provider-ticket')).toBe('duplicate')
    }
  })

  it('fails closed at capacity without ever evicting a previously admitted intent', () => {
    for (let index = 0; index < 128; index += 1) {
      expect(claimOAuthCompletion('github', `ticket-${index}`)).toBe('claimed')
    }
    expect(claimOAuthCompletion('github', 'next-ticket')).toBe('exhausted')
    expect(claimOAuthCompletion('github', 'ticket-0')).toBe('duplicate')
    expect(claimOAuthCompletion('google_drive', 'different-provider-ticket')).toBe('exhausted')
    expect(claimOAuthCompletion('github', 'ticket-127')).toBe('duplicate')
    expect(claimOAuthCompletion('github', 'next-ticket')).toBe('exhausted')
  })

  it('bounds untrusted ticket size without consuming an admission slot', () => {
    expect(claimOAuthCompletion('github', '')).toBe('unavailable')
    expect(claimOAuthCompletion('github', 'x'.repeat(4097))).toBe('unavailable')
    expect(claimOAuthCompletion('github', 'x'.repeat(4096))).toBe('claimed')
  })

  it('has no SSR claim state and requires a browser document', () => {
    const browserDocument = document
    vi.stubGlobal('window', undefined)
    expect(claimOAuthCompletion('github', 'ticket')).toBe('unavailable')
    vi.stubGlobal('window', {})
    vi.stubGlobal('document', undefined)
    expect(claimOAuthCompletion('github', 'ticket')).toBe('unavailable')
    vi.stubGlobal('document', browserDocument)
    expect(claimOAuthCompletion('github', 'ticket')).toBe('claimed')
  })

  it('starts a fresh ledger for a new browser document', () => {
    expect(claimOAuthCompletion('github', 'ticket')).toBe('claimed')
    vi.stubGlobal('document', {})
    expect(claimOAuthCompletion('github', 'ticket')).toBe('claimed')
  })

  it('does not touch durable storage, cookies, or logs', () => {
    const forbidden = () => { throw new Error('OAuth claim touched persistent storage') }
    vi.stubGlobal('window', Object.defineProperties({}, {
      localStorage: { get: forbidden },
      sessionStorage: { get: forbidden },
    }))
    vi.stubGlobal('document', Object.defineProperty({}, 'cookie', { get: forbidden, set: forbidden }))
    const log = vi.spyOn(console, 'log')
    const error = vi.spyOn(console, 'error')
    const warn = vi.spyOn(console, 'warn')
    try {
      expect(claimOAuthCompletion('github', 'ticket')).toBe('claimed')
      expect(claimOAuthCompletion('github', 'ticket')).toBe('duplicate')
      expect(log).not.toHaveBeenCalled()
      expect(error).not.toHaveBeenCalled()
      expect(warn).not.toHaveBeenCalled()
    } finally {
      log.mockRestore()
      error.mockRestore()
      warn.mockRestore()
    }
  })
})
