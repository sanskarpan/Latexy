import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/lib/api-client'

afterEach(() => {
  apiClient.setAuthToken(null)
  apiClient.setTenantSlug(null)
  vi.unstubAllGlobals()
})

describe('entitlements API request', () => {
  it('requests only feature grants without caching and forwards cancellation', async () => {
    const response = { features: { c09: true } }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: { 'content-type': 'application/json' },
      json: () => Promise.resolve(response),
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await expect(apiClient.getEntitlements(controller.signal)).resolves.toEqual(response)

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${apiClient.baseUrl}/config/entitlements?include_quotas=false`)
    expect(init.cache).toBe('no-store')
    expect(init.signal).toBe(controller.signal)
  })
})
