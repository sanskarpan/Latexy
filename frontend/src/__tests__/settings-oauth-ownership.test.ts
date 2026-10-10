import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

type Harness = {
  render: () => VNode
  runLifecycleEffect: () => () => void
  runInitialEffect: () => () => void
  runNormalDriveEffect: () => () => void
  runCompletionEffect: () => () => void
  cleanups: () => void
  setQuery: (value: string | null) => void
  setProvider: (value: 'google_drive' | 'github') => void
  setSession: (value: unknown) => void
  replace: ReturnType<typeof vi.fn>
  complete: ReturnType<typeof vi.fn>
  completeGithub: ReturnType<typeof vi.fn>
  status: ReturnType<typeof vi.fn>
  githubStatus: ReturnType<typeof vi.fn>
  stateUpdates: unknown[]
}

async function loadSettingsHarness(): Promise<Harness> {
  vi.resetModules()
  let query: string | null = 'ticket-a'
  let provider: 'google_drive' | 'github' = 'google_drive'
  let session: unknown = {
    user: { id: 'account-a' },
    session: { token: 'session-a' },
  }
  let hookIndex = 0
  let states: unknown[] = []
  let refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const activeCleanups: Array<() => void> = []
  const stateUpdates: unknown[] = []
  const replace = vi.fn()
  const complete = vi.fn()
  const completeGithub = vi.fn()
  const status = vi.fn()
  const githubStatus = vi.fn().mockResolvedValue({ connected: false, username: null, public_import: false, private_sync: false })

  vi.stubGlobal('window', { opener: null, location: { origin: 'http://localhost:5180' } })
  vi.stubGlobal('document', { cookie: '' })
  // These lifecycle fixtures assume the optional tour is available.
  // Entitlement failures and identity isolation are exercised separately.
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: () => true }) }))
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
        stateUpdates.push(states[index])
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/navigation', () => ({
    useSearchParams: () => ({
      get: (key: string) => key === 'google_drive'
        ? provider === 'google_drive' && query ? 'complete' : null
        : key === 'github'
          ? provider === 'github' && query ? 'complete' : null
          : key === 'ticket' ? query : null,
    }),
    useRouter: () => ({ replace }),
    usePathname: () => '/settings',
  }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session, isPending: false, error: null }) }))
  vi.doMock('@/components/onboarding/OnboardingFlow', () => ({ useOnboarding: () => ({ resetOnboarding: vi.fn() }) }))
  vi.doMock('@/hooks/usePushNotifications', () => ({ getNotificationPref: () => true, setNotificationPref: vi.fn() }))
  vi.doMock('@/lib/oauth-navigation', () => ({ safeOAuthAuthorizationUrl: vi.fn(() => null) }))
  vi.doMock('@/components/PersonalDictionarySettings', () => ({ default: 'PersonalDictionarySettings' }))
  vi.doMock('@/components/auth/SecuritySettings', () => ({ default: 'SecuritySettings' }))
  vi.doMock('@/components/ReferralPanel', () => ({ default: 'ReferralPanel' }))
  vi.doMock('lucide-react', () => ({
    Bell: 'Bell', BookOpen: 'BookOpen', Mail: 'Mail', Calendar: 'Calendar', Loader2: 'Loader2',
    CheckCircle: 'CheckCircle', Monitor: 'Monitor', Unlink: 'Unlink', ExternalLink: 'ExternalLink',
    Cloud: 'Cloud', LogIn: 'LogIn', CircleAlert: 'CircleAlert', Eye: 'Eye',
  }))
  vi.doMock('@/components/icons/brand-icons', () => ({ Github: 'Github' }))
  vi.doMock('@/lib/api-client', () => ({
    apiClient: {
      getNotificationPrefs: vi.fn().mockResolvedValue({}),
      getGitHubStatus: githubStatus,
      getZoteroStatus: vi.fn().mockResolvedValue({ connected: false }),
      getMendeleyStatus: vi.fn().mockResolvedValue({ connected: false }),
      getDropboxStatus: vi.fn().mockResolvedValue({ connected: false }),
      completeGoogleDriveOAuth: complete,
      completeGitHubOAuth: completeGithub,
      getGoogleDriveStatus: status,
    },
  }))

  const page = (await import('../app/settings/page')).default() as VNode
  const content = page.props.children as VNode
  const render = () => {
    hookIndex = 0
    effects = []
    return (content.type as () => VNode)()
  }
  const run = (marker: string) => {
    const effect = effects.find((candidate) => candidate.toString().includes(marker))
    if (!effect) throw new Error(`settings effect containing ${marker} was not registered`)
    const cleanup = effect()
    if (cleanup) activeCleanups.push(cleanup)
    return cleanup as (() => void) | undefined
  }

  return {
    render,
    runLifecycleEffect: () => run('googleDriveStatusGenerationRef.current += 1') as () => void,
    // Locate the initial integration effect independently of optional
    // notification request-context arguments. The status assertions below
    // still exercise its real cancellation and account-generation guards.
    runInitialEffect: () => run('apiClient.getNotificationPrefs(') as () => void,
    runNormalDriveEffect: () => run('hasDriveTicket') as () => void,
    runCompletionEffect: () => run('const providers') as () => void,
    cleanups: () => { while (activeCleanups.length) activeCleanups.pop()?.() },
    setQuery: (value) => { query = value },
    setProvider: (value) => { provider = value },
    setSession: (value) => { session = value },
    replace,
    complete,
    completeGithub,
    status,
    githubStatus,
    stateUpdates,
  }
}

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

