import { describe, expect, it, vi } from 'vitest'
import { gatePasskeySessionForTwoFactor, handlePasskeyTwoFactorAfterHook } from '../lib/passkey-two-factor'
import { supportsPasskeys } from '../lib/passkey-security'

describe('passkey two-factor session gate', () => {
  it('deletes the passkey session and installs only a short-lived TOTP challenge', async () => {
    const deleteSession = vi.fn(async (_token: string) => undefined)
    const createVerificationValue = vi.fn(async (_value: { identifier: string; value: string; expiresAt: Date }) => undefined)
    const setChallengeCookie = vi.fn(async () => undefined)
    const expireSessionCookie = vi.fn()
    const clearNewSession = vi.fn()
    const order: string[] = []
    const result = {
      session: { token: 'newly-issued-session-token' },
      user: { id: 'user-123', twoFactorEnabled: true },
    }

    const response = await gatePasskeySessionForTwoFactor(result, {
      deleteSession: async (token) => { order.push('delete-session'); await deleteSession(token) },
      createVerificationValue: async (value) => { order.push('create-verification'); await createVerificationValue(value) },
      setChallengeCookie,
      expireSessionCookie: () => { order.push('expire-session-cookie'); expireSessionCookie() },
      clearNewSession: () => { order.push('clear-new-session'); clearNewSession() },
      now: () => 1_000,
      createChallengeId: () => 'challenge-id',
    })

    expect(response).toEqual({ twoFactorRedirect: true, twoFactorMethods: ['totp'] })
    expect(response).not.toHaveProperty('session')
    expect(deleteSession).toHaveBeenCalledWith('newly-issued-session-token')
    expect(createVerificationValue).toHaveBeenNthCalledWith(1, {
      identifier: '2fa-challenge-id',
      value: 'user-123',
      expiresAt: new Date(601_000),
    })
    expect(createVerificationValue).toHaveBeenNthCalledWith(2, {
      identifier: '2fa-attempts-2fa-challenge-id',
      value: '0',
      expiresAt: new Date(601_000),
    })
    expect(setChallengeCookie).toHaveBeenCalledWith('two_factor', '2fa-challenge-id', 600)
    expect(expireSessionCookie).toHaveBeenCalledOnce()
    expect(clearNewSession).toHaveBeenCalledOnce()
    expect(order.slice(0, 3)).toEqual(['expire-session-cookie', 'delete-session', 'clear-new-session'])
  })

  it('keeps ordinary passkey sessions for accounts without TOTP', async () => {
    const result = {
      session: { token: 'newly-issued-session-token' },
      user: { id: 'user-123', twoFactorEnabled: false },
    }
    const deleteSession = vi.fn(async (_token: string) => undefined)
    const createVerificationValue = vi.fn(async (_value: { identifier: string; value: string; expiresAt: Date }) => undefined)
    const setChallengeCookie = vi.fn(async () => undefined)
    const expireSessionCookie = vi.fn()
    const clearNewSession = vi.fn()

    await expect(gatePasskeySessionForTwoFactor(result, {
      deleteSession,
      createVerificationValue,
      setChallengeCookie,
      expireSessionCookie,
      clearNewSession,
    })).resolves.toBe(result)
    expect(deleteSession).not.toHaveBeenCalled()
    expect(createVerificationValue).not.toHaveBeenCalled()
    expect(setChallengeCookie).not.toHaveBeenCalled()
    expect(expireSessionCookie).not.toHaveBeenCalled()
    expect(clearNewSession).not.toHaveBeenCalled()
  })
})

describe('passkey browser capability checks', () => {
  it('requires a secure origin and both WebAuthn ceremony methods', () => {
    vi.stubGlobal('window', { isSecureContext: true, PublicKeyCredential: class {} })
    vi.stubGlobal('navigator', { credentials: { create: vi.fn(), get: vi.fn() } })
    expect(supportsPasskeys()).toBe(true)

    vi.stubGlobal('window', { isSecureContext: false, PublicKeyCredential: class {} })
    expect(supportsPasskeys()).toBe(false)

    vi.stubGlobal('window', { isSecureContext: true, PublicKeyCredential: class {} })
    vi.stubGlobal('navigator', { credentials: { create: vi.fn() } })
    expect(supportsPasskeys()).toBe(false)
    vi.unstubAllGlobals()
  })
})

describe('Better Auth passkey authentication after-hook', () => {
  it('withholds a 2FA-enabled user session and returns the pending challenge response', async () => {
    const order: string[] = []
    const result = {
      session: { token: 'passkey-session-token' },
      user: { id: 'user-456', twoFactorEnabled: true },
    }
    const ctx = {
      path: '/passkey/verify-authentication',
      context: {
        returned: result as unknown,
        secret: 'server-secret',
        internalAdapter: {
          deleteSession: vi.fn(async (_token: string) => { order.push('delete-session') }),
          createVerificationValue: vi.fn(async (_value: { identifier: string; value: string; expiresAt: Date }) => { order.push('create-verification') }),
        },
        setNewSession: vi.fn((session: null) => { order.push(`new-session:${session}`) }),
        createAuthCookie: vi.fn((name: string, options: { maxAge: number }) => ({
          name: `better-auth.${name}`,
          attributes: { httpOnly: true, maxAge: options.maxAge },
        })),
      },
      setSignedCookie: vi.fn(async () => { order.push('set-challenge-cookie') }),
    }
    const expireSessionCookie = vi.fn(() => { order.push('expire-session-cookie') })

    await handlePasskeyTwoFactorAfterHook(ctx, expireSessionCookie)

    expect(expireSessionCookie).toHaveBeenCalledOnce()
    expect(ctx.context.internalAdapter.deleteSession).toHaveBeenCalledWith('passkey-session-token')
    expect(ctx.context.setNewSession).toHaveBeenCalledWith(null)
    expect(ctx.context.returned).toEqual({ twoFactorRedirect: true, twoFactorMethods: ['totp'] })
    expect(ctx.context.returned).not.toHaveProperty('session')
    expect(ctx.setSignedCookie).toHaveBeenCalledWith(
      'better-auth.two_factor', expect.stringMatching(/^2fa-/), 'server-secret',
      { httpOnly: true, maxAge: 600 },
    )
    expect(order.slice(0, 3)).toEqual(['expire-session-cookie', 'delete-session', 'new-session:null'])
  })

  it('leaves non-2FA passkey authentication responses and session issuance alone', async () => {
    const result = {
      session: { token: 'ordinary-session-token' },
      user: { id: 'user-789', twoFactorEnabled: false },
    }
    const deleteSession = vi.fn(async (_token: string) => undefined)
    const createVerificationValue = vi.fn(async (_value: { identifier: string; value: string; expiresAt: Date }) => undefined)
    const setNewSession = vi.fn()
    const setSignedCookie = vi.fn(async () => undefined)
    const expireSessionCookie = vi.fn()
    const ctx = {
      path: '/passkey/verify-authentication',
      context: {
        returned: result as unknown,
        secret: 'server-secret',
        internalAdapter: { deleteSession, createVerificationValue },
        setNewSession,
        createAuthCookie: vi.fn(),
      },
      setSignedCookie,
    }

    await handlePasskeyTwoFactorAfterHook(ctx, expireSessionCookie)

    expect(ctx.context.returned).toBe(result)
    expect(deleteSession).not.toHaveBeenCalled()
    expect(createVerificationValue).not.toHaveBeenCalled()
    expect(setNewSession).not.toHaveBeenCalled()
    expect(setSignedCookie).not.toHaveBeenCalled()
    expect(expireSessionCookie).not.toHaveBeenCalled()
  })
})
