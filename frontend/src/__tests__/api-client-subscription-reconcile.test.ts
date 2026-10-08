import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/lib/api-client'

afterEach(() => {
  vi.unstubAllGlobals()
  apiClient.setAuthToken(null)
})

describe('subscription reconciliation API', () => {
  it('sends an authenticated bodyless POST and returns the backend status', async () => {
    const previousToken = apiClient.getAuthToken()
    const fetchMock = vi.fn().mockResolvedValue(
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
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(new URL(url, 'http://localhost').pathname).toBe('/subscription/reconcile')
      expect(init.method).toBe('POST')
      expect(init.body).toBeUndefined()
      expect(new Headers(init.headers).get('authorization')).toBe('Bearer billing-test-session')
    } finally {
      apiClient.setAuthToken(previousToken)
    }
  })
})
