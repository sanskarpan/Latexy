import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/lib/api-client'

afterEach(() => {
  vi.unstubAllGlobals()
  apiClient.setAuthToken(null)
})

describe('subscription reconciliation API', () => {
  it('sends an authenticated bodyless POST and returns the backend status', async () => {
    const previousToken = apiClient.getAuthToken()
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ billing: { provider: 'dodo' } }), { headers: { 'content-type': 'application/json' } })).mockResolvedValueOnce(
      new Response(JSON.stringify({ success: true, status: 'pending' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    apiClient.setAuthToken('billing-test-session')

    try {
      const result = await apiClient.reconcileSubscription()

      expect(result).toEqual({
        success: true,
        data: { success: true, status: 'pending' },
      })
      expect(fetchMock).toHaveBeenCalledTimes(2)
      const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit]
      expect(new URL(url, 'http://localhost').pathname).toBe('/billing/dodo/subscription/reconcile')
      expect(init.method).toBe('POST')
      expect(init.body).toBeUndefined()
      expect(new Headers(init.headers).get('authorization')).toBe('Bearer billing-test-session')
    } finally {
      apiClient.setAuthToken(previousToken)
    }
  })

  it.each(['getCurrentSubscription', 'reconcileSubscription', 'cancelSubscription'] as const)(
    'binds %s dispatch to its captured account', async (method) => {
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      apiClient.setAuthToken('account-b')
      const result = await apiClient[method]({ authToken: 'account-a', isCurrent: () => true })
      expect(result.success).toBe(false)
      expect(fetchMock).not.toHaveBeenCalled()

      apiClient.setAuthToken('account-a')
      const stale = await apiClient[method]({ authToken: 'account-a', isCurrent: () => false })
      expect(stale.success).toBe(false)
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )


  it('does not dispatch checkout creation under another account token', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    apiClient.setAuthToken('account-b')
    const result = await apiClient.createSubscription('basic', 'a@example.com', 'A', {}, {
      authToken: 'account-a', isCurrent: () => true,
    })
    expect(result.success).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

})
