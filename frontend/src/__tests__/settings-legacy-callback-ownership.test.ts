import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }
type Session = { user: { id: string }; session: { token: string } }
type Provider = 'github' | 'zotero' | 'mendeley' | 'dropbox'

type Harness = {
  render: () => VNode
  runMountedEffect: () => () => void
  runLegacyEffect: () => () => void
  runLegacyOwnerNoticeEffect: () => () => void
  setSession: (session: Session) => void
  setProvider: (provider: Provider) => void
  setProviders: (providers: Provider[]) => void
  setQuery: (connected: boolean) => void
  setAuthState: (pending: boolean, error?: Error | null) => void
  holdGitHubDispatch: (held: boolean) => void
  dispatchGitHub: (index?: number) => void
  runInitialStatusEffect: () => () => void
  resolveGitHub: (value: unknown, index?: number) => void
  rejectGitHub: (error: Error, index?: number) => void
  resolveZotero: (value: unknown, index?: number) => void
  resolveMendeley: (value: unknown, index?: number) => void
  resolveDropbox: (value: unknown, index?: number) => void
  githubContexts: Array<{ authToken: string; isCurrent: () => boolean }>
  zoteroContexts: Array<{ authToken: string; isCurrent: () => boolean }>
  routerReplacements: string[]
  dropboxContexts: Array<{ authToken: string; isCurrent: () => boolean }>
  stateUpdates: unknown[]
  cleanups: () => void
  opener: { postMessage: ReturnType<typeof vi.fn> }
  close: ReturnType<typeof vi.fn>
}

