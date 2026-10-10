import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }
const billingStatus = { featureEnabled: true, mode: 'enabled' as const, available: true, reason: null, message: 'Available' }
const free = {
  userId: 'account-b', planId: 'free', planName: 'Free', status: 'checkout_pending',
  subscriptionId: null,
  features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
}
const paid = { ...free, userId: 'account-a', planId: 'pro', planName: 'Pro', status: 'active', subscriptionId: 'sub-a' }
const deferred = () => {
  let resolve!: (value: unknown) => void
  const promise = new Promise(resolvePromise => { resolve = resolvePromise })
  return { promise, resolve }
}
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve() }
function nodes(node: unknown): VNode[] {
  if (!node || typeof node !== 'object') return []
  const n = node as VNode
  const children = n.props?.children
  return [n, ...(Array.isArray(children) ? children : [children]).flatMap(nodes)]
}
function button(view: VNode, label: string) {
  return nodes(view).find(n => n.type === 'button' && n.props.children === label)
}
async function harness() {
  const getCurrentSubscription = vi.fn().mockResolvedValue({ success: true, data: free })
  const reconcileSubscription = vi.fn().mockResolvedValue({ success: true, data: { status: 'pending' } })
  const cancelSubscription = vi.fn().mockResolvedValue({ success: true })
  const onLoaded = vi.fn()
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  let index = 0
  let effects: Array<() => void | (() => void)> = []
  vi.doMock('react', () => ({
    useCallback: (callback: unknown) => callback,
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useRef: (initial: unknown) => { const i = index++; return refs[i] ??= { current: initial } },
    useState: (initial: unknown) => {
      const i = index++
      if (!(i in states)) states[i] = initial
      return [states[i], (value: unknown) => {
        states[i] = typeof value === 'function' ? (value as (old: unknown) => unknown)(states[i]) : value
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getCurrentSubscription, reconcileSubscription, cancelSubscription } }))
  const Manager = (await import('../components/billing/SubscriptionManager')).default
  const props = { authToken: 'token-a', billingStatus, onLoaded, onUpgrade: vi.fn(), checkoutReturned: true }
  return {
    getCurrentSubscription, reconcileSubscription, cancelSubscription, onLoaded,
    render(overrides: Partial<Parameters<typeof Manager>[0]> = {}) {
      index = 0
      effects = []
      return Manager({ ...props, ...overrides }) as VNode
    },
    effect() { return effects[0]() as () => void },
  }
}
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  for (const name of ['react', 'react/jsx-runtime', '@/lib/api-client']) vi.doUnmock(name)
  vi.resetModules()
})

