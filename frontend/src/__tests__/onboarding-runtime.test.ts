import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

type Scope = { ownerId: string | null; authToken: string; confirmed: boolean }
type HookResult = ReturnType<typeof import('@/components/onboarding/OnboardingFlow').useOnboarding>
type Effect = () => void | (() => void)
type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void }

const mocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  updateMePreferences: vi.fn(),
  react: {
    useState: vi.fn(),
    useEffect: vi.fn(),
    useRef: vi.fn(),
    useCallback: vi.fn(),
  },
}))

vi.mock('react', () => ({ default: mocks.react, ...mocks.react }))
vi.mock('framer-motion', () => ({
  AnimatePresence: 'AnimatePresence',
  motion: { div: 'div' },
  useReducedMotion: () => false,
}))
vi.mock('lucide-react', () => ({}))
vi.mock('next/link', () => ({ default: 'a' }))
vi.mock('@/components/I18nProvider', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    getMe: mocks.getMe,
    updateMePreferences: mocks.updateMePreferences,
  },
}))

let useOnboarding: typeof import('@/components/onboarding/OnboardingFlow').useOnboarding

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function me(hasOnboarded: boolean) {
  return {
    id: 'runtime-owner',
    email: 'runtime@example.invalid',
    plan: 'free',
    role: 'user' as const,
    preferences: { has_onboarded: hasOnboarded },
  }
}

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

type Harness = {
  scope: Scope
  result: HookResult
  render: () => HookResult
  commit: (force?: boolean) => void
  mountStrict: () => void
  unmount: () => void
}

function createHarness(initialScope: Scope | undefined): Harness {
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  const callbacks: Array<{ deps: unknown[] | undefined; value: unknown }> = []
  const effects: Array<{ deps: unknown[] | undefined; cleanup?: () => void }> = []
  let hookIndex = 0
  let pendingEffects: Array<{ index: number; effect: Effect; deps: unknown[] | undefined; changed: boolean }> = []
  let result!: HookResult
  const harness = {
    scope: initialScope ? { ...initialScope } : { ownerId: null, authToken: '', confirmed: false },
    result: undefined as unknown as HookResult,
    render: () => result,
    commit: (_force = false) => {},
    mountStrict: () => {},
    unmount: () => {},
  } as Harness
  mocks.react.useState.mockImplementation((initial: unknown) => {
    const index = hookIndex++
    if (!(index in states)) states[index] = initial
    const setState = (value: unknown | ((previous: unknown) => unknown)) => {
      states[index] = typeof value === 'function'
        ? (value as (previous: unknown) => unknown)(states[index])
        : value
    }
    return [states[index], setState]
  })
  mocks.react.useRef.mockImplementation((initial: unknown) => {
    const index = hookIndex++
    refs[index] ??= { current: initial }
    return refs[index]
  })
  mocks.react.useCallback.mockImplementation((callback: unknown, deps: unknown[] | undefined) => {
    const index = hookIndex++
    const previous = callbacks[index]
    const changed = !previous || !deps || !previous.deps || deps.length !== previous.deps.length ||
      deps.some((value, depIndex) => !Object.is(value, previous.deps?.[depIndex]))
    if (changed) callbacks[index] = { deps, value: callback }
    return callbacks[index].value
  })
  mocks.react.useEffect.mockImplementation((effect: Effect, deps?: unknown[]) => {
    const index = hookIndex++
    const previous = effects[index]
    const changed = !previous || !deps || !previous.deps || deps.length !== previous.deps.length ||
      deps.some((value, depIndex) => !Object.is(value, previous.deps?.[depIndex]))
    pendingEffects.push({ index, effect, deps, changed })
  })

  harness.render = () => {
    hookIndex = 0
    pendingEffects = []
    // The indexed harness deliberately invokes the real hook body outside a
    // component renderer so deferred effects and cleanups can be controlled.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    result = initialScope === undefined ? useOnboarding() : useOnboarding(harness.scope)
    harness.result = result
    return result
  }
  harness.commit = (force = false) => {
    for (const pending of pendingEffects) {
      if (!force && !pending.changed) continue
      effects[pending.index]?.cleanup?.()
      const cleanup = pending.effect()
      effects[pending.index] = {
        deps: pending.deps,
        cleanup: typeof cleanup === 'function' ? cleanup : undefined,
      }
    }
  }
  harness.mountStrict = () => {
    harness.render()
    harness.commit()
    harness.unmount()
    harness.render()
    harness.commit(true)
  }
  harness.unmount = () => {
    for (const effect of effects) {
      effect?.cleanup?.()
      if (effect) effect.cleanup = undefined
    }
  }
  return harness
}

