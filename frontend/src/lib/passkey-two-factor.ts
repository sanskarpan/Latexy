type PasskeySessionResult = {
  session?: { token?: string }
  user?: { id?: string; twoFactorEnabled?: boolean }
}

export type PasskeyTwoFactorDependencies = {
  deleteSession: (token: string) => Promise<void>
  createVerificationValue: (value: { identifier: string; value: string; expiresAt: Date }) => Promise<void>
  setChallengeCookie: (name: string, value: string, maxAge: number) => Promise<void>
  expireSessionCookie: () => void
  clearNewSession: () => void
  now?: () => number
  createChallengeId?: () => string
}

type PasskeyAuthAfterContext = {
  path?: string
  context: {
    returned?: unknown
    secret: string
    internalAdapter: {
      deleteSession: (token: string) => Promise<unknown>
      createVerificationValue: (value: { identifier: string; value: string; expiresAt: Date }) => Promise<unknown>
    }
    setNewSession: (session: null) => void
    createAuthCookie: (name: string, options: { maxAge: number }) => { name: string; attributes: Record<string, unknown> }
  }
  setSignedCookie: (name: string, value: string, secret: string, attributes: Record<string, unknown>) => Promise<unknown>
}

/** Apply the gate to Better Auth's completed passkey authentication response. */
export async function handlePasskeyTwoFactorAfterHook(
  ctx: PasskeyAuthAfterContext,
  expireSessionCookie: () => void,
): Promise<void> {
  if (ctx.path !== '/passkey/verify-authentication') return
  const result = ctx.context.returned as PasskeySessionResult | undefined
  if (!result) return
  const gatedResult = await gatePasskeySessionForTwoFactor(result, {
    deleteSession: async (token) => { await ctx.context.internalAdapter.deleteSession(token) },
    createVerificationValue: async (value) => { await ctx.context.internalAdapter.createVerificationValue(value) },
    setChallengeCookie: async (name, value, maxAge) => {
      const cookie = ctx.context.createAuthCookie(name, { maxAge })
      await ctx.setSignedCookie(cookie.name, value, ctx.context.secret, cookie.attributes)
    },
    expireSessionCookie,
    clearNewSession: () => ctx.context.setNewSession(null),
  })
  if (gatedResult !== result) ctx.context.returned = gatedResult
}

/**
 * Replace a passkey-created full session with Better Auth's pending 2FA state.
 * Better Auth's two-factor plugin currently hooks password sign-in only, so
 * passkey sign-in needs to explicitly withhold the session when TOTP is on.
 */
export async function gatePasskeySessionForTwoFactor<T extends PasskeySessionResult>(
  result: T,
  dependencies: PasskeyTwoFactorDependencies,
): Promise<T | { twoFactorRedirect: true; twoFactorMethods: string[] }> {
  const sessionToken = result.session?.token
  const userId = result.user?.id
  if (!sessionToken || !userId || result.user?.twoFactorEnabled !== true) return result

  const maxAge = 10 * 60
  const challengeId = `2fa-${(dependencies.createChallengeId || (() => crypto.randomUUID()))()}`
  const expiresAt = new Date((dependencies.now || Date.now)() + maxAge * 1000)
  // Remove the provisional session from the response before any remaining
  // storage work can fail; then revoke it and clear Better Auth's hook state.
  dependencies.expireSessionCookie()
  await dependencies.deleteSession(sessionToken)
  dependencies.clearNewSession()
  await dependencies.createVerificationValue({ identifier: challengeId, value: userId, expiresAt })
  await dependencies.createVerificationValue({ identifier: `2fa-attempts-${challengeId}`, value: '0', expiresAt })
  await dependencies.setChallengeCookie('two_factor', challengeId, maxAge)
  return { twoFactorRedirect: true, twoFactorMethods: ['totp'] }
}