describe('billing owner and checkout recovery interactions', () => {
  it('keeps recovery visible when lifecycle supplies a subscription ID before payment', async () => {
    vi.useFakeTimers()
    const h = await harness()
    h.getCurrentSubscription.mockResolvedValue({ success: true, data: { ...free, subscriptionId: 'sub-unpaid' } })
    h.reconcileSubscription.mockResolvedValue({ success: false, error: 'provider unavailable' })
    h.render(); const cleanup = h.effect(); await flush()
    const view = h.render()
    expect(button(view, 'Check payment status')).toBeDefined()
    expect(button(view, 'Cancel')).toBeUndefined()
    expect(button(view, 'Change Plan')).toBeUndefined()
    expect(nodes(view).some(n => n.props?.role === 'alert' && n.props.children === 'provider unavailable')).toBe(true)
    await (button(view, 'Check payment status')!.props.onClick as () => Promise<void>)()
    await flush()
    expect(h.reconcileSubscription).toHaveBeenCalledTimes(2)
    cleanup()
  })

  it('ignores the previous account response even when it completes last', async () => {
    const h = await harness(), a = deferred(), b = deferred()
    h.getCurrentSubscription.mockImplementationOnce(() => a.promise).mockImplementationOnce(() => b.promise)
    h.render({ checkoutReturned: false }); const cleanupA = h.effect()
    cleanupA()
    h.render({ authToken: 'token-b', checkoutReturned: false }); const cleanupB = h.effect()
    b.resolve({ success: true, data: free }); await flush()
    a.resolve({ success: true, data: paid }); await flush()
    expect(h.onLoaded).toHaveBeenCalledTimes(1)
    expect(h.onLoaded).toHaveBeenLastCalledWith(free)
    const context = h.getCurrentSubscription.mock.calls[0][0]
    expect(context.authToken).toBe('token-a')
    expect(context.isCurrent()).toBe(false)
    cleanupB()
  })

  it('invalidates an A request across an A-B-A account round trip', async () => {
    const h = await harness(), a = deferred()
    h.getCurrentSubscription.mockImplementationOnce(() => a.promise)
    h.render({ checkoutReturned: false }); const cleanupA = h.effect()
    h.render({ authToken: 'token-b', checkoutReturned: false }); cleanupA()
    const cleanupB = h.effect()
    h.render({ checkoutReturned: false }); cleanupB(); const cleanupNewA = h.effect()
    await flush()
    h.onLoaded.mockClear()
    a.resolve({ success: true, data: paid }); await flush()
    expect(h.onLoaded).not.toHaveBeenCalled()
    cleanupNewA()
  })

  it('transfers an automatic reconciliation through effect replay without trapping its spinner', async () => {
    vi.useFakeTimers()
    const h = await harness(), recovery = deferred()
    h.reconcileSubscription.mockImplementation(() => recovery.promise)
    h.render(); const oldCleanup = h.effect(); oldCleanup()
    h.render(); const cleanup = h.effect()
    recovery.resolve({ success: false, error: 'temporary failure' }); await flush()
    const retry = button(h.render(), 'Check payment status')
    expect(h.reconcileSubscription).toHaveBeenCalledTimes(1)
    expect(retry?.props.disabled).toBe(false)
    cleanup()
  })

  it('does not hide authenticated retry because of an untrusted failed return query', async () => {
    const h = await harness()
    h.reconcileSubscription.mockResolvedValue({ success: false, error: 'network unavailable' })
    h.render({ checkoutStatus: 'failed' }); const cleanup = h.effect(); await flush()
    expect(button(h.render({ checkoutStatus: 'failed' }), 'Check payment status')).toBeDefined()
    cleanup()
  })

  it('does not publish or refetch after unmounting during reconciliation', async () => {
    const h = await harness(), recovery = deferred()
    h.reconcileSubscription.mockImplementation(() => recovery.promise)
    h.render(); const cleanup = h.effect(); cleanup()
    recovery.resolve({ success: false, error: 'late error' }); await flush()
    expect(h.getCurrentSubscription).not.toHaveBeenCalled()
    expect(h.onLoaded).not.toHaveBeenCalled()
  })

  it('suppresses repeated cancellation clicks and a stale completion after account switch', async () => {
    const h = await harness(), cancellation = deferred()
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    h.getCurrentSubscription.mockResolvedValueOnce({ success: true, data: paid })
    h.cancelSubscription.mockImplementation(() => cancellation.promise)
    h.render({ checkoutReturned: false }); const cleanupA = h.effect(); await flush()
    const cancel = button(h.render({ checkoutReturned: false }), 'Cancel')!
    const first = (cancel.props.onClick as () => Promise<void>)()
    await (cancel.props.onClick as () => Promise<void>)()
    expect(h.cancelSubscription).toHaveBeenCalledTimes(1)
    cleanupA(); h.render({ authToken: 'token-b', checkoutReturned: false }); const cleanupB = h.effect(); await flush()
    cancellation.resolve({ success: true }); await first
    expect(h.getCurrentSubscription).toHaveBeenCalledTimes(2)
    expect(h.onLoaded).toHaveBeenLastCalledWith(free)
    cleanupB()
  })

  it('refreshes the card after an external Free cancellation action', async () => {
    const h = await harness()
    h.getCurrentSubscription.mockResolvedValueOnce({ success: true, data: paid })
      .mockResolvedValueOnce({ success: true, data: { ...paid, status: 'cancel_scheduled' } })
    h.render({ checkoutReturned: false }); const oldCleanup = h.effect(); await flush()
    expect(button(h.render({ checkoutReturned: false }), 'Cancel')).toBeDefined()
    oldCleanup(); h.render({ checkoutReturned: false, refreshKey: 1 }); const cleanup = h.effect(); await flush()
    expect(button(h.render({ checkoutReturned: false, refreshKey: 1 }), 'Cancel')).toBeUndefined()
    expect(h.onLoaded).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'cancel_scheduled' }))
    cleanup()
  })

  it('offers recovery for a pending checkout reopened without return query parameters', async () => {
    const h = await harness()
    h.render({ checkoutReturned: false }); const cleanup = h.effect(); await flush()
    const retry = button(h.render({ checkoutReturned: false }), 'Check payment status')
    expect(retry).toBeDefined()
    expect(h.reconcileSubscription).not.toHaveBeenCalled()
    await (retry!.props.onClick as () => Promise<void>)()
    await flush()
    expect(h.reconcileSubscription).toHaveBeenCalledTimes(1)
    cleanup()
  })


  it('can recover an existing Dodo checkout when new sales are disabled', async () => {
    vi.useFakeTimers()
    const h = await harness()
    const props = { billingStatus: { ...billingStatus, available: false } }
    h.render(props); const cleanup = h.effect(); await flush()
    expect(h.reconcileSubscription).toHaveBeenCalledTimes(1)
    const retry = button(h.render(props), 'Check payment status')!
    expect(retry.props.disabled).toBe(false)
    await (retry.props.onClick as () => Promise<void>)(); await flush()
    expect(h.reconcileSubscription).toHaveBeenCalledTimes(2)
    cleanup()
  })

  it('keeps existing Dodo cancellation available when new sales are disabled', async () => {
    const h = await harness()
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    h.getCurrentSubscription.mockResolvedValue({ success: true, data: paid })
    const props = { checkoutReturned: false, billingStatus: { ...billingStatus, available: false } }
    h.render(props); const cleanup = h.effect(); await flush()
    const cancel = button(h.render(props), 'Cancel')!
    expect(cancel.props.disabled).toBe(false)
    await (cancel.props.onClick as () => Promise<void>)()
    expect(h.cancelSubscription).toHaveBeenCalledTimes(1)
    cleanup()
  })

})