beforeAll(async () => {
  ({ useOnboarding } = await import('@/components/onboarding/OnboardingFlow'))
})

beforeEach(() => {
  const store: Record<string, string> = {}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
  })
  mocks.getMe.mockReset()
  mocks.updateMePreferences.mockReset()
  mocks.updateMePreferences.mockResolvedValue(me(true))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useOnboarding runtime lifecycle', () => {
  it('reconciles signed-in false and true accounts only after the account body resolves', async () => {
    const falseRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(falseRead.promise)
    const first = createHarness({ ownerId: 'account-b', authToken: 'token-b', confirmed: true })
    first.render()
    first.commit()
    expect(first.result.onboardingReady).toBe(false)
    falseRead.resolve(me(false))
    await settle()
    first.render()
    first.commit()
    expect(first.result.onboardingReady).toBe(true)
    expect(first.result.hasCompletedOnboarding).toBe(false)

    const trueRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(trueRead.promise)
    const second = createHarness({ ownerId: 'account-c', authToken: 'token-c', confirmed: true })
    second.render()
    second.commit()
    trueRead.resolve(me(true))
    await settle()
    second.render()
    second.commit()
    expect(second.result.onboardingReady).toBe(true)
    expect(second.result.hasCompletedOnboarding).toBe(true)
    expect(second.result.isOnboardingOpen).toBe(false)
  })

  it('uses legacy storage only for confirmed anonymous state and keeps owner cache offline', async () => {
    localStorage.setItem('latexy_onboarding_completed', 'true')
    const anonymous = createHarness({ ownerId: null, authToken: '', confirmed: true })
    anonymous.render()
    anonymous.commit()
    expect(anonymous.result.hasCompletedOnboarding).toBe(true)
    expect(mocks.getMe).not.toHaveBeenCalled()

    const ownerRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(ownerRead.promise)
    const owner = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    owner.render()
    owner.commit()
    ownerRead.reject(new Error('offline'))
    await settle()
    owner.render()
    owner.commit()
    expect(owner.result.onboardingReady).toBe(true)
    // The owner must not inherit the anonymous global completion flag; the
    // initial latch remains closed on an unknown offline state.
    expect(owner.result.hasCompletedOnboarding).toBe(true)

    const serverNotCompleted = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(serverNotCompleted.promise)
    const signedInOwner = createHarness({ ownerId: 'account-b', authToken: 'token-b', confirmed: true })
    signedInOwner.render()
    signedInOwner.commit()
    serverNotCompleted.resolve(me(false))
    await settle()
    signedInOwner.render()
    signedInOwner.commit()
    signedInOwner.render()
    expect(signedInOwner.result.hasCompletedOnboarding).toBe(false)
    expect(localStorage.getItem('latexy_onboarding_completed')).toBe('true')
    expect(localStorage.getItem('latexy_onboarding_completed:account-b')).toBeNull()
  })

  it('preserves no-argument anonymous completion and reset locally without account API calls', () => {
    localStorage.setItem('latexy_onboarding_completed', 'true')
    const harness = createHarness(undefined)
    harness.render()
    harness.commit()
    harness.render()
    expect(harness.result.hasCompletedOnboarding).toBe(true)
    expect(harness.result.onboardingReady).toBe(true)

    harness.result.resetOnboarding()
    harness.render()
    expect(localStorage.getItem('latexy_onboarding_completed')).toBeNull()
    expect(harness.result.hasCompletedOnboarding).toBe(false)
    harness.result.startOnboarding()
    harness.render()
    expect(harness.result.isOnboardingOpen).toBe(true)
    harness.result.skipOnboarding()
    harness.render()
    expect(localStorage.getItem('latexy_onboarding_completed')).toBe('true')
    expect(harness.result.isOnboardingOpen).toBe(false)
    expect(mocks.getMe).not.toHaveBeenCalled()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
  })

  it('keeps explicit anonymous fallback local and prevents it while auth is pending', () => {
    const anonymous = createHarness({ ownerId: null, authToken: '', confirmed: true })
    anonymous.render()
    anonymous.commit()
    anonymous.result.completeOnboarding()
    anonymous.render()
    expect(localStorage.getItem('latexy_onboarding_completed')).toBe('true')
    expect(mocks.getMe).not.toHaveBeenCalled()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()

    const pending = createHarness({ ownerId: null, authToken: '', confirmed: false })
    pending.render()
    pending.commit()
    pending.result.startOnboarding()
    pending.result.skipOnboarding()
    pending.result.resetOnboarding()
    expect(pending.result.onboardingReady).toBe(false)
    expect(pending.result.isOnboardingOpen).toBe(false)
    expect(localStorage.getItem('latexy_onboarding_completed')).toBe('true')
    expect(mocks.getMe).not.toHaveBeenCalled()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
  })

  it('rejects deferred A/B/ABA reads using the render-time owner generation', async () => {
    const reads = [deferred<ReturnType<typeof me>>(), deferred<ReturnType<typeof me>>(), deferred<ReturnType<typeof me>>()]
    mocks.getMe.mockImplementation(() => reads[mocks.getMe.mock.calls.length - 1].promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    harness.scope = { ownerId: 'account-b', authToken: 'token-b', confirmed: true }
    harness.render()
    harness.commit()
    harness.scope = { ownerId: 'account-a', authToken: 'token-a-2', confirmed: true }
    harness.render()
    harness.commit()
    reads[0].resolve(me(false))
    reads[1].resolve(me(false))
    await settle()
    reads[2].resolve(me(true))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.hasCompletedOnboarding).toBe(true)
    expect(mocks.getMe.mock.calls).toHaveLength(3)
    expect(mocks.getMe.mock.calls[0][0].isCurrent()).toBe(false)
    expect(mocks.getMe.mock.calls[1][0].isCurrent()).toBe(false)
    expect(mocks.getMe.mock.calls[2][0].isCurrent()).toBe(true)
  })

  it('rejects saved A callbacks immediately after B render, before passive effects run', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValue(read.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    const staleStart = harness.result.startOnboarding
    const staleComplete = harness.result.completeOnboarding
    const staleReset = harness.result.resetOnboarding

    harness.scope = { ownerId: 'account-b', authToken: 'token-b', confirmed: true }
    harness.render()
    staleStart()
    staleComplete()
    staleReset()

    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
    expect(localStorage.getItem('latexy_onboarding_completed:account-a')).toBeNull()
    expect(localStorage.getItem('latexy_onboarding_replay:account-a')).toBeNull()
    expect(harness.result.onboardingReady).toBe(false)
    expect(harness.result.hasCompletedOnboarding).toBe(true)
    read.resolve(me(false))
    await settle()
  })

  it('masks A readiness and completion while B is rendered before B reconciliation', async () => {
    const aRead = deferred<ReturnType<typeof me>>()
    const bRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(aRead.promise).mockReturnValueOnce(bRead.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    aRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    expect(harness.result.hasCompletedOnboarding).toBe(false)

    harness.scope = { ownerId: 'account-b', authToken: 'token-b', confirmed: true }
    harness.render()
    expect(harness.result.onboardingReady).toBe(false)
    expect(harness.result.hasCompletedOnboarding).toBe(true)
    harness.commit()
    expect(mocks.getMe).toHaveBeenCalledTimes(2)
    harness.render()
    harness.commit()
    expect(mocks.getMe).toHaveBeenCalledTimes(2)
    bRead.resolve(me(true))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    expect(harness.result.hasCompletedOnboarding).toBe(true)
  })

  it('rejects saved same-owner callbacks after confirmation loss or token rotation', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(read.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    read.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    const staleSkip = harness.result.skipOnboarding
    const staleReset = harness.result.resetOnboarding
    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: false }
    harness.render()
    staleSkip()
    staleReset()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
    expect(localStorage.getItem('latexy_onboarding_completed:account-a')).toBeNull()

    harness.scope = { ownerId: 'account-a', authToken: 'token-a-rotated', confirmed: true }
    harness.render()
    staleSkip()
    staleReset()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(1)
  })

  it('invalidates stale reads on unmount without changing owner cache or current state', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValue(read.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    const context = mocks.getMe.mock.calls[0][0] as { isCurrent: () => boolean }
    harness.unmount()
    expect(context.isCurrent()).toBe(false)
    read.resolve(me(true))
    await settle()
    expect(localStorage.getItem('latexy_onboarding_completed:account-a')).toBeNull()
  })

  it('keeps explicit owner replay ahead of a stale true read across navigation', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(read.promise)
    const settings = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    settings.render()
    settings.commit()
    settings.result.resetOnboarding()
    expect(localStorage.getItem('latexy_onboarding_replay:account-a')).toBe('true')
    expect(mocks.updateMePreferences).toHaveBeenCalledWith(
      { has_onboarded: false },
      expect.objectContaining({ authToken: 'token-a' }),
    )
    read.resolve(me(true))
    await settle()
    settings.render()
    settings.commit()
    expect(settings.result.hasCompletedOnboarding).toBe(false)
    expect(settings.result.isOnboardingOpen).toBe(true)

    settings.unmount()
    const workspaceRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(workspaceRead.promise)
    const workspace = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    workspace.render()
    workspace.commit()
    workspaceRead.resolve(me(true))
    await settle()
    workspace.render()
    workspace.commit()
    expect(workspace.result.hasCompletedOnboarding).toBe(false)
    expect(workspace.result.isOnboardingOpen).toBe(true)
  })

  it('does not reload or reset current state on a same-owner token refresh', async () => {
    const read = deferred<ReturnType<typeof me>>()
    const retriedRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(read.promise).mockReturnValueOnce(retriedRead.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    harness.scope = { ownerId: 'account-a', authToken: 'token-a-rotated', confirmed: true }
    harness.render()
    harness.commit()
    expect(mocks.getMe.mock.calls[0][0].isCurrent()).toBe(false)
    expect(mocks.getMe).toHaveBeenCalledTimes(2)
    expect(mocks.getMe.mock.calls[1][0]).toMatchObject({ authToken: 'token-a-rotated' })
    read.resolve(me(true))
    retriedRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.hasCompletedOnboarding).toBe(false)
    expect(mocks.getMe.mock.calls[1][0].isCurrent()).toBe(true)
  })

  it('keeps a ready tour state through a same-owner token refresh without another GET', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(read.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    read.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    harness.scope = { ownerId: 'account-a', authToken: 'token-a-rotated', confirmed: true }
    harness.render()
    harness.commit()
    expect(mocks.getMe).toHaveBeenCalledTimes(1)
    expect(harness.result.onboardingReady).toBe(true)
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(1)
  })

  it('preserves ready state through same-owner confirmation loss while gating actions', async () => {
    const read = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(read.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    read.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: false }
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).not.toHaveBeenCalled()
    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: true }
    harness.render()
    harness.commit()
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(1)
  })

  it('requires confirmation at request dispatch and preserves same-owner dispatched tour state', async () => {
    const firstRead = deferred<ReturnType<typeof me>>()
    const confirmedRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(firstRead.promise).mockReturnValueOnce(confirmedRead.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    const initialGetContext = mocks.getMe.mock.calls[0][0] as { isCurrent: () => boolean }
    expect(initialGetContext.isCurrent()).toBe(true)

    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: false }
    harness.render()
    // Check before passive effects invalidate the request revision: the auth
    // gate itself must prevent a request from dispatching without confirmation.
    expect(initialGetContext.isCurrent()).toBe(false)
    harness.commit()
    firstRead.resolve(me(true))
    await settle()

    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: true }
    harness.render()
    harness.commit()
    confirmedRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)

    harness.result.resetOnboarding()
    const updateContext = mocks.updateMePreferences.mock.calls[0][1] as { isCurrent: () => boolean }
    expect(updateContext.isCurrent()).toBe(true)
    harness.scope = { ownerId: 'account-a', authToken: 'token-a', confirmed: false }
    harness.render()
    expect(updateContext.isCurrent()).toBe(false)
    expect(harness.result.onboardingReady).toBe(true)
    expect(harness.result.isOnboardingOpen).toBe(true)
    harness.commit()
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    expect(harness.result.isOnboardingOpen).toBe(true)
  })

  it('releases an old action without clearing a newer owner action', async () => {
    const firstRead = deferred<ReturnType<typeof me>>()
    const secondRead = deferred<ReturnType<typeof me>>()
    const thirdRead = deferred<ReturnType<typeof me>>()
    const firstWrite = deferred<ReturnType<typeof me>>()
    const secondWrite = deferred<ReturnType<typeof me>>()
    const thirdWrite = deferred<ReturnType<typeof me>>()
    mocks.getMe
      .mockReturnValueOnce(firstRead.promise)
      .mockReturnValueOnce(secondRead.promise)
      .mockReturnValueOnce(thirdRead.promise)
    mocks.updateMePreferences
      .mockReturnValueOnce(firstWrite.promise)
      .mockReturnValueOnce(secondWrite.promise)
      .mockReturnValueOnce(thirdWrite.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.render()
    harness.commit()
    firstRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(1)

    harness.scope = { ownerId: 'account-b', authToken: 'token-b', confirmed: true }
    harness.render()
    harness.commit()
    harness.scope = { ownerId: 'account-a', authToken: 'token-a-2', confirmed: true }
    harness.render()
    harness.commit()
    secondRead.resolve(me(false))
    thirdRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(2)

    firstWrite.resolve(me(true))
    await settle()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(2)
    harness.result.resetOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(2)
    secondWrite.resolve(me(true))
    await settle()
    harness.result.resetOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(3)
    thirdWrite.resolve(me(false))
    await settle()
  })

  it('allows Strict Mode GET replay but prevents duplicate preference mutations', async () => {
    const firstRead = deferred<ReturnType<typeof me>>()
    const secondRead = deferred<ReturnType<typeof me>>()
    mocks.getMe.mockReturnValueOnce(firstRead.promise).mockReturnValueOnce(secondRead.promise)
    const harness = createHarness({ ownerId: 'account-a', authToken: 'token-a', confirmed: true })
    harness.mountStrict()
    expect(mocks.getMe).toHaveBeenCalledTimes(2)
    firstRead.resolve(me(false))
    secondRead.resolve(me(false))
    await settle()
    harness.render()
    harness.commit()
    expect(harness.result.onboardingReady).toBe(true)
    harness.result.skipOnboarding()
    harness.result.skipOnboarding()
    expect(mocks.updateMePreferences).toHaveBeenCalledTimes(1)
    expect(mocks.updateMePreferences).toHaveBeenCalledWith(
      { has_onboarded: true },
      expect.objectContaining({ authToken: 'token-a' }),
    )
  })
})