async function loadHarness(): Promise<Harness> {
  vi.resetModules()
  let session: Session = { user: { id: 'account-a' }, session: { token: 'session-a' } }
  let providers: Provider[] = ['github']
  let queryConnected = true
  let sessionPending = false
  let sessionError: Error | null = null
  let hookIndex = 0
  let states: unknown[] = []
  let refs: Array<{ current: unknown }> = []
  let memos: Array<{ deps: unknown[]; value: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const activeCleanups: Array<() => void> = []
  const stateUpdates: unknown[] = []
  const githubContexts: Array<{ authToken: string; isCurrent: () => boolean }> = []
  const githubResolvers: Array<(value: unknown) => void> = []
  const githubRejecters: Array<(error: Error) => void> = []
  const githubDispatchers: Array<() => void> = []
  let holdGitHubDispatch = false
  const routerReplacements: string[] = []
  const dropboxContexts: Array<{ authToken: string; isCurrent: () => boolean }> = []
  const dropboxResolvers: Array<(value: unknown) => void> = []
  const zoteroContexts: Array<{ authToken: string; isCurrent: () => boolean }> = []
  const zoteroResolvers: Array<(value: unknown) => void> = []
  const mendeleyResolvers: Array<(value: unknown) => void> = []
  const githubStatus = vi.fn().mockImplementation((context?: { authToken: string; isCurrent: () => boolean }) => {
    if (context) githubContexts.push(context)
    return new Promise((resolve, reject) => {
      const index = githubResolvers.length
      githubResolvers.push(resolve)
      githubRejecters.push(reject)
      const dispatch = () => {
        if (context && !context.isCurrent()) {
          reject(new Error('Account request context changed before dispatch'))
        }
      }
      githubDispatchers[index] = dispatch
      if (!holdGitHubDispatch) dispatch()
    })
  })
  const zoteroStatus = vi.fn().mockImplementation((context?: { authToken: string; isCurrent: () => boolean }) => {
    if (context) {
      zoteroContexts.push(context)
      if (!context.isCurrent()) return Promise.reject(new Error('Account request context changed before dispatch'))
    }
    return new Promise((resolve) => { zoteroResolvers.push(resolve) })
  })
  const mendeleyStatus = vi.fn().mockImplementation((context?: { isCurrent: () => boolean }) => {
    if (context && !context.isCurrent()) return Promise.reject(new Error('Account request context changed before dispatch'))
    return new Promise((resolve) => { mendeleyResolvers.push(resolve) })
  })
  const dropboxStatus = vi.fn().mockImplementation((context?: { authToken: string; isCurrent: () => boolean }) => {
    if (context) dropboxContexts.push(context)
    if (context && !context.isCurrent()) return Promise.reject(new Error('Account request context changed before dispatch'))
    return new Promise((resolve) => { dropboxResolvers.push(resolve) })
  })
  const opener = { postMessage: vi.fn() }
  const close = vi.fn()

  vi.stubGlobal('window', { opener, close, location: { origin: 'http://localhost:5180' } })
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
    useMemo: (factory: () => unknown, deps: unknown[]) => {
      const index = hookIndex++
      const previous = memos[index]
      const changed = !previous || deps.length !== previous.deps.length
        || deps.some((value, depIndex) => !Object.is(value, previous.deps[depIndex]))
      if (changed) memos[index] = { deps: [...deps], value: factory() }
      return memos[index].value
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/navigation', () => ({
    useSearchParams: () => ({
      get: (key: string) => providers.includes(key as Provider) && queryConnected ? 'connected' : null,
      toString: () => queryConnected ? providers.map((provider) => `${provider}=connected`).join('&') : '',
    }),
    useRouter: () => ({ replace: vi.fn((path: string) => { routerReplacements.push(path) }) }),
    usePathname: () => '/settings',
  }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session, isPending: sessionPending, error: sessionError }) }))
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
      getZoteroStatus: zoteroStatus,
      getMendeleyStatus: mendeleyStatus,
      getDropboxStatus: dropboxStatus,
      getGoogleDriveStatus: vi.fn().mockResolvedValue({ connected: false }),
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
    runMountedEffect: () => run('providerActionMountedRef.current = true') as () => void,
    runLegacyEffect: () => run('const connectedProviders') as () => void,
    runLegacyOwnerNoticeEffect: () => run('clearPreviousOwnerNotice') as () => void,
    setSession: (next) => { session = next },
    setProvider: (next) => { providers = [next] },
    setProviders: (next) => { providers = next },
    setQuery: (connected) => { queryConnected = connected },
    setAuthState: (pending, error = null) => { sessionPending = pending; sessionError = error },
    holdGitHubDispatch: (held) => { holdGitHubDispatch = held },
    dispatchGitHub: (index = 0) => githubDispatchers[index]?.(),
    runInitialStatusEffect: () => run('const generation = ++integrationStatusGenerationRef.current') as () => void,
    resolveGitHub: (value, index = 0) => githubResolvers[index]?.(value),
    rejectGitHub: (error, index = 0) => githubRejecters[index]?.(error),
    resolveZotero: (value, index = 0) => zoteroResolvers[index]?.(value),
    resolveMendeley: (value, index = 0) => mendeleyResolvers[index]?.(value),
    resolveDropbox: (value, index = 0) => dropboxResolvers[index]?.(value),
    githubContexts,
    zoteroContexts,
    routerReplacements,
    dropboxContexts,
    stateUpdates,
    cleanups: () => { while (activeCleanups.length) activeCleanups.pop()?.() },
    opener,
    close,
  }
}

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

beforeEach(() => vi.useFakeTimers())

