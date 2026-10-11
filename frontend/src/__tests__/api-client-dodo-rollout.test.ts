import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/lib/api-client'

const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status, headers: { 'content-type': 'application/json' },
})
const plans = (provider?: string | null, available = true) => ({
  plans: { free: { id: 'free' } },
  billing: { provider, feature_enabled: true, mode: 'enabled', available, message: 'Available' },
})
const actions = {
  create: () => apiClient.createSubscription('basic', 'owner@example.com', 'Owner'),
  cancel: () => apiClient.cancelSubscription(),
  reconcile: () => apiClient.reconcileSubscription(),
  student: () => apiClient.verifyStudentSubscription('student/token'),
}
const paths = {
  create: '/billing/dodo/subscription/create',
  cancel: '/billing/dodo/subscription/cancel',
  reconcile: '/billing/dodo/subscription/reconcile',
  student: '/billing/dodo/subscription/student/verify/student%2Ftoken',
}

afterEach(() => {
  vi.unstubAllGlobals()
  apiClient.setAuthToken(null)
})

describe('Dodo-only staged frontend rollout', () => {
  it.each([undefined, null, 'razorpay', 'unknown'])(
    'fails closed for provider %s even when the old backend reports billing available', async provider => {
      const fetch = vi.fn().mockImplementation(() => Promise.resolve(response(plans(provider))))
      vi.stubGlobal('fetch', fetch)
      apiClient.setAuthToken('owner-token')
      const catalog = await apiClient.getSubscriptionPlans()
      expect(catalog.data?.plans).toEqual({ free: { id: 'free' } })
      expect(catalog.data?.billing).toMatchObject({
        provider: null, available: false, reason: 'billing_backend_update_required',
      })
      for (const action of Object.values(actions)) {
        expect(await action()).toMatchObject({ success: false, error: expect.stringContaining('after the update') })
      }
      expect(fetch).toHaveBeenCalledTimes(5)
      for (const [url, init] of fetch.mock.calls as [string, RequestInit][]) {
        expect(new URL(url, 'http://localhost').pathname).toBe('/subscription/plans')
        expect(init.method ?? 'GET').toBe('GET')
        expect(init.cache).toBe('no-store')
      }
    },
  )

  it.each(Object.keys(actions) as Array<keyof typeof actions>)(
    'dispatches %s exclusively to a Dodo-only route after an uncached identity check', async action => {
      const fetch = vi.fn().mockResolvedValueOnce(response(plans('dodo')))
        .mockResolvedValueOnce(response({ success: true, status: 'pending' }))
      vi.stubGlobal('fetch', fetch)
      apiClient.setAuthToken('owner-token')
      expect((await actions[action]()).success).toBe(true)
      expect(fetch).toHaveBeenCalledTimes(2)
      const [url, init] = fetch.mock.calls[1] as [string, RequestInit]
      expect(new URL(url, 'http://localhost').pathname).toBe(paths[action])
      expect(new Headers(init.headers).get('authorization')).toBe('Bearer owner-token')
    },
  )

  it.each(Object.keys(actions) as Array<keyof typeof actions>)(
    'never falls back to the old %s route when a rolling old instance returns 404', async action => {
      const fetch = vi.fn().mockResolvedValueOnce(response(plans('dodo')))
        .mockResolvedValueOnce(response({ detail: 'Not Found' }, 404))
      vi.stubGlobal('fetch', fetch)
      apiClient.setAuthToken('owner-token')
      expect((await actions[action]()).success).toBe(false)
      expect(fetch).toHaveBeenCalledTimes(2)
      expect(new URL(fetch.mock.calls[1][0], 'http://localhost').pathname).toBe(paths[action])
    },
  )

  it.each(['cancel', 'reconcile'] as const)('allows existing Dodo %s when new sales are disabled', async action => {
    const fetch = vi.fn().mockResolvedValueOnce(response(plans('dodo', false)))
      .mockResolvedValueOnce(response({ success: true, status: 'pending' }))
    vi.stubGlobal('fetch', fetch)
    apiClient.setAuthToken('owner-token')
    expect((await actions[action]()).success).toBe(true)
    expect(new URL(fetch.mock.calls[1][0], 'http://localhost').pathname).toBe(paths[action])
  })

  it('preserves read-only current-subscription access without a capability handshake', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ userId: 'owner', planId: 'pro' }))
    vi.stubGlobal('fetch', fetch)
    apiClient.setAuthToken('owner-token')
    expect((await apiClient.getCurrentSubscription()).success).toBe(true)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(new URL(fetch.mock.calls[0][0], 'http://localhost').pathname).toBe('/subscription/current')
  })

  it('rechecks account ownership between the capability read and mutation dispatch', async () => {
    let resolve!: (value: Response) => void
    const fetch = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r }))
    vi.stubGlobal('fetch', fetch)
    apiClient.setAuthToken('owner-token')
    const pending = apiClient.createSubscription('basic', 'owner@example.com', 'Owner', {}, {
      authToken: 'owner-token', isCurrent: () => true,
    })
    for (let i = 0; i < 6; i += 1) await Promise.resolve()
    apiClient.setAuthToken('other-owner')
    resolve(response(plans('dodo')))
    expect((await pending).success).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
