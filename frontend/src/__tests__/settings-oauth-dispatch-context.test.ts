import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

afterEach(() => {
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

describe('GitHub OAuth completion captured account context', () => {
  async function loadRealSettingsWithApiToken(apiToken: string | null) {
    vi.resetModules()
    let session = { user: { id: 'owner-b' }, session: { token: 'token-b' } }
    let queryActive = true
    let hookIndex = 0
    const refs: Array<{ current: unknown }> = []
    const states: unknown[] = []
    const effects: Array<() => void | (() => void)> = []
    const requests: Array<{ url: string; init: RequestInit }> = []

    vi.stubGlobal('window', { opener: null, location: { origin: 'http://localhost:3000' } })
    vi.stubGlobal('confirm', () => true)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      requests.push({ url, init })
      const body = url.endsWith('/github/complete')
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
        if (!(index in states)) states[index] = initial
        return [states[index], (value: unknown) => {
          states[index] = typeof value === 'function'
            ? (value as (previous: unknown) => unknown)(states[index])
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
        get: (key: string) => queryActive && key === 'github' ? 'complete' : queryActive && key === 'ticket' ? 'ticket-b' : null,
      }),
      useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
      usePathname: () => '/settings',
    }))
    vi.doMock('@/hooks/useRequireAuth', () => ({
      useRequireAuth: () => ({
        session,
        isPending: false,
        error: null,
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
      ;(content.type as () => VNode)()
    }
    const runEffects = () => {
      while (effects.length) {
        const cleanup = effects.shift()?.()
        if (cleanup) cleanups.push(cleanup)
      }
    }
    render()
    runEffects()
    await settle()
    return {
      requests,
      apiClient,
      render,
      runEffects,
      setSession: (next: typeof session) => { session = next },
      clearQuery: () => { queryActive = false },
      cleanup: () => { while (cleanups.length) cleanups.pop()?.() },
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
})
