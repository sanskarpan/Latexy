import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, any> }
type Session = { user: { id: string }; session: { token: string } }

type Harness = {
  render: () => VNode
  runEffects: () => void
  cleanupEffects: () => void
  setSession: (session: Session) => void
  setAuthState: (pending: boolean, error?: Error | null) => void
  stateUpdates: Array<{ index: number; value: unknown }>
  apiCalls: Array<{ method: string; owner: string; args: unknown[] }>
  resolveGoogle: (value: unknown, index?: number) => void
  resolveDisconnectGoogle: (value: unknown, index?: number) => void
  rejectDisconnectGoogle: (error: Error, index?: number) => void
  resolveDisconnectGithub: (value: unknown, index?: number) => void
  setGoogleStatusMode: (mode: 'error' | 'held' | 'connected' | 'disconnected') => void
  getRoot: () => VNode
}

function textContent(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    return textContent((node as VNode).props.children)
  }
  return ''
}

function findButton(root: VNode, label: string): VNode {
  const pending: unknown[] = [root]
  while (pending.length) {
    const node = pending.shift()
    if (!node || typeof node !== 'object') continue
    if ('props' in node) {
      const vnode = node as VNode
      if (vnode.type === 'button' && textContent(vnode).includes(label)) return vnode
      pending.push(vnode.props.children)
    }
    if (Array.isArray(node)) pending.push(...node)
  }
  throw new Error(`button ${label} not found in rendered Settings component`)
}

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

