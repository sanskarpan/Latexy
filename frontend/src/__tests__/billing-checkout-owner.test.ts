import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }
function nodes(node: unknown): VNode[] {
  if (!node || typeof node !== 'object') return []
  const n = node as VNode
  const children = n.props?.children
  return [n, ...(Array.isArray(children) ? children : [children]).flatMap(nodes)]
}
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve() }
const paid = {
  userId: 'account-a', planId: 'pro', planName: 'Pro', status: 'active', subscriptionId: 'sub-a',
  features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
}
async function harness() {
  let session = { user: { id: 'account-a', email: 'a@example.com', name: 'A' }, session: { token: 'token-a' } }
  let index = 0
  const states: unknown[] = [], refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const tab = { opener: null, close: vi.fn(), location: { href: '' } }
  vi.stubGlobal('window', { open: vi.fn().mockReturnValue(tab), location: { pathname: '/billing', search: '?checkout=return', origin: 'http://localhost' }, scrollTo: vi.fn() })
  vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
  const plans = Object.fromEntries(['free', 'basic', 'pro'].map(id => [id, { id, name: id, price: id === 'free' ? 0 : 100, currency: 'INR', interval: 'month', features: paid.features }]))
  const api = {
    getSubscriptionPlans: vi.fn().mockResolvedValue({ success: true, data: { plans, billing: { available: true } } }),
    createSubscription: vi.fn(),
    cancelSubscription: vi.fn().mockResolvedValue({ success: true }),
    getCurrentSubscription: vi.fn().mockResolvedValue({ success: true, data: { ...paid, status: 'cancel_scheduled' } }),
  }
  const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() }
  vi.doMock('react', () => ({
    Suspense: 'Suspense', useMemo: (fn: () => unknown) => fn(), useCallback: (fn: unknown) => fn,
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useRef: (value: unknown) => { const i = index++; return refs[i] ??= { current: value } },
    useState: (value: unknown) => {
      const i = index++; if (!(i in states)) states[i] = value
      return [states[i], (next: unknown) => { states[i] = typeof next === 'function' ? (next as (old: unknown) => unknown)(states[i]) : next }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({ jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }), jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }) }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams('checkout=return') }))
  vi.doMock('@/contexts/FeatureFlagsContext', () => ({ useFeatureFlags: () => ({ billing: true }) }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: session, isPending: false, error: null }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('sonner', () => ({ toast }))
  vi.doMock('@/components/billing/PricingCard', () => ({ default: 'PricingCard' }))
  vi.doMock('@/components/billing/SubscriptionManager', () => ({ default: 'SubscriptionManager' }))
  const page = (await import('../app/billing/page')).default() as VNode
  const Content = (page.props.children as VNode).type as () => VNode
  return {
    api, toast, tab,
    render() { index = 0; effects = []; return Content() },
    runEffects() { effects.forEach(effect => effect()) },
    switchAccount() { session = { user: { id: 'account-b', email: 'b@example.com', name: 'B' }, session: { token: 'token-b' } } },
  }
}
afterEach(() => {
  vi.unstubAllGlobals()
  for (const name of ['react', 'react/jsx-runtime', 'next/link', 'next/navigation', '@/contexts/FeatureFlagsContext', '@/lib/auth-client', '@/lib/api-client', 'sonner', '@/components/billing/PricingCard', '@/components/billing/SubscriptionManager']) vi.doUnmock(name)
  vi.resetModules()
})

describe('billing page checkout and cancellation ownership', () => {
  it('refreshes the subscription card and prevents competing plan changes after selecting Free', async () => {
    const h = await harness()
    h.render(); h.runEffects(); await flush()
    const manager = nodes(h.render()).find(n => n.type === 'SubscriptionManager')!
    ;(manager.props.onLoaded as (subscription: unknown) => void)(paid)
    const freeCard = nodes(h.render()).find(n => n.type === 'PricingCard' && (n.props.plan as { id: string }).id === 'free')!
    await (freeCard.props.onSelectPlan as (id: string) => Promise<void>)('free')
    const view = h.render()
    expect(nodes(view).find(n => n.type === 'SubscriptionManager')!.props.refreshKey).toBe(1)
    expect(nodes(view).filter(n => n.type === 'PricingCard').every(n => n.props.disabled)).toBe(true)
    expect(h.api.cancelSubscription.mock.calls[0][0].authToken).toBe('token-a')
  })

  it('closes the preopened checkout tab instead of navigating after an account switch', async () => {
    const h = await harness()
    let resolve!: (value: unknown) => void
    h.api.createSubscription.mockImplementation(() => new Promise(r => { resolve = r }))
    h.render(); h.runEffects(); await flush()
    const card = nodes(h.render()).find(n => n.type === 'PricingCard' && (n.props.plan as { id: string }).id === 'basic')!
    const request = (card.props.onSelectPlan as (id: string) => Promise<void>)('basic')
    await flush()
    expect(h.api.createSubscription).toHaveBeenCalledTimes(1)
    const context = h.api.createSubscription.mock.calls[0][4]
    expect(context.authToken).toBe('token-a')
    h.switchAccount(); h.render()
    resolve({ success: true, data: { shortUrl: 'https://checkout.example.test/old-account' } })
    await request
    expect(context.isCurrent()).toBe(false)
    expect(h.tab.close).toHaveBeenCalledTimes(1)
    expect(h.tab.location.href).toBe('')
    expect(h.toast.success).not.toHaveBeenCalled()
  })

  it('keeps Free current when the account only has a historical provider subscription ID', async () => {
    const h = await harness()
    h.render(); h.runEffects(); await flush()
    const manager = nodes(h.render()).find(n => n.type === 'SubscriptionManager')!
    ;(manager.props.onLoaded as (subscription: unknown) => void)({ ...paid, planId: 'free', planName: 'Free', status: 'cancelled' })
    const freeCard = nodes(h.render()).find(n => n.type === 'PricingCard' && (n.props.plan as { id: string }).id === 'free')!
    expect(freeCard.props.disabled).toBe(true)
    await (freeCard.props.onSelectPlan as (id: string) => Promise<void>)('free')
    expect(h.api.cancelSubscription).not.toHaveBeenCalled()
  })

})
