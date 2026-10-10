import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }
const providers = ['github', 'zotero', 'mendeley', 'dropbox', 'google_drive'] as const
type Provider = typeof providers[number]

function providerPath(provider: Provider) {
  return provider === 'google_drive' ? 'google-drive' : provider
}

function textContent(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  if (node && typeof node === 'object' && 'props' in node) return textContent((node as VNode).props.children)
  return ''
}

async function settle() {
  for (let index = 0; index < 24; index += 1) await Promise.resolve()
}

function hasConnectingButton(node: unknown): boolean {
  if (Array.isArray(node)) return node.some(hasConnectingButton)
  if (!node || typeof node !== 'object' || !('props' in node)) return false
  const vnode = node as VNode
  const children = vnode.props.children
  if (vnode.type === 'button' && Array.isArray(children)
    && children.some((child) => child === 'Authorizing…' || child === 'Connecting…')) return true
  return hasConnectingButton(children)
}

afterEach(() => {
  vi.doUnmock('@/contexts/EntitlementsContext')
  vi.unstubAllGlobals()
  vi.doUnmock('react')
  vi.doUnmock('react/jsx-runtime')
  vi.doUnmock('next/navigation')
  vi.doUnmock('@/hooks/useRequireAuth')
  vi.doUnmock('@/components/onboarding/OnboardingFlow')
  vi.doUnmock('@/hooks/usePushNotifications')
  vi.doUnmock('@/lib/oauth-navigation')
  vi.doUnmock('@/components/PersonalDictionarySettings')
  vi.doUnmock('@/components/auth/SecuritySettings')
  vi.doUnmock('@/components/ReferralPanel')
  vi.doUnmock('@/components/icons/brand-icons')
  vi.doUnmock('lucide-react')
  vi.doUnmock('@/lib/api-client')
  vi.resetModules()
})