async function loadHarness(): Promise<Harness> {
  vi.resetModules()
  let session: Session = { user: { id: 'owner-a' }, session: { token: 'token-a' } }
  let sessionPending = false
  let sessionError: Error | null = null
  let hookIndex = 0
  const memos: Array<{ deps: unknown[]; value: unknown }> = []
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  const effects: Array<() => void | (() => void)> = []
  const cleanups: Array<() => void> = []
  const stateUpdates: Array<{ index: number; value: unknown }> = []
  const apiCalls: Array<{ method: string; owner: string; args: unknown[] }> = []
  const googleResolvers: Array<(value: unknown) => void> = []
  const disconnectGoogleResolvers: Array<(value: unknown) => void> = []
  const disconnectGoogleRejecters: Array<(error: Error) => void> = []
  const disconnectGithubResolvers: Array<(value: unknown) => void> = []
  let googleMode: 'error' | 'held' | 'connected' | 'disconnected' = 'disconnected'
  let googleCallIndex = 0

  const recordCall = (method: string, args: unknown[]) => {
    apiCalls.push({ method, owner: session.user.id, args })
  }
  const mockGoogleStatus = vi.fn((...args: unknown[]) => {
    recordCall('getGoogleDriveStatus', args)
    const mode = googleMode
    googleCallIndex += 1
    if (mode === 'error') return Promise.reject(new Error('synthetic status failure'))
    if (mode === 'held') return new Promise((resolve) => { googleResolvers.push(resolve) })
    return Promise.resolve({ connected: mode === 'connected', scope: mode === 'connected' ? 'drive.file' : null })
  })
  const mockDisconnectGoogle = vi.fn((...args: unknown[]) => {
    recordCall('disconnectGoogleDrive', args)
    return new Promise((resolve, reject) => {
      disconnectGoogleResolvers.push(resolve)
      disconnectGoogleRejecters.push(reject)
    })
  })
  const mockDisconnectGithub = vi.fn((...args: unknown[]) => {
    recordCall('disconnectGitHub', args)
    return new Promise((resolve) => { disconnectGithubResolvers.push(resolve) })
  })
  const mockGithubStatus = vi.fn((...args: unknown[]) => {
    recordCall('getGitHubStatus', args)
    return Promise.resolve({ connected: true, username: 'Alice', public_import: true, private_sync: false })
  })
  const disconnected = (method: string) => vi.fn((...args: unknown[]) => {
    recordCall(method, args)
    return Promise.resolve({ connected: false })
  })

  vi.stubGlobal('window', {
    opener: null,
    close: vi.fn(),
    location: { origin: 'http://localhost:3000', assign: vi.fn() },
    localStorage: { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() },
  })
  vi.stubGlobal('confirm', () => true)
  vi.stubGlobal('Notification', undefined)
  vi.doMock('react', () => ({
    Suspense: 'Suspense',
    useMemo: (factory: () => unknown, deps: unknown[]) => {
      const index = hookIndex++
      const previous = memos[index]
      if (!previous || deps.length !== previous.deps.length || deps.some((value, depIndex) => !Object.is(value, previous.deps[depIndex]))) {
        memos[index] = { deps: [...deps], value: factory() }
      }
      return memos[index].value
    },
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
        stateUpdates.push({ index, value: states[index] })
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/navigation', () => ({
    useSearchParams: () => ({ get: () => null, toString: () => '' }),
    useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
    usePathname: () => '/settings',
  }))
  vi.doMock('@/hooks/useRequireAuth', () => ({
    useRequireAuth: () => ({ session, isPending: sessionPending, error: sessionError }),
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
  vi.doMock('@/lib/api-client', () => ({
    apiClient: {
      getNotificationPrefs: disconnected('getNotificationPrefs'),
      getGitHubStatus: mockGithubStatus,
      getZoteroStatus: disconnected('getZoteroStatus'),
      getMendeleyStatus: disconnected('getMendeleyStatus'),
      getDropboxStatus: disconnected('getDropboxStatus'),
      getGoogleDriveStatus: mockGoogleStatus,
      disconnectGoogleDrive: mockDisconnectGoogle,
      disconnectGitHub: mockDisconnectGithub,
      disconnectZotero: disconnected('disconnectZotero'),
      disconnectDropbox: disconnected('disconnectDropbox'),
      disconnectMendeley: disconnected('disconnectMendeley'),
      startGitHubOAuth: disconnected('startGitHubOAuth'),
      startZoteroOAuth: disconnected('startZoteroOAuth'),
      startDropboxOAuth: disconnected('startDropboxOAuth'),
      startGoogleDriveOAuth: disconnected('startGoogleDriveOAuth'),
      startMendeleyOAuth: disconnected('startMendeleyOAuth'),
    },
  }))

  const page = (await import('../app/settings/page')).default() as VNode
  const content = page.props.children as VNode
  let root!: VNode
  const render = () => {
    hookIndex = 0
    effects.length = 0
    root = (content.type as () => VNode)()
    return root
  }
  const runEffects = () => {
    while (effects.length) {
      const cleanup = effects.shift()?.()
      if (cleanup) cleanups.push(cleanup)
    }
  }
  const cleanupEffects = () => {
    while (cleanups.length) cleanups.pop()?.()
  }
  render()
  runEffects()

  return {
    render,
    runEffects,
    cleanupEffects,
    setSession: (next) => { session = next },
    setAuthState: (pending, error = null) => {
      sessionPending = pending
      sessionError = error
    },
    stateUpdates,
    apiCalls,
    resolveGoogle: (value, index = 0) => googleResolvers[index]?.(value),
    resolveDisconnectGoogle: (value, index = 0) => disconnectGoogleResolvers[index]?.(value),
    rejectDisconnectGoogle: (error, index = 0) => disconnectGoogleRejecters[index]?.(error),
    resolveDisconnectGithub: (value, index = 0) => disconnectGithubResolvers[index]?.(value),
    setGoogleStatusMode: (mode) => { googleMode = mode },
    getRoot: () => root,
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('Settings provider owner races (component-executed)', () => {
  it('blocks a held Drive status response through A→B→A effect cleanup', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('held')
    harness.render()
    harness.runEffects()
    const updatesBefore = harness.stateUpdates.length

    harness.cleanupEffects()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    harness.cleanupEffects()
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.runEffects()
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'stale-a' }, 0)
    await settle()

    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value)).not.toContainEqual(
      expect.objectContaining({ marker: 'stale-a' }),
    )
  })

  it('blocks a held Drive status response through A→B effect cleanup', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('held')
    harness.render()
    harness.runEffects()
    const updatesBefore = harness.stateUpdates.length
    harness.cleanupEffects()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'stale-status-a-to-b' }, 0)
    await settle()
    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value)).not.toContainEqual(
      expect.objectContaining({ marker: 'stale-status-a-to-b' }),
    )
  })

  it('blocks a held Drive retry response after A→B→A', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const retryPromise = retry.props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'stale-retry-a' })
    await retryPromise
    const retryCall = harness.apiCalls.slice(callsBefore).find((call) => call.method === 'getGoogleDriveStatus')
    expect(retryCall?.owner).toBe('owner-a')
    expect(retryCall?.args[0]).toMatchObject({ authToken: 'token-a' })
    expect(harness.stateUpdates.map(({ value }) => value)).not.toContainEqual(expect.objectContaining({ marker: 'stale-retry-a' }))
  })

  it('blocks a held Drive retry response after A→B', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retryPromise = findButton(harness.getRoot(), 'Retry').props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'stale-retry-a-to-b' })
    await retryPromise
    expect(harness.stateUpdates.map(({ value }) => value)).not.toContainEqual(expect.objectContaining({ marker: 'stale-retry-a-to-b' }))
  })

  it('does not admit a saved Drive retry handler after the render owner changes', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const updatesBefore = harness.stateUpdates.length
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    await retry.props.onClick()
    expect(harness.apiCalls.slice(callsBefore)).toEqual([])
    expect(harness.stateUpdates.slice(updatesBefore)).toEqual([])
  })

  it('does not admit a saved Drive retry handler while auth is pending or errored', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const updatesBefore = harness.stateUpdates.length
    harness.setAuthState(true)
    harness.render()
    await retry.props.onClick()
    harness.setAuthState(false, new Error('synthetic auth refresh failure'))
    harness.render()
    await retry.props.onClick()
    expect(harness.apiCalls.slice(callsBefore)).toEqual([])
    expect(harness.stateUpdates.slice(updatesBefore)).toEqual([])
  })

  it('does not admit a saved Drive retry handler after unmount', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const updatesBefore = harness.stateUpdates.length
    harness.cleanupEffects()
    await retry.props.onClick()
    expect(harness.apiCalls.slice(callsBefore)).toEqual([])
    expect(harness.stateUpdates.slice(updatesBefore)).toEqual([])
  })

  it('keeps Drive disconnect mutually exclusive with an in-flight retry', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retryPromise = findButton(harness.getRoot(), 'Retry').props.onClick()
    harness.render()
    expect(() => findButton(harness.getRoot(), 'Disconnect Google Drive')).toThrow()
    expect(harness.apiCalls.filter((call) => call.method === 'disconnectGoogleDrive')).toEqual([])
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'current-retry' })
    await retryPromise
  })

  it('does not admit a saved Drive disconnect while retry owns the operation', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const disconnect = findButton(harness.getRoot(), 'Disconnect Google Drive')
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const retryPromise = retry.props.onClick()
    await disconnect.props.onClick()
    expect(harness.apiCalls.slice(callsBefore).filter((call) => call.method === 'disconnectGoogleDrive')).toEqual([])
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'current-retry' })
    await retryPromise
    harness.render()
    // Completion must also release the loading/admission state; suppressing
    // the competing dispatch alone would miss a permanently busy card.
    expect(() => findButton(harness.getRoot(), 'Disconnect Google Drive')).not.toThrow()
  })

  it('blocks a held Drive disconnect response after an owner switch', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const disconnect = findButton(harness.getRoot(), 'Disconnect Google Drive')
    const updatesBefore = harness.stateUpdates.length
    const disconnectPromise = disconnect.props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.resolveDisconnectGoogle({ success: true, marker: 'stale-disconnect-a' })
    await disconnectPromise
    expect(harness.apiCalls.find((call) => call.method === 'disconnectGoogleDrive')?.owner).toBe('owner-a')
    expect(harness.apiCalls.find((call) => call.method === 'disconnectGoogleDrive')?.args[0]).toMatchObject({ authToken: 'token-a' })
    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value)).not.toContainEqual(expect.objectContaining({ connected: false, scope: null }))
  })

  it('suppresses a stale Drive disconnect error after an owner switch', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const disconnect = findButton(harness.getRoot(), 'Disconnect Google Drive')
    const disconnectPromise = disconnect.props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    const updatesBeforeRelease = harness.stateUpdates.length
    harness.rejectDisconnectGoogle(new Error('stale disconnect failure'))
    await disconnectPromise
    // Setters record { index, value }, and errors are rendered as strings. An
    // Error-instance assertion would pass even if stale catch/finally ran.
    expect(harness.stateUpdates.slice(updatesBeforeRelease)).toEqual([])
  })

  it('applies a current-owner Drive disconnect response', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const disconnect = findButton(harness.getRoot(), 'Disconnect Google Drive')
    const callsBefore = harness.apiCalls.length
    const disconnectPromise = disconnect.props.onClick()
    harness.resolveDisconnectGoogle({ success: true })
    await disconnectPromise
    const call = harness.apiCalls.slice(callsBefore).find((entry) => entry.method === 'disconnectGoogleDrive')
    expect(call?.args[0]).toMatchObject({ authToken: 'token-a' })
    expect(harness.stateUpdates.map(({ value }) => value)).toContainEqual(expect.objectContaining({ connected: false, scope: null }))
  })

  it('blocks a held Drive disconnect response after A→B', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('connected')
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const updatesBefore = harness.stateUpdates.length
    const disconnectPromise = findButton(harness.getRoot(), 'Disconnect Google Drive').props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.resolveDisconnectGoogle({ success: true })
    await disconnectPromise
    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value)).not.toContainEqual(expect.objectContaining({ connected: false, scope: null }))
  })

  it('blocks a held GitHub disconnect response after A→B→A', async () => {
    const harness = await loadHarness()
    harness.render()
    harness.runEffects()
    await settle()
    harness.render()
    const disconnect = findButton(harness.getRoot(), 'Disconnect')
    const updatesBefore = harness.stateUpdates.length
    const disconnectPromise = disconnect.props.onClick()
    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.resolveDisconnectGithub({ success: true })
    await disconnectPromise
    expect(harness.apiCalls.find((call) => call.method === 'disconnectGitHub')?.owner).toBe('owner-a')
    expect(harness.apiCalls.find((call) => call.method === 'disconnectGitHub')?.args[0]).toMatchObject({ authToken: 'token-a' })
    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value)).not.toContainEqual(expect.objectContaining({ connected: false, username: null }))
  })

  it('allows a current-owner Drive retry response', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const retry = findButton(harness.getRoot(), 'Retry')
    const callsBefore = harness.apiCalls.length
    const retryPromise = retry.props.onClick()
    harness.resolveGoogle({ connected: true, scope: 'drive.file', marker: 'current-a' })
    await retryPromise
    expect(harness.stateUpdates.map(({ value }) => value)).toContainEqual(expect.objectContaining({ marker: 'current-a' }))
    const retryCall = harness.apiCalls.slice(callsBefore).find((call) => call.method === 'getGoogleDriveStatus')
    expect(retryCall?.args[0]).toMatchObject({ authToken: 'token-a' })
  })

  it('invalidates a held retry after token rotation for the same user', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const pending = findButton(harness.getRoot(), 'Retry').props.onClick()
    const updatesBefore = harness.stateUpdates.length
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'rotated-token-a' } })
    harness.render()
    harness.resolveGoogle({ connected: true, marker: 'stale-token' })
    await pending
    expect(harness.stateUpdates.slice(updatesBefore).map(({ value }) => value))
      .not.toContainEqual(expect.objectContaining({ marker: 'stale-token' }))
  })

  it('admits a fresh action after a same-owner lifecycle cleanup/setup replay', async () => {
    const harness = await loadHarness()
    harness.setGoogleStatusMode('error')
    harness.render()
    harness.runEffects()
    await settle()
    harness.cleanupEffects()
    harness.render()
    harness.runEffects()
    await settle()
    harness.setGoogleStatusMode('held')
    harness.render()
    const pending = findButton(harness.getRoot(), 'Retry').props.onClick()
    harness.resolveGoogle({ connected: true, marker: 'replayed-current' })
    await pending
    expect(harness.stateUpdates.map(({ value }) => value))
      .toContainEqual(expect.objectContaining({ marker: 'replayed-current' }))
  })
})