afterEach(() => {
  vi.doUnmock('@/contexts/EntitlementsContext')
  vi.unstubAllGlobals()
  for (const moduleName of [
    'react', 'react/jsx-runtime', 'next/navigation', '@/hooks/useRequireAuth',
    '@/components/onboarding/OnboardingFlow', '@/hooks/usePushNotifications',
    '@/lib/oauth-navigation', '@/components/PersonalDictionarySettings',
    '@/components/auth/SecuritySettings', '@/components/ReferralPanel',
    'lucide-react', '@/components/icons/brand-icons', '@/lib/api-client',
  ]) vi.doUnmock(moduleName)
  vi.resetModules()
})

describe('settings OAuth deferred ownership', () => {
  it('does not issue a second Drive status request after delayed ticket cleanup', async () => {
    const harness = await loadSettingsHarness()
    let resolveCompletion!: () => void
    let resolveStatus!: (value: unknown) => void
    harness.complete.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))
    harness.status.mockImplementation(() => new Promise((resolve) => { resolveStatus = resolve }))

    harness.render()
    harness.runLifecycleEffect()
    harness.runNormalDriveEffect()
    harness.runCompletionEffect()
    expect(harness.complete).toHaveBeenCalledWith('ticket-a')
    expect(harness.status).not.toHaveBeenCalled()

    resolveCompletion()
    await settle()
    expect(harness.status).toHaveBeenCalledTimes(1)
    resolveStatus({ connected: true, scope: 'drive.file' })
    await settle()

    // Simulate router.replace completing after the exchange's status read.
    harness.setQuery(null)
    harness.render()
    harness.runNormalDriveEffect()
    expect(harness.status).toHaveBeenCalledTimes(1)
    harness.cleanups()
  })

  it('retains the pending one-use completion across a Strict Mode effect replay', async () => {
    const harness = await loadSettingsHarness()
    let resolveCompletion!: () => void
    harness.complete.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))
    harness.status.mockResolvedValue({ connected: true, scope: 'drive.file' })

    harness.render()
    const firstLifecycleCleanup = harness.runLifecycleEffect()
    harness.runCompletionEffect()
    firstLifecycleCleanup()

    // Strict Mode immediately sets the effect up again before the deferred
    // cleanup microtask runs. The existing owner/key must be reused.
    harness.render()
    harness.runLifecycleEffect()
    harness.runCompletionEffect()
    await settle()
    expect(harness.complete).toHaveBeenCalledTimes(1)

    resolveCompletion()
    await settle()
    expect(harness.status).toHaveBeenCalledTimes(1)
    expect(harness.stateUpdates).toContain('Google Drive connected successfully!')
    harness.cleanups()
  })

  it('ignores a Drive completion after the account changes', async () => {
    const harness = await loadSettingsHarness()
    let resolveCompletion!: () => void
    harness.complete.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))
    harness.status.mockResolvedValue({ connected: true, scope: 'drive.file' })

    harness.render()
    harness.runLifecycleEffect()
    harness.runCompletionEffect()
    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.setQuery(null)
    harness.render()
    harness.runNormalDriveEffect()
    resolveCompletion()
    await settle()

    expect(harness.status).toHaveBeenCalledTimes(1)
    expect(harness.stateUpdates).not.toContain('Google Drive connected successfully!')
    harness.cleanups()
  })

  it('ignores a Drive completion after the session token changes for the same user', async () => {
    const harness = await loadSettingsHarness()
    let resolveCompletion!: () => void
    harness.complete.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))
    harness.status.mockResolvedValue({ connected: true, scope: 'drive.file' })

    harness.render()
    harness.runLifecycleEffect()
    harness.runCompletionEffect()
    harness.setSession({ user: { id: 'account-a' }, session: { token: 'session-b' } })
    harness.setQuery(null)
    harness.render()
    harness.runNormalDriveEffect()
    resolveCompletion()
    await settle()

    expect(harness.status).toHaveBeenCalledTimes(1)
    expect(harness.stateUpdates).not.toContain('Google Drive connected successfully!')
    harness.cleanups()
  })

  it('does not update state after the settings page unmounts', async () => {
    const harness = await loadSettingsHarness()
    let resolveCompletion!: () => void
    harness.complete.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))
    harness.render()
    harness.runLifecycleEffect()
    harness.runCompletionEffect()
    const updatesBeforeUnmount = harness.stateUpdates.length
    harness.cleanups()
    expect(harness.stateUpdates).toHaveLength(updatesBeforeUnmount)
    resolveCompletion()
    await settle()
    expect(harness.stateUpdates).toHaveLength(updatesBeforeUnmount)
    expect(harness.status).not.toHaveBeenCalled()
  })

  it('ignores an initial integration status after the account changes', async () => {
    const harness = await loadSettingsHarness()
    const oldStatus = { connected: true, username: 'old-account', public_import: true, private_sync: false }
    let resolveOld!: (value: unknown) => void
    harness.githubStatus.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))

    harness.render()
    const cleanupOld = harness.runInitialEffect()
    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    cleanupOld()
    harness.render()
    harness.runInitialEffect()
    resolveOld(oldStatus)
    await settle()

    expect(harness.stateUpdates).not.toContain(oldStatus)
    harness.cleanups()
  })

  it('does not update an initial integration status after settings unmounts', async () => {
    const harness = await loadSettingsHarness()
    const oldStatus = { connected: true, username: 'old-account', public_import: true, private_sync: false }
    let resolveOld!: (value: unknown) => void
    harness.githubStatus.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))

    harness.render()
    const cleanup = harness.runInitialEffect()
    const updatesBeforeUnmount = harness.stateUpdates.length
    cleanup()
    resolveOld(oldStatus)
    await settle()

    expect(harness.stateUpdates).toHaveLength(updatesBeforeUnmount)
    expect(harness.stateUpdates).not.toContain(oldStatus)
    harness.cleanups()
  })

  it('does not apply a pending GitHub OAuth response after the account changes', async () => {
    const harness = await loadSettingsHarness()
    harness.setProvider('github')
    let resolveCompletion!: () => void
    harness.completeGithub.mockImplementation(() => new Promise<void>((resolve) => { resolveCompletion = resolve }))

    harness.render()
    harness.runLifecycleEffect()
    harness.runCompletionEffect()
    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.setQuery(null)
    harness.render()
    harness.runInitialEffect()
    harness.githubStatus.mockClear()
    resolveCompletion()
    await settle()

    expect(harness.githubStatus).not.toHaveBeenCalled()
    expect(harness.stateUpdates).not.toContain('GitHub account connected successfully!')
    harness.cleanups()
  })
})