afterEach(() => {
  vi.useRealTimers()
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

describe('legacy Settings callback ownership', () => {
  it('does not publish a held response after an owner ABA transition', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts[0].authToken).toBe('session-a')

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    harness.setSession({ user: { id: 'account-a' }, session: { token: 'session-a' } })
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts[0].isCurrent()).toBe(false)

    const updatesBeforeRelease = harness.stateUpdates.length
    harness.resolveGitHub({ connected: true, username: 'AliceLegacy', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates.slice(updatesBeforeRelease)).not.toContainEqual(expect.objectContaining({ username: 'AliceLegacy' }))
    harness.cleanups()
  })

  it('invalidates a held response when Settings unmounts', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    const updatesBeforeUnmount = harness.stateUpdates.length
    harness.cleanups()
    harness.resolveGitHub({ connected: true, username: 'AliceAfterUnmount', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toHaveLength(updatesBeforeUnmount)
  })

  it('retains same-owner success and guards the expiry timer', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'Alice', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toContain('GitHub account connected successfully!')
    vi.advanceTimersByTime(5_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('deduplicates a Strict Mode effect replay without stranding the request', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    harness.resolveGitHub({ connected: true, username: 'Alice', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toContain('GitHub account connected successfully!')
    harness.cleanups()
  })

  it('restarts a request after the actual Strict Mode cleanup/setup replay', async () => {
    const harness = await loadHarness()
    harness.render()
    const firstCleanup = harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)

    firstCleanup()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()

    expect(harness.githubContexts).toHaveLength(2)
    expect(harness.githubContexts[0]?.isCurrent()).toBe(false)
    expect(harness.githubContexts[1]?.isCurrent()).toBe(true)
    harness.resolveGitHub({ connected: true, username: 'OldReplay', public_import: true, private_sync: false }, 0)
    harness.resolveGitHub({ connected: true, username: 'FreshReplay', public_import: true, private_sync: false }, 1)
    await settle()
    expect(harness.stateUpdates).not.toContainEqual(expect.objectContaining({ username: 'OldReplay' }))
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'FreshReplay' }))
    harness.cleanups()
  })

  it('does not apply an older same-owner callback after a newer callback', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.setQuery(false)
    harness.render()
    harness.runLegacyEffect()
    harness.setQuery(true)
    harness.render()
    harness.runLegacyEffect()

    harness.resolveGitHub({ connected: true, username: 'NewerSameOwner', public_import: true, private_sync: false }, 1)
    await settle()
    harness.resolveGitHub({ connected: true, username: 'OlderSameOwner', public_import: true, private_sync: false }, 0)
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'NewerSameOwner' }))
    expect(harness.stateUpdates).not.toContainEqual(expect.objectContaining({ username: 'OlderSameOwner' }))
    harness.cleanups()
  })

  it('does not report success when the current provider remains disconnected', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: false, username: null, public_import: false, private_sync: false })
    await settle()
    expect(harness.stateUpdates).not.toContain('GitHub account connected successfully!')
    expect(harness.stateUpdates).toContain('GitHub account authorization completed, but the connection could not be verified. Refresh or try connecting again.')
    harness.cleanups()
  })

  it('does not let an older same-owner timer clear a newer callback notice', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'OlderNotice', public_import: true, private_sync: false }, 0)
    await settle()
    vi.advanceTimersByTime(1_000)
    harness.setQuery(false)
    harness.render()
    harness.runLegacyEffect()
    harness.setQuery(true)
    harness.render()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'NewerNotice', public_import: true, private_sync: false }, 1)
    await settle()
    vi.advanceTimersByTime(4_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBe('GitHub account connected successfully!')
    vi.advanceTimersByTime(1_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('expires a confirmed notice after a same-owner token rotation', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'Alice', public_import: true, private_sync: false })
    await settle()
    harness.setSession({ user: { id: 'account-a' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    vi.advanceTimersByTime(5_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('keeps an already-dispatched verified read across same-owner token refresh', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    expect(harness.githubContexts[0]?.isCurrent()).toBe(true)

    harness.setSession({ user: { id: 'account-a' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    expect(harness.githubContexts[0]?.isCurrent()).toBe(false)

    harness.resolveGitHub({ connected: true, username: 'RefreshedSameOwner', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'RefreshedSameOwner' }))
    expect(harness.stateUpdates).toContain('GitHub account connected successfully!')
    vi.advanceTimersByTime(5_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('posts a verified Zotero popup result after same-owner token refresh', async () => {
    const harness = await loadHarness()
    harness.setProvider('zotero')
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.zoteroContexts).toHaveLength(1)
    expect(harness.zoteroContexts[0]?.authToken).toBe('session-a')

    harness.setSession({ user: { id: 'account-a' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    expect(harness.zoteroContexts).toHaveLength(1)

    harness.resolveZotero({ connected: true, username: 'ZoteroAfterRefresh', user_id: 'zotero-a' })
    await settle()
    expect(harness.opener.postMessage).toHaveBeenCalledWith(
      { type: 'zotero:connected' },
      'http://localhost:5180',
    )
    expect(harness.close).toHaveBeenCalledTimes(1)
    harness.cleanups()
  })

  it('preserves the OAuth query when auth is lost before dispatch, then retries after confirmation', async () => {
    const harness = await loadHarness()
    harness.holdGitHubDispatch(true)
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    expect(harness.routerReplacements).toHaveLength(0)

    harness.setAuthState(true)
    harness.render()
    harness.runLegacyEffect()
    harness.dispatchGitHub(0)
    await settle()
    expect(harness.routerReplacements).toHaveLength(0)

    harness.setAuthState(false)
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(2)
    expect(harness.githubContexts[1]?.isCurrent()).toBe(true)
    harness.dispatchGitHub(1)
    harness.resolveGitHub({ connected: true, username: 'ConfirmedRetry', public_import: true, private_sync: false }, 1)
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'ConfirmedRetry' }))
    expect(harness.routerReplacements).toEqual(['/settings'])
    harness.cleanups()
  })

  it('keeps an initial status visible while the legacy callback verification is held', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runInitialStatusEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)

    harness.resolveGitHub({ connected: false, username: null, public_import: false, private_sync: false }, 0)
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ connected: false }))
    expect(harness.stateUpdates).not.toContain('GitHub account connected successfully!')
    harness.cleanups()
  })

  it('does not let an older initial status overwrite the verified callback result', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runInitialStatusEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)

    harness.resolveGitHub({ connected: true, username: 'CallbackVerified', public_import: true, private_sync: false }, 1)
    await settle()
    const callbackUpdateIndex = harness.stateUpdates.findIndex((value) => (
      typeof value === 'object' && value !== null && 'username' in value && value.username === 'CallbackVerified'
    ))
    expect(callbackUpdateIndex).toBeGreaterThanOrEqual(0)

    harness.resolveGitHub({ connected: false, username: 'InitialStale', public_import: false, private_sync: false }, 0)
    await settle()
    expect(harness.stateUpdates.slice(callbackUpdateIndex + 1)).not.toContainEqual(
      expect.objectContaining({ username: 'InitialStale' }),
    )
    expect(harness.stateUpdates.slice(callbackUpdateIndex + 1)).not.toContainEqual(
      expect.objectContaining({ connected: false }),
    )
    harness.cleanups()
  })

  it('does not let an old-owner timer clear a newer-owner notice', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'Alice', public_import: true, private_sync: false }, 0)
    await settle()
    vi.advanceTimersByTime(1_000)
    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'Bob', public_import: true, private_sync: false }, 1)
    await settle()
    vi.advanceTimersByTime(4_000)
    expect(harness.stateUpdates).toContain('GitHub account connected successfully!')
    vi.advanceTimersByTime(1_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('clears a settled legacy success notice when its owner changes without another callback', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'AliceNotice', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toContain('GitHub account connected successfully!')

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyOwnerNoticeEffect()
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    vi.advanceTimersByTime(5_000)
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('clears a settled legacy verification error when its owner changes', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: false, username: null, public_import: false, private_sync: false })
    await settle()
    const verificationError = 'GitHub account authorization completed, but the connection could not be verified. Refresh or try connecting again.'
    expect(harness.stateUpdates).toContain(verificationError)

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyOwnerNoticeEffect()
    expect(harness.stateUpdates[harness.stateUpdates.length - 1]).toBeNull()
    harness.cleanups()
  })

  it('does not post or close after a held Zotero response outlives unmount', async () => {
    const harness = await loadHarness()
    harness.setProvider('zotero')
    harness.render()
    const cleanup = harness.runMountedEffect()
    harness.runLegacyEffect()
    cleanup()
    harness.resolveZotero({ connected: true, username: 'ZoteroAfterUnmount', user_id: 'zotero-a' })
    await settle()
    expect(harness.opener.postMessage).not.toHaveBeenCalled()
    expect(harness.close).not.toHaveBeenCalled()
    harness.cleanups()
  })

  it('keeps simultaneous GitHub and Zotero operations independent', async () => {
    const harness = await loadHarness()
    harness.setProviders(['github', 'zotero'])
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveGitHub({ connected: true, username: 'AliceGitHub', public_import: true, private_sync: false })
    harness.resolveZotero({ connected: true, username: 'AliceZotero', user_id: 'zotero-a' })
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'AliceGitHub' }))
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'AliceZotero' }))
    expect(harness.opener.postMessage).toHaveBeenCalledWith({ type: 'zotero:connected' }, 'http://localhost:5180')
    harness.cleanups()
  })

  it('does not publish a held Mendeley response after an owner change', async () => {
    const harness = await loadHarness()
    harness.setProvider('mendeley')
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    harness.resolveMendeley({ connected: true, name: 'MendeleyAfterOwnerChange' }, 0)
    await settle()
    expect(harness.stateUpdates).not.toContainEqual(expect.objectContaining({ name: 'MendeleyAfterOwnerChange' }))
    expect(harness.stateUpdates).not.toContain('Mendeley connected successfully!')
    harness.resolveMendeley({ connected: false }, 1)
    harness.cleanups()
  })

  it('does not publish a held Dropbox response after an owner change', async () => {
    const harness = await loadHarness()
    harness.setProvider('dropbox')
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.dropboxContexts[0]?.authToken).toBe('session-a')

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    expect(harness.dropboxContexts[0]?.isCurrent()).toBe(false)
    harness.resolveDropbox({ connected: true, display_name: 'DropboxAfterOwnerChange', account_id: 'dropbox-a' }, 0)
    await settle()
    expect(harness.stateUpdates).not.toContainEqual(expect.objectContaining({ display_name: 'DropboxAfterOwnerChange' }))
    expect(harness.stateUpdates).not.toContain('Dropbox account connected successfully!')
    harness.cleanups()
  })

  it('waits for confirmed auth before dispatching the legacy callback status read', async () => {
    const harness = await loadHarness()
    harness.setAuthState(true)
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(0)

    harness.setAuthState(false)
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)
    expect(harness.githubContexts[0]?.authToken).toBe('session-a')
    harness.resolveGitHub({ connected: true, username: 'CurrentAfterAuth', public_import: true, private_sync: false })
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'CurrentAfterAuth' }))
    harness.cleanups()
  })

  it('retries if auth is restored before the old pre-dispatch rejection settles', async () => {
    const harness = await loadHarness()
    harness.holdGitHubDispatch(true)
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(1)

    harness.setAuthState(true)
    harness.render()
    harness.runLegacyEffect()
    harness.setAuthState(false)
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(2)
    expect(harness.githubContexts[0]?.isCurrent()).toBe(false)
    expect(harness.githubContexts[1]?.isCurrent()).toBe(true)
    expect(harness.routerReplacements).toHaveLength(0)

    // Resolve the old auth wait after the fresh attempt already exists. It must
    // neither dispatch with its stale context nor delete the fresh attempt.
    harness.dispatchGitHub(0)
    await settle()
    harness.render()
    harness.runLegacyEffect()
    expect(harness.githubContexts).toHaveLength(2)
    expect(harness.stateUpdates).not.toContain('GitHub account connected successfully!')
    expect(harness.routerReplacements).toHaveLength(0)

    harness.dispatchGitHub(1)
    harness.resolveGitHub({ connected: true, username: 'RetryAfterAuthReturn', public_import: true, private_sync: false }, 1)
    await settle()
    expect(harness.stateUpdates).toContainEqual(expect.objectContaining({ username: 'RetryAfterAuthReturn' }))
    expect(harness.routerReplacements).toEqual(['/settings'])
    harness.cleanups()
  })

  it('suppresses a stale provider verification error after an owner change', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    harness.render()
    harness.runLegacyEffect()
    const beforeStaleFailure = harness.stateUpdates.length
    harness.rejectGitHub(new Error('stale verification failure'), 0)
    await settle()
    expect(harness.stateUpdates.slice(beforeStaleFailure)).not.toContain(
      'GitHub account authorization completed, but the connection could not be verified. Refresh or try connecting again.',
    )
    harness.resolveGitHub({ connected: false, username: null, public_import: false, private_sync: false }, 1)
    await settle()
    harness.cleanups()
  })

  it('posts the Zotero opener message only after a current verified response', async () => {
    const harness = await loadHarness()
    harness.setProvider('zotero')
    harness.render()
    harness.runMountedEffect()
    harness.runLegacyEffect()
    harness.resolveZotero({ connected: true, username: 'Zotero User', user_id: 'zotero-user' })
    await settle()
    expect(harness.opener.postMessage).toHaveBeenCalledWith(
      { type: 'zotero:connected' },
      'http://localhost:5180',
    )
    expect(harness.close).toHaveBeenCalledTimes(1)
    harness.cleanups()
  })
})
