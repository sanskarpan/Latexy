import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.useRealTimers()
  for (const moduleName of ['react', 'react/jsx-runtime', '@/lib/api-client']) {
    vi.doUnmock(moduleName)
  }
  vi.resetModules()
})

describe('billing checkout return confirmation', () => {
  it('refreshes a pending checkout until Dodo confirms the paid entitlement', async () => {
    vi.useFakeTimers()
    const pending = {
      userId: 'user-1', planId: 'free', planName: 'Free', status: 'checkout_pending',
      features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
    }
    const active = {
      ...pending, planId: 'pro', planName: 'Pro', status: 'active', subscriptionId: 'sub-1',
    }
    const pastDue = { ...active, status: 'past_due' }
    const getCurrentSubscription = vi.fn()
      .mockResolvedValueOnce({ success: true, data: pending })
      .mockResolvedValueOnce({ success: true, data: pastDue })
      .mockResolvedValueOnce({ success: true, data: active })
    const reconcileSubscription = vi.fn().mockResolvedValue({
      success: true,
      data: { success: false, status: 'pending' },
    })
    const effects: Array<() => void | (() => void)> = []
    let hookIndex = 0
    const states: unknown[] = []

    vi.doMock('react', () => ({
      useCallback: (callback: unknown) => callback,
      useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
      useState: (initial: unknown) => {
        const index = hookIndex++
        if (!(index in states)) states[index] = initial
        return [states[index], (value: unknown) => {
          states[index] = typeof value === 'function'
            ? (value as (previous: unknown) => unknown)(states[index])
            : value
        }]
      },
      useRef: (initial: unknown) => ({ current: initial }),
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
    SubscriptionManager({
      authToken: 'session-token',
      billingStatus: {
        featureEnabled: true,
        mode: 'enabled',
        available: true,
        reason: null,
        message: 'Available',
      },
      checkoutReturned: true,
      onUpgrade: vi.fn(),
      onLoaded,
    })
    const cleanup = effects[0]()

    await Promise.resolve()
    await Promise.resolve()
    expect(reconcileSubscription).toHaveBeenCalledTimes(1)
    expect(getCurrentSubscription).toHaveBeenCalledTimes(1)
    expect(onLoaded).toHaveBeenLastCalledWith(pending)

    await vi.advanceTimersByTimeAsync(2_500)
    expect(getCurrentSubscription).toHaveBeenCalledTimes(2)
    expect(onLoaded).toHaveBeenLastCalledWith(pastDue)
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(2_500)
    expect(getCurrentSubscription).toHaveBeenCalledTimes(3)
    expect(reconcileSubscription).toHaveBeenCalledTimes(1)
    expect(onLoaded).toHaveBeenLastCalledWith(active)
    expect(vi.getTimerCount()).toBe(0)
    cleanup?.()
  })
})