describe('Settings OAuth completion captured account context', () => {
  async function loadRealSettingsWithApiToken(apiToken: string | null, options: {
    sessionError?: Error
    holdCompletion?: boolean
    provider?: Provider
    featureEnabled?: boolean
    returnTo?: string
  } = {}) {
    vi.resetModules()
    let session = { user: { id: 'owner-b' }, session: { token: 'token-b' } }
    let queryActive = true
    let ticketValue = 'ticket-b'
    let sessionPending = false
    let sessionError = options.sessionError ?? null
    let featureEnabled = options.featureEnabled ?? true
    const provider = options.provider ?? 'github'
    let hookIndex = 0
    let refs: Array<{ current: unknown }> = []
    let states: unknown[] = []
    const effects: Array<() => void | (() => void)> = []
    const requests: Array<{ url: string; init: RequestInit }> = []
    const replace = vi.fn()
    let releaseCompletion!: () => void
    const completionGate = new Promise<void>((resolve) => { releaseCompletion = resolve })

    vi.stubGlobal('window', { opener: null, location: { origin: 'http://localhost:3000' } })
    vi.stubGlobal('confirm', () => true)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      requests.push({ url, init })
      if (options.holdCompletion && url.endsWith('/complete')) await completionGate
      const body = url.endsWith('/complete')
        ? { success: true, message: 'ok' }
        : url.endsWith('/github/status')
          ? { connected: true, username: 'alice', public_import: true, private_sync: false }
          : url.endsWith('/settings/notifications')
            ? { job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true }
            : url.includes('/zotero/status')
              ? { connected: false, username: null, user_id: null }
              : url.includes('/mendeley/status')
                ? { connected: false, name: null }
                : url.includes('/dropbox/status')
                  ? { connected: false, display_name: null, account_id: null }
                  : { connected: false, scope: null }
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      } as unknown as Response
    }))
    vi.stubGlobal('document', { cookie: '' })

    vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: () => featureEnabled }) }))
    vi.doMock('react', () => ({
      Suspense: 'Suspense',
      useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
      useRef: (initial: unknown) => {
        const index = hookIndex++
        refs[index] ??= { current: initial }
        return refs[index]
      },
      useState: (initial: unknown) => {
        const index = hookIndex++
        // Each mount owns its setters. A held promise from an unmounted owner
        // must not accidentally write into the replacement harness instance.
        const mountedStates = states
        if (!(index in mountedStates)) mountedStates[index] = initial
        return [mountedStates[index], (value: unknown) => {
          mountedStates[index] = typeof value === 'function'
            ? (value as (previous: unknown) => unknown)(mountedStates[index])
            : value
        }]
      },
    }))
    vi.doMock('react/jsx-runtime', () => ({
      jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
      jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    }))
    vi.doMock('next/navigation', () => ({
      useSearchParams: () => ({
        get: (key: string) => !queryActive
          ? null
          : key === provider ? 'complete'
            : key === 'ticket' ? ticketValue
              : key === 'return_to' ? options.returnTo ?? null : null,
      }),
      useRouter: () => ({ replace, push: vi.fn() }),
      usePathname: () => '/settings',
    }))
    vi.doMock('@/hooks/useRequireAuth', () => ({
      useRequireAuth: () => ({
        session,
        isPending: sessionPending,
        error: sessionError,
      }),
    }))
    vi.doMock('@/components/onboarding/OnboardingFlow', () => ({ useOnboarding: () => ({ resetOnboarding: vi.fn() }) }))
    vi.doMock('@/hooks/usePushNotifications', () => ({ getNotificationPref: () => true, setNotificationPref: vi.fn() }))
    vi.doMock('@/lib/oauth-navigation', () => ({ safeOAuthAuthorizationUrl: vi.fn(() => null) }))
    vi.doMock('@/components/PersonalDictionarySettings', () => ({ default: 'PersonalDictionarySettings' }))
    vi.doMock('@/components/auth/SecuritySettings', () => ({ default: 'SecuritySettings' }))
    vi.doMock('@/components/ReferralPanel', () => ({ default: 'ReferralPanel' }))
    vi.doMock('@/components/icons/brand-icons', () => ({ Github: 'Github' }))
    vi.doMock('lucide-react', () => Object.fromEntries([
      'Bell', 'BookOpen', 'Mail', 'Calendar', 'Loader2', 'CheckCircle', 'Monitor', 'Unlink', 'ExternalLink',
      'Cloud', 'LogIn', 'CircleAlert', 'Eye',
    ].map((name) => [name, name])))

    const { apiClient } = await import('../lib/api-client')
    if (apiToken) apiClient.setAuthToken(apiToken)
    const page = (await import('../app/settings/page')).default() as VNode
    const content = page.props.children as VNode
    const cleanups: Array<() => void> = []
    const render = () => {
      hookIndex = 0
      effects.length = 0
      return (content.type as () => VNode)()
    }
    const runEffects = () => {
      while (effects.length) {
        const cleanup = effects.shift()?.()
        if (cleanup) cleanups.push(cleanup)
      }
    }
    const cleanup = () => { while (cleanups.length) cleanups.pop()?.() }
    const remount = () => {
      cleanup()
      refs = []
      states = []
      render()
      runEffects()
    }
    render()
    runEffects()
    await settle()
    return {
      requests,
      replace,
      apiClient,
      render,
      runEffects,
      remount,
      setSession: (next: typeof session) => { session = next },
      setAuthState: (pending: boolean, error: Error | null = null) => { sessionPending = pending; sessionError = error },
      clearQuery: () => { queryActive = false },
      setTicket: (ticket: string) => { ticketValue = ticket; queryActive = true },
      setFeatureEnabled: (enabled: boolean) => { featureEnabled = enabled },
      releaseCompletion,
      cleanup,
    }
  }

  it('real Settings + real ApiClient dispatches the confirmed owner B token', async () => {
    const { requests } = await loadRealSettingsWithApiToken('token-b')
    const completion = requests.find(({ url }) => url.endsWith('/github/complete'))
    const status = requests.find(({ url }) => url.endsWith('/github/status'))
    expect(completion).toBeDefined()
    expect((completion?.init.headers as Record<string, string>).Authorization).toBe('Bearer token-b')
    expect(status).toBeDefined()
    expect((status?.init.headers as Record<string, string>).Authorization).toBe('Bearer token-b')
  })

  it('real Settings + real ApiClient rejects a retained A token before completion fetch', async () => {
    const { requests } = await loadRealSettingsWithApiToken('token-a')
    const completion = requests.find(({ url }) => url.endsWith('/github/complete'))
    expect(completion).toBeUndefined()
  })

  it('real Settings + real ApiClient rejects a queued completion when auth publishes retained A', async () => {
    const harness = await loadRealSettingsWithApiToken(null)
    harness.apiClient.setAuthToken('token-a')
    await settle()
    const { requests } = harness
    const completion = requests.find(({ url }) => url.endsWith('/github/complete'))
    expect(completion).toBeUndefined()
  })

  it('rejects the old B completion across a queued B→A→B owner transition', async () => {
    const harness = await loadRealSettingsWithApiToken(null)
    harness.clearQuery()
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.runEffects()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    harness.apiClient.setAuthToken('token-b')
    await settle()
    expect(harness.requests.some(({ url }) => url.endsWith('/github/complete'))).toBe(false)
  })

  it('rejects a queued B completion after unmount before auth dispatch', async () => {
    const harness = await loadRealSettingsWithApiToken(null)
    harness.cleanup()
    harness.apiClient.setAuthToken('token-b')
    await settle()
    expect(harness.requests.some(({ url }) => url.endsWith('/github/complete'))).toBe(false)
  })

  it('keeps exactly one completion across a StrictMode cleanup/setup replay', async () => {
    const harness = await loadRealSettingsWithApiToken(null)
    harness.cleanup()
    harness.render()
    harness.runEffects()
    harness.apiClient.setAuthToken('token-b')
    await settle()
    const completions = harness.requests.filter(({ url }) => url.endsWith('/github/complete'))
    expect(completions).toHaveLength(1)
    expect((completions[0].init.headers as Record<string, string>).Authorization).toBe('Bearer token-b')
  })

  it('does not start a callback or strand connecting UI on a retained-session error', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { sessionError: new Error('synthetic auth refresh error') })
    expect(harness.requests.some(({ url }) => url.endsWith('/github/complete'))).toBe(false)
    expect(hasConnectingButton(harness.render())).toBe(false)
  })

  it('clears obsolete connecting UI after same-owner token rotation', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { holdCompletion: true })
    expect(hasConnectingButton(harness.render())).toBe(true)
    harness.clearQuery()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'rotated-token-b' } })
    harness.apiClient.setAuthToken('rotated-token-b')
    harness.render()
    harness.runEffects()
    harness.releaseCompletion()
    await settle()
    expect(hasConnectingButton(harness.render())).toBe(false)
  })

  it('clears held callback UI when a retained session refresh fails', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { holdCompletion: true })
    expect(hasConnectingButton(harness.render())).toBe(true)
    harness.clearQuery()
    harness.setAuthState(false, new Error('synthetic refresh failure'))
    harness.render()
    harness.runEffects()
    harness.releaseCompletion()
    await settle()
    expect(hasConnectingButton(harness.render())).toBe(false)
  })

  it('does not reinterpret an already-started ticket as the replacement account', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { holdCompletion: true })
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.apiClient.setAuthToken('token-a')
    harness.render()
    harness.runEffects()
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith('/github/complete'))).toHaveLength(1)
    harness.releaseCompletion()
    await settle()
  })

  it('allows a genuinely new callback ticket for the replacement account', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b')
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.apiClient.setAuthToken('token-a')
    harness.setTicket('fresh-ticket-a')
    harness.render()
    harness.runEffects()
    await settle()
    const completions = harness.requests.filter(({ url }) => url.endsWith('/github/complete'))
    expect(completions).toHaveLength(2)
    expect((completions[1].init.headers as Record<string, string>).Authorization).toBe('Bearer token-a')
    expect(completions[1].init.body).toBe(JSON.stringify({ ticket: 'fresh-ticket-a' }))
  })

  it('starts the preserved callback after the retained session error clears', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { sessionError: new Error('synthetic error') })
    expect(harness.requests.some(({ url }) => url.endsWith('/github/complete'))).toBe(false)
    harness.setAuthState(false)
    harness.render()
    harness.runEffects()
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith('/github/complete'))).toHaveLength(1)
  })

  it.each(providers)('never replays a held %s callback after an account-boundary remount', async (provider) => {
    const harness = await loadRealSettingsWithApiToken('token-b', { provider, holdCompletion: true })
    const completePath = `/${providerPath(provider)}/complete`
    expect(harness.requests.filter(({ url }) => url.endsWith(completePath))).toHaveLength(1)

    // Real AccountBoundary remounts discard every component ref. Keep the old
    // callback query visible to model router.replace not having committed yet.
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.apiClient.setAuthToken('token-a')
    harness.remount()
    await settle()
    const completions = harness.requests.filter(({ url }) => url.endsWith(completePath))
    expect(completions).toHaveLength(1)
    expect((completions[0].init.headers as Record<string, string>).Authorization).toBe('Bearer token-b')
    expect(hasConnectingButton(harness.render())).toBe(false)

    harness.releaseCompletion()
    await settle()
    expect(textContent(harness.render())).not.toContain('connected successfully!')
    harness.cleanup()
  })

  it.each(providers)('does not reclaim a %s ticket after same-owner token rotation and remount', async (provider) => {
    const harness = await loadRealSettingsWithApiToken('token-b', { provider, holdCompletion: true })
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'rotated-token-b' } })
    harness.apiClient.setAuthToken('rotated-token-b')
    harness.remount()
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith(`/${providerPath(provider)}/complete`))).toHaveLength(1)
    harness.releaseCompletion()
    await settle()
    harness.cleanup()
  })

  it.each(providers)('admits a genuinely new %s ticket after remount but remembers earlier tickets', async (provider) => {
    const harness = await loadRealSettingsWithApiToken('token-b', { provider })
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.apiClient.setAuthToken('token-a')
    harness.setTicket('fresh-ticket-a')
    harness.remount()
    await settle()
    const completePath = `/${providerPath(provider)}/complete`
    const completions = harness.requests.filter(({ url }) => url.endsWith(completePath))
    expect(completions).toHaveLength(2)
    expect((completions[1].init.headers as Record<string, string>).Authorization).toBe('Bearer token-a')
    expect(completions[1].init.body).toBe(JSON.stringify({ ticket: 'fresh-ticket-a' }))

    // Returning to B (or Back navigation to B's old callback) must not revive
    // its intent, even after a different successful ticket has been admitted.
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.apiClient.setAuthToken('token-b')
    harness.setTicket('ticket-b')
    harness.remount()
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith(completePath))).toHaveLength(2)
    harness.cleanup()
  })

  it('does not let an account remount redispatch a callback still queued behind auth sync', async () => {
    const harness = await loadRealSettingsWithApiToken(null)
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.remount()
    harness.apiClient.setAuthToken('token-a')
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith('/github/complete'))).toHaveLength(0)
    harness.cleanup()
  })

  it('preserves same-owner success for an admitted GitHub callback when its feature turns off', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { holdCompletion: true })
    harness.setFeatureEnabled(false)
    harness.render()
    harness.runEffects()
    harness.releaseCompletion()
    await settle()
    expect(harness.requests.filter(({ url }) => url.endsWith('/github/complete'))).toHaveLength(1)
    expect(textContent(harness.render())).toContain('GitHub account connected successfully!')
    harness.cleanup()
  })

  it.each(providers)('can exchange an admitted %s callback with its feature already off', async (provider) => {
    const harness = await loadRealSettingsWithApiToken('token-b', { provider, featureEnabled: false })
    expect(harness.requests.filter(({ url }) => url.endsWith(`/${providerPath(provider)}/complete`))).toHaveLength(1)
    harness.cleanup()
  })

  it('does not let repeated callback effects override a successful return_to navigation', async () => {
    const harness = await loadRealSettingsWithApiToken('token-b', { returnTo: '/workspace' })
    expect(harness.replace.mock.calls).toEqual([
      ['/settings', { scroll: false }],
      ['/workspace'],
    ])
    harness.render()
    harness.runEffects()
    await settle()
    expect(harness.replace).toHaveBeenCalledTimes(2)
    expect(harness.requests.filter(({ url }) => url.endsWith('/github/complete'))).toHaveLength(1)
    harness.cleanup()
  })
})
