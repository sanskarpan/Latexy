import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

const availableBillingStatus = {
  provider: 'dodo' as const, featureEnabled: true,
  mode: 'enabled' as const,
  available: true,
  reason: null,
  message: 'Available',
}

function findButton(node: unknown, label: string): VNode | null {
  if (!node || typeof node !== 'object') return null
  const candidate = node as VNode
  if (candidate.type === 'button' && candidate.props.children === label) return candidate
  const children = candidate.props?.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findButton(child, label)
      if (found) return found
    }
  } else {
    return findButton(children, label)
  }
  return null
}

function hasAlert(node: unknown, message: string): boolean {
  if (!node || typeof node !== 'object') return false
  const candidate = node as VNode
  if (candidate.props?.role === 'alert' && candidate.props.children === message) return true
  const children = candidate.props?.children
  return Array.isArray(children)
    ? children.some(child => hasAlert(child, message))
    : hasAlert(children, message)
}

afterEach(() => {
  vi.useRealTimers()
  vi.doUnmock('react')
  vi.doUnmock('react/jsx-runtime')
  vi.doUnmock('@/lib/api-client')
  vi.resetModules()
})

describe('billing checkout reconciliation', () => {
  it('keeps Free access on reconciliation network errors and exposes an authenticated retry', async () => {
    vi.useFakeTimers()
    const freeSubscription = {
      userId: 'user-1', planId: 'free', planName: 'Free', status: 'checkout_pending',
      features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
    }
    const getCurrentSubscription = vi.fn().mockResolvedValue({ success: true, data: freeSubscription })
    const reconcileSubscription = vi.fn().mockResolvedValue({ success: false, error: 'network unavailable' })
    const effects: Array<() => void | (() => void)> = []
    const states: unknown[] = []
    const refs: Array<{ current: unknown }> = []
    let hookIndex = 0

    vi.doMock('react', () => ({
      useCallback: (callback: unknown) => callback,
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
    vi.doMock('@/lib/api-client', () => ({
      apiClient: { getCurrentSubscription, reconcileSubscription },
    }))

    const SubscriptionManager = (await import('../components/billing/SubscriptionManager')).default
    const onLoaded = vi.fn()
    const props = {
      authToken: 'session-token',
      billingStatus: availableBillingStatus,
      checkoutReturned: true,
      onUpgrade: vi.fn(),
      onLoaded,
    }
    hookIndex = 0
    SubscriptionManager(props)
    const cleanup = effects[0]()
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    expect(reconcileSubscription).toHaveBeenCalledTimes(1)
    expect(getCurrentSubscription).toHaveBeenCalledTimes(1)
    expect(onLoaded).toHaveBeenLastCalledWith(freeSubscription)

    hookIndex = 0
    const pendingView = SubscriptionManager(props) as VNode
    const retry = findButton(pendingView, 'Check payment status')
    expect(retry).not.toBeNull()
    expect(hasAlert(pendingView, 'network unavailable')).toBe(true)

    await (retry!.props.onClick as () => void)()
    await Promise.resolve()
    await Promise.resolve()
    expect(reconcileSubscription).toHaveBeenCalledTimes(2)
    expect(getCurrentSubscription).toHaveBeenCalledTimes(2)
    expect(onLoaded).toHaveBeenLastCalledWith(freeSubscription)

    hookIndex = 0
    const failedRetryView = SubscriptionManager(props) as VNode
    expect(findButton(failedRetryView, 'Check payment status')).not.toBeNull()
    expect(hasAlert(failedRetryView, 'network unavailable')).toBe(true)
    cleanup?.()
  })

  it('does not reconcile or offer manual reconciliation without an authenticated session token', async () => {
    vi.useFakeTimers()
    const freeSubscription = {
      userId: 'user-1', planId: 'free', planName: 'Free', status: 'active',
      features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
    }
    const getCurrentSubscription = vi.fn().mockResolvedValue({ success: true, data: freeSubscription })
    const reconcileSubscription = vi.fn()
    const effects: Array<() => void | (() => void)> = []
    const states: unknown[] = []
    const refs: Array<{ current: unknown }> = []
    let hookIndex = 0

    vi.doMock('react', () => ({
      useCallback: (callback: unknown) => callback,
      useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
      useRef: (initial: unknown) => {
        const index = hookIndex++
        refs[index] ??= { current: initial }
        return refs[index]
      },
      useState: (initial: unknown) => {
        const index = hookIndex++
        if (!(index in states)) states[index] = initial
        return [states[index], (value: unknown) => { states[index] = value }]
      },
    }))
    vi.doMock('react/jsx-runtime', () => ({
      jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
      jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    }))
    vi.doMock('@/lib/api-client', () => ({
      apiClient: { getCurrentSubscription, reconcileSubscription },
    }))

    const SubscriptionManager = (await import('../components/billing/SubscriptionManager')).default
    const props = {
      authToken: null,
      billingStatus: availableBillingStatus,
      checkoutReturned: true,
      onUpgrade: vi.fn(),
    }
    hookIndex = 0
    SubscriptionManager(props)
    const cleanup = effects[0]()
    await Promise.resolve()
    await Promise.resolve()
    hookIndex = 0
    const view = SubscriptionManager(props) as VNode

    expect(reconcileSubscription).not.toHaveBeenCalled()
    expect(findButton(view, 'Check payment status')).toBeNull()
    cleanup?.()
  })
})
