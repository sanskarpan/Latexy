import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext, NotificationPrefs } from '../lib/api-client'

type VNode = { type: unknown; props: Record<string, any> }
type Session = { user: { id: string }; session: { token: string } }
type HookSlot =
  | { kind: 'state'; value: unknown }
  | { kind: 'ref'; value: { current: unknown } }
  | { kind: 'effect'; deps: unknown[] | undefined; cleanup?: () => void }

const prefs = (jobCompleted: boolean): NotificationPrefs => ({
  job_completed: jobCompleted,
  job_failed: true,
  share_viewed: false,
  weekly_digest: false,
  tracker_updates: true,
  comment_mentions: true,
})

function walk(root: unknown, visit: (node: VNode) => boolean): VNode | null {
  if (Array.isArray(root)) {
    for (const child of root) {
      const match = walk(child, visit)
      if (match) return match
    }
    return null
  }
  if (!root || typeof root !== 'object' || !('props' in root)) return null
  const node = root as VNode
  if (visit(node)) return node
  return walk(node.props.children, visit)
}

function findToggle(root: VNode): VNode {
  const match = walk(root, (node) => node.props.role === 'switch' && node.props['aria-label'] === 'Job completion emails')
  if (!match) throw new Error('Job completion emails switch not found')
  return match
}

function textContent(root: unknown): string {
  if (typeof root === 'string' || typeof root === 'number') return String(root)
  if (Array.isArray(root)) return root.map(textContent).join('')
  if (!root || typeof root !== 'object' || !('props' in root)) return ''
  return textContent((root as VNode).props.children)
}

function hasExactText(root: VNode, target: string): boolean {
  return Boolean(walk(root, (node) => textContent(node) === target))
}

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: Error) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

type Harness = {
  render: () => VNode
  runEffects: () => void
  cleanup: () => void
  setSession: (session: Session) => void
  setAuthState: (pending: boolean, error?: Error | null) => void
  getCalls: Array<{ owner: string; context?: AccountPreferenceRequestContext }>
  putCalls: Array<{ owner: string; prefs: NotificationPrefs; context?: AccountPreferenceRequestContext }>
  deferNextPut: (gate: Deferred<NotificationPrefs>) => void
  stateUpdates: unknown[]
}

