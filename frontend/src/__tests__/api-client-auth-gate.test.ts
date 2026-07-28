import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

/**
 * The auth-ready gate makes requests wait for AuthSync to publish the Better Auth
 * session state, but the wait must be *bounded* — a slow/hanging session endpoint
 * must not deadlock the app (including anonymous flows like /try).
 *
 * The gate only exists in the browser, so these tests stub `window` before
 * importing a fresh module instance.
 */

function mockFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: {},
    json: () => Promise.resolve({}),
    text: () => Promise.resolve('{}'),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function loadBrowserApiClient() {
  vi.resetModules()
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  const mod = await import('../lib/api-client')
  return mod.apiClient
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('ApiClient auth-ready gate', () => {
  test('holds a request until AuthSync reports the session state', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-123')
    client.markAuthResolved()
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-123')
  })

  test('falls through unauthenticated if the session never resolves', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    // No setAuthToken / markAuthResolved at all — the deadline must open the gate.
    await vi.advanceTimersByTimeAsync(2000)
    await pending

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBeUndefined()
  })

  test('a null token from a page does not open the gate early', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    // A page mirroring its own (not yet hydrated) session token must not release
    // the gate — otherwise the request goes out without the token AuthSync is
    // about to publish.
    client.setAuthToken(null)
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-456')
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-456')
  })

  test('raw-fetch helpers are gated too (deleteResume)', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.deleteResume('resume-1')
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-789')
    client.markAuthResolved()
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-789')
  })
})