async function loadHarness(initialACompleted = false): Promise<Harness> {
  vi.resetModules()
  let session: Session = { user: { id: 'owner-a' }, session: { token: 'token-a' } }
  let sessionPending = false
  let sessionError: Error | null = null
  let hookIndex = 0
  const slots: HookSlot[] = []
  let pendingEffects: Array<{ index: number; effect: () => void | (() => void); deps: unknown[] | undefined }> = []
  const stateUpdates: unknown[] = []
  const getCalls: Harness['getCalls'] = []
  const putCalls: Harness['putCalls'] = []
  let deferredPut: Deferred<NotificationPrefs> | null = null

  const apiClient = {
    getNotificationPrefs: vi.fn((context?: AccountPreferenceRequestContext) => {
      const owner = session.user.id
      getCalls.push({ owner, context })
      return Promise.resolve(prefs(owner === 'owner-a' ? initialACompleted : false))
    }),
    updateNotificationPrefs: vi.fn((next: NotificationPrefs, context?: AccountPreferenceRequestContext) => {
      const owner = session.user.id
      putCalls.push({ owner, prefs: next, context })
      if (deferredPut) {
        const current = deferredPut
        deferredPut = null
        return current.promise
      }
      return Promise.resolve(next)
    }),
    getGitHubStatus: vi.fn().mockResolvedValue({ connected: false, username: null, public_import: false, private_sync: false }),
    getZoteroStatus: vi.fn().mockResolvedValue({ connected: false }),
    getMendeleyStatus: vi.fn().mockResolvedValue({ connected: false }),
    getDropboxStatus: vi.fn().mockResolvedValue({ connected: false }),
    getGoogleDriveStatus: vi.fn().mockResolvedValue({ connected: false, scope: null }),
    disconnectGoogleDrive: vi.fn().mockResolvedValue({ success: true }),
    disconnectGitHub: vi.fn().mockResolvedValue({ success: true }),
    disconnectZotero: vi.fn().mockResolvedValue({ success: true }),
    disconnectDropbox: vi.fn().mockResolvedValue({ success: true }),
    disconnectMendeley: vi.fn().mockResolvedValue({ success: true }),
    startGitHubOAuth: vi.fn(),
    startZoteroOAuth: vi.fn(),
    startDropboxOAuth: vi.fn(),
    startGoogleDriveOAuth: vi.fn(),
    startMendeleyOAuth: vi.fn(),
    completeGitHubOAuth: vi.fn(),
    completeZoteroOAuth: vi.fn(),
    completeMendeleyOAuth: vi.fn(),
    completeDropboxOAuth: vi.fn(),
    completeGoogleDriveOAuth: vi.fn(),
  }

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
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const index = hookIndex++
      const previous = slots[index]
      const changed = deps === undefined
        || !previous
        || previous.kind !== 'effect'
        || previous.deps === undefined
        || deps.length !== previous.deps.length
        || deps.some((value, depIndex) => !Object.is(value, previous.deps?.[depIndex]))
      if (changed) pendingEffects.push({ index, effect, deps })
    },
    useRef: (initial: unknown) => {
      const index = hookIndex++
      if (!slots[index]) slots[index] = { kind: 'ref', value: { current: initial } }
      return (slots[index] as Extract<HookSlot, { kind: 'ref' }>).value
    },
    useState: (initial: unknown) => {
      const index = hookIndex++
      if (!slots[index]) slots[index] = { kind: 'state', value: initial }
      const slot = slots[index] as Extract<HookSlot, { kind: 'state' }>
      return [slot.value, (value: unknown) => {
        slot.value = typeof value === 'function'
          ? (value as (previous: unknown) => unknown)(slot.value)
          : value
        stateUpdates.push(slot.value)
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
  vi.doMock('@/lib/api-client', () => ({ apiClient }))

  const page = (await import('../app/settings/page')).default() as VNode
  const content = page.props.children as VNode
  const render = () => {
    hookIndex = 0
    pendingEffects = []
    return (content.type as () => VNode)()
  }
  const runEffects = () => {
    const effects = pendingEffects
    pendingEffects = []
    for (const entry of effects) {
      const previous = slots[entry.index]
      if (previous?.kind === 'effect') previous.cleanup?.()
      const cleanup = entry.effect()
      slots[entry.index] = { kind: 'effect', deps: entry.deps, cleanup: cleanup || undefined }
    }
  }
  const cleanup = () => {
    for (let index = slots.length - 1; index >= 0; index -= 1) {
      const slot = slots[index]
      if (slot?.kind === 'effect') {
        slot.cleanup?.()
        slots[index] = { ...slot, cleanup: undefined }
      }
    }
  }
  render()
  runEffects()

  return {
    render,
    runEffects,
    cleanup,
    setSession: (next) => { session = next },
    setAuthState: (pending, error = null) => { sessionPending = pending; sessionError = error },
    getCalls,
    putCalls,
    deferNextPut: (gate) => { deferredPut = gate },
    stateUpdates,
  }
}

async function settle() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

async function renderSettled(harness: Harness): Promise<VNode> {
  await settle()
  return harness.render()
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

describe('Settings notification owner state', () => {
  it.each(['success', 'failure'] as const)('does not apply A PUT %s to B after a session switch', async (outcome) => {
    const harness = await loadHarness(outcome === 'failure')
    await renderSettled(harness)
    const aGate = deferred<NotificationPrefs>()
    harness.deferNextPut(aGate)
    const aToggle = findToggle(harness.render())
    const pendingA = aToggle.props.onClick() as Promise<void>
    expect(harness.putCalls[0].owner).toBe('owner-a')

    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    const bRoot = await renderSettled(harness)
    expect(findToggle(bRoot).props['aria-checked']).toBe(false)

    if (outcome === 'success') aGate.resolve(prefs(true))
    else aGate.reject(new Error('Synthetic A save failure'))
    await pendingA
    const afterOldA = harness.render()
    expect(findToggle(afterOldA).props['aria-checked']).toBe(false)
    expect(hasExactText(afterOldA, 'Saved')).toBe(false)
    expect(textContent(afterOldA)).not.toContain('Synthetic A save failure')
  })

  it('blocks an A→B→A stale completion using the owner epoch, even when A token is reused', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const gate = deferred<NotificationPrefs>()
    harness.deferNextPut(gate)
    const pendingA = findToggle(harness.render()).props.onClick() as Promise<void>

    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    await renderSettled(harness)
    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a' } })
    harness.render()
    harness.runEffects()
    const freshA = await renderSettled(harness)
    expect(findToggle(freshA).props['aria-checked']).toBe(false)

    gate.resolve(prefs(true))
    await pendingA
    expect(findToggle(harness.render()).props['aria-checked']).toBe(false)
  })

  it('does not clear B saving state when an old A request finishes', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const aGate = deferred<NotificationPrefs>()
    harness.deferNextPut(aGate)
    const pendingA = findToggle(harness.render()).props.onClick() as Promise<void>

    harness.setSession({ user: { id: 'owner-b' }, session: { token: 'token-b' } })
    harness.render()
    harness.runEffects()
    await renderSettled(harness)
    const bGate = deferred<NotificationPrefs>()
    harness.deferNextPut(bGate)
    const pendingB = findToggle(harness.render()).props.onClick() as Promise<void>

    aGate.resolve(prefs(true))
    await pendingA
    expect(textContent(harness.render())).toContain('Saving…')

    bGate.resolve(prefs(true))
    await pendingB
    expect(textContent(harness.render())).not.toContain('Saving…')
  })

  it('does not let an old Saved timer clear a newer same-owner save notice', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const firstSave = findToggle(harness.render()).props.onClick() as Promise<void>
    await firstSave
    await vi.advanceTimersByTimeAsync(1000)

    const secondSave = findToggle(harness.render()).props.onClick() as Promise<void>
    await secondSave
    expect(hasExactText(harness.render(), 'Saved')).toBe(true)
    await vi.advanceTimersByTimeAsync(1001)
    expect(hasExactText(harness.render(), 'Saved')).toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(hasExactText(harness.render(), 'Saved')).toBe(false)
  })

  it('rejects a duplicate saved-handler dispatch before rerender and gates stale handlers during auth error', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const gate = deferred<NotificationPrefs>()
    harness.deferNextPut(gate)
    const oldHandler = findToggle(harness.render()).props.onClick as () => Promise<void>
    const pending = oldHandler()
    await oldHandler()
    expect(harness.putCalls).toHaveLength(1)

    harness.setAuthState(false, new Error('synthetic refresh error'))
    harness.render()
    await oldHandler()
    expect(harness.putCalls).toHaveLength(1)
    gate.resolve(prefs(true))
    await pending
  })

  it('ignores deferred results after unmount', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const gate = deferred<NotificationPrefs>()
    harness.deferNextPut(gate)
    const pending = findToggle(harness.render()).props.onClick() as Promise<void>
    const updatesAtUnmount = harness.stateUpdates.length
    harness.cleanup()
    gate.resolve(prefs(true))
    await pending
    expect(harness.stateUpdates).toHaveLength(updatesAtUnmount)
  })

  it('retains a same-owner optimistic draft across token refresh and clears a recovered read error', async () => {
    const harness = await loadHarness(false)
    await renderSettled(harness)
    const gate = deferred<NotificationPrefs>()
    harness.deferNextPut(gate)
    const pending = findToggle(harness.render()).props.onClick() as Promise<void>

    harness.setSession({ user: { id: 'owner-a' }, session: { token: 'token-a-refreshed' } })
    harness.render()
    harness.runEffects()
    const refreshed = await renderSettled(harness)
    expect(findToggle(refreshed).props['aria-checked']).toBe(true)
    expect(harness.getCalls[harness.getCalls.length - 1]?.context?.authToken).toBe('token-a-refreshed')

    gate.resolve(prefs(true))
    await pending
    expect(findToggle(harness.render()).props['aria-checked']).toBe(true)
  })
})
